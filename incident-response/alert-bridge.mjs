#!/usr/bin/env node
// alert-bridge — receives Alertmanager/Grafana webhooks and runs the on-call responder.
// Zero deps. Node 18+.
//
// Flow per firing alert:
//   alert -> incidents/<id>/alert.json -> collect-evidence.sh -> headless agent
//         -> response.json (schema-checked) -> autonomy-policy gate -> execute or escalate
//         -> verify-recovery.sh -> summary.md
//
// Endpoints:  GET /health   POST /alert   POST /test
// Env: ONCALL_PORT (9099), ONCALL_AGENT_CMD, PROMETHEUS_URL, APP_HEALTH_URL,
//      ONCALL_DRY_RUN=1 (never execute proposed commands)

import http from 'node:http';
import { spawn } from 'node:child_process';
import { writeFileSync, mkdirSync, readFileSync, existsSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = dirname(fileURLToPath(import.meta.url));
const INCIDENTS = join(ROOT, 'incidents');
const PORT = Number(process.env.ONCALL_PORT || 9099);
const DRY_RUN = process.env.ONCALL_DRY_RUN === '1';
const AGENT_CMD =
  process.env.ONCALL_AGENT_CMD || 'claude -p "$(cat "$ONCALL_PROMPT_FILE")"';

const now = () => new Date().toISOString();
const log = (m) => console.log(`[${now()}] ${m}`);
const sh = (cmd, opts = {}) =>
  new Promise((res) => {
    const p = spawn('bash', ['-c', cmd], { env: process.env, ...opts });
    let out = '';
    p.stdout.on('data', (d) => (out += d));
    p.stderr.on('data', (d) => (out += d));
    p.on('close', (code) => res({ code, out }));
  });

// Normalize Alertmanager v4 and Grafana webhook payloads into one shape.
function normalize(body) {
  if (body.alerts) {
    return body.alerts.map((a) => ({
      status: a.status,
      name: a.labels?.alertname || 'unnamed',
      severity: a.labels?.severity || 'unknown',
      summary: a.annotations?.summary || '',
      description: a.annotations?.description || '',
      startsAt: a.startsAt,
      labels: a.labels || {},
      raw: a,
    }));
  }
  return [
    {
      status: body.status || 'firing',
      name: body.title || body.ruleName || body.labels?.alertname || 'unnamed',
      severity: body.labels?.severity || 'unknown',
      summary: body.message || '',
      description: '',
      startsAt: now(),
      labels: body.labels || {},
      raw: body,
    },
  ];
}

// shortcut: flat-list YAML parse for our own file. Upgrade to a real parser if
// autonomy-policy.yaml gains nesting beyond `allowed_actions` / `escalate_when`.
function readPolicy() {
  const y = readFileSync(join(ROOT, 'autonomy-policy.yaml'), 'utf8').replace(/\r\n/g, '\n');
  const grab = (key) => {
    const m = y.match(new RegExp(`^${key}:\\n((?:  - .+\\n)+)`, 'm'));
    return m
      ? m[1].split('\n')
          .map((l) => l.replace(/^  - /, '').replace(/#.*$/, '').trim())
          .filter(Boolean)
      : [];
  };
  return { allowed: grab('allowed_actions'), escalate: grab('escalate_when') };
}

function extractJson(text) {
  const start = text.indexOf('{');
  const end = text.lastIndexOf('}');
  if (start === -1 || end <= start) return null;
  try {
    const obj = JSON.parse(text.slice(start, end + 1));
    const ok = ['incident_summary', 'root_cause', 'confidence', 'action', 'escalate']
      .every((k) => k in obj);
    return ok ? obj : null;
  } catch {
    return null;
  }
}

async function handleAlert(alert) {
  const slug = alert.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40);
  const id = `${now().replace(/[:.]/g, '-').slice(0, 19)}_${slug}`;
  const dir = join(INCIDENTS, id);
  mkdirSync(join(dir, 'evidence'), { recursive: true });
  writeFileSync(join(dir, 'alert.json'), JSON.stringify(alert, null, 2));
  log(`incident ${id} created (${alert.severity})`);

  // 1. Bounded, read-only evidence packet — before any model is involved.
  const ev = await sh(`bash "${join(ROOT, 'collect-evidence.sh')}" "${join(dir, 'evidence')}"`);
  writeFileSync(join(dir, 'evidence', 'collector.log'), ev.out);

  // 2. Headless agent on the evidence. Prompt = task file + alert + packet index.
  const task = readFileSync(join(ROOT, 'responder-task.md'), 'utf8');
  const evidenceIndex = readdirSync(join(dir, 'evidence')).join('\n');
  const prompt = task
    .replaceAll('{{ALERT_JSON}}', JSON.stringify(alert, null, 2))
    .replaceAll('{{INCIDENT_DIR}}', dir)
    .replaceAll('{{EVIDENCE_INDEX}}', evidenceIndex);
  writeFileSync(join(dir, 'prompt.txt'), prompt);

  const run = await sh(AGENT_CMD, {
    env: { ...process.env, ONCALL_PROMPT_FILE: join(dir, 'prompt.txt'), ONCALL_INCIDENT_DIR: dir },
  });
  writeFileSync(join(dir, 'agent-output.txt'), run.out);

  const response = extractJson(run.out);
  const policy = readPolicy();
  let status, actionLog = '';

  if (!response) {
    status = 'escalated';
    writeFileSync(join(dir, 'escalation.md'),
      `# Escalation: ${id}\n\nAgent produced no schema-valid response.\n\nSee agent-output.txt and evidence/.\n`);
  } else {
    writeFileSync(join(dir, 'response.json'), JSON.stringify(response, null, 2));
    const allowed = policy.allowed.includes(response.action?.type) && !response.escalate;
    if (allowed && !DRY_RUN) {
      const act = await sh(response.action.command, { cwd: ROOT });
      actionLog = `$ ${response.action.command}\n\n${act.out}`;
      const ver = await sh(`bash "${join(ROOT, 'runbooks', 'verify-recovery.sh')}"`);
      writeFileSync(join(dir, 'verification.log'), ver.out);
      status = ver.code === 0 ? 'recovered' : 'escalated';
      if (ver.code !== 0)
        writeFileSync(join(dir, 'escalation.md'),
          `# Escalation: ${id}\n\nAction executed but recovery verification failed.\n`);
    } else if (allowed) {
      status = 'proposed';
      writeFileSync(join(dir, 'escalation.md'),
        `# Dry-run: ${id}\n\nAllowlisted action proposed but dry-run mode — nothing executed.\n\`${response.action.command}\`\n`);
    } else {
      status = 'escalated';
      const why = response.escalate ? response.escalation_reason || 'agent escalated'
        : `action type '${response.action?.type}' not in allowlist`;
      writeFileSync(join(dir, 'escalation.md'), `# Escalation: ${id}\n\n${why}\n`);
    }
  }
  writeFileSync(join(dir, 'action.log'), actionLog);
  writeFileSync(join(dir, 'summary.md'),
    `# ${id}\n\n- alert: ${alert.name} (${alert.severity})\n- status: ${status}${DRY_RUN ? ' (dry-run)' : ''}\n` +
    (response ? `- root cause: ${response.root_cause}\n- action: ${response.action?.type} — \`${response.action?.command}\`\n` : ''));
  log(`incident ${id} -> ${status}`);
  return { id, status };
}

const server = http.createServer(async (req, res) => {
  const send = (code, obj) => {
    res.writeHead(code, { 'content-type': 'application/json' });
    res.end(JSON.stringify(obj));
  };
  if (req.method === 'GET' && req.url === '/health') return send(200, { ok: true });
  if (req.method === 'POST' && (req.url === '/alert' || req.url === '/test')) {
    let body = '';
    req.on('data', (d) => (body += d));
    req.on('end', async () => {
      try {
        const payload = req.url === '/test'
          ? { alerts: [{ status: 'firing', labels: { alertname: 'TestHighErrorRate', severity: 'critical' }, annotations: { summary: 'synthetic test incident' }, startsAt: now() }] }
          : JSON.parse(body || '{}');
        const results = [];
        for (const a of normalize(payload))
          if (a.status === 'firing') results.push(await handleAlert(a));
        send(200, { processed: results.length, results });
      } catch (e) {
        send(500, { error: String(e) });
      }
    });
    return;
  }
  send(404, { error: 'not found' });
});

server.listen(PORT, () => log(`alert-bridge on :${PORT} (dry_run=${DRY_RUN})`));
