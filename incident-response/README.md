# incident-response — AI on-call responder pack

Drop this folder into your app repo. Alert → bounded evidence packet → headless
coding agent (read-only) → policy gate → allowlisted fix → recovery check →
auditable incident record. The model proposes; code enforces permission.

```text
Alertmanager/Grafana --webhook--> alert-bridge.mjs :9099
   |                                 |
   |                                 +-> incidents/<id>/alert.json
   |                                 +-> collect-evidence.sh  (read-only, allowlisted)
   |                                 +-> agent (claude/codex/devin headless)
   |                                 |      responder-task.md + evidence -> response.json
   |                                 +-> autonomy-policy.yaml gate
   |                                 +-> execute | escalate
   |                                 +-> runbooks/verify-recovery.sh
   +---------------------------------+-> summary.md (audit trail)
```

## Setup

```bash
export APP_HEALTH_URL=http://localhost:3000/health   # required by verify-recovery
export PROMETHEUS_URL=http://localhost:9090           # optional metrics
export MONITORED_CONTAINERS="app db"                  # optional log tails
export ONCALL_AGENT_CMD='claude -p "$(cat "$ONCALL_PROMPT_FILE")"'   # default
# codex:  ONCALL_AGENT_CMD='codex exec --skip-git-repo-check "$(cat "$ONCALL_PROMPT_FILE")"'

node alert-bridge.mjs
```

Point Alertmanager at it:

```yaml
receivers:
  - name: oncall-bridge
    webhook_configs:
      - url: http://localhost:9099/alert
```

Grafana: contact point → Webhook → `http://<host>:9099/alert`.

## Test without a real outage

```bash
ONCALL_DRY_RUN=1 node alert-bridge.mjs &   # never executes proposed commands
bash test-incident.sh                      # synthetic firing alert
ls incidents/                              # inspect the incident record
```

`POST /test` fires the same synthetic alert; `GET /health` liveness.

## Capability table (the responder as attack surface)

| Capability | Granted | Enforced by |
|---|---|---|
| Read incident evidence | yes | files under incidents/<id>/ |
| Read app source | yes | agent cwd = repo |
| Query telemetry | via packet only | collect-evidence.sh allowlist |
| Execute shell in prod | no | agent never gets credentials |
| Mutate state | only via policy | autonomy-policy.yaml gate, outside the model |
| Write fix code | worktree + PR | `open-pr` action, human merges |
| Network | loopback bridge only | run bridge on localhost / private net |

Audit: each incident dir keeps alert, evidence, prompt, raw agent output,
parsed response, executed command, verification log, and escalation reason —
everything needed to reconstruct the incident from the record alone.

## Maps to the course criteria

- **Alerting on user impact (1 pt):** any Alertmanager/Grafana alert → `/alert`.
- **On-call agent (2 pts):** agent wakes on the alert, investigates, proposes;
  allowlisted actions execute + verify; everything else escalates.
- **Module 4 deliverable:** layout matches `incident-response/` exactly.

shortcut: flat-list YAML parse in the bridge — upgrade to a real parser if
autonomy-policy.yaml grows nested structure.
