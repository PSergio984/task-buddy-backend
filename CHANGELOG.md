# Changelog

## 2026-10-25 — Full-stack run + observability + on-call responder

Retrofitted the AI Dev Tools Zoomcamp ops workflow onto the existing app:
one-command full stack, Prometheus/Loki/Tempo/Grafana observability,
user-impact alerting, and the bounded on-call responder. No app behavior
changes — all additions are additive infra/config plus one log-format option.

### Added

- **`app/observability.py`** — `setup_observability(app)` wires OpenTelemetry:
  OTLP trace export to `OTEL_EXPORTER_OTLP_ENDPOINT` (Tempo in compose; skips
  exporter cleanly when unset), `FastAPIInstrumentor` request spans,
  `LoggingInstrumentor` injecting `otelTraceID`/`otelSpanID` into log records,
  and `prometheus-fastapi-instrumentator` serving `/metrics`.
- **`docker-compose.fullstack.yml`** — one command for the entire system:
  Next.js frontend (standalone build, `BACKEND_URL=http://app:8000`), this API,
  Postgres, Redis, Prometheus, Tempo, Loki, Promtail, Grafana, alert-bridge.
  `docker compose -f docker-compose.fullstack.yml config` validates.
- **`observability/`** — Prometheus scrape config, Tempo OTLP receiver config
  (:4317/:4318), Loki single-binary config (tsdb v13, structured metadata),
  Promtail docker_sd pipeline (extracts `level`, `trace_id`, `correlation_id`),
  Grafana provisioning: datasources with bidirectional Loki↔Tempo trace links,
  "Task Buddy — Overview" dashboard, alert contact point + rules.
- **User-impact alerts** (`observability/grafana/provisioning/alerting/`):
  `tb-api-5xx-rate` (>5% 5xx for 2m, critical) and `tb-api-p95-latency`
  (p95 > 3s for 5m, warning) → webhook to `alert-bridge:9099/alert`.
- **`incident-response/`** — the on-call responder pack vendored into the repo:
  `alert-bridge.mjs` (webhook → evidence → bounded agent → escalate),
  `collect-evidence.sh`, `autonomy-policy.yaml`, `responder-task.md`,
  `response.schema.json`, `Dockerfile` (bash + docker CLI + curl for evidence),
  and a real dry-run incident record at `incidents/2026-10-27T07-51-25_*`.
- **`.github/workflows/deploy-production.yml`** — manual dispatch bound to the
  GitHub `production` environment (approval gate) → pre/post-deploy health
  checks → `RENDER_DEPLOY_HOOK`. Safe no-op if the secret is unset.
- **`docs/ops/DEPLOYMENT.md`** — topology, gate setup, rollback paths
  (Render redeploy / git revert / Vercel promote), migration expand-only rule,
  post-deploy smoke checklist.
- **`docs/agents/agent-team.md`** — agent roles, the implement→review→fix→
  re-review loop, standing gates, responder boundary.

### Changed

- **`app/main.py`** — one line: `setup_observability(app)` after `FastAPI()`.
- **`app/logging_conf.py`** — `LOG_FORMAT=json` env swaps the Rich console
  handler for a `StreamHandler` emitting the existing JSON formatter (used in
  containers so Promtail/Loki get parseable logs); JSON format string gains
  `otelTraceID`/`otelSpanID`. Dev behavior unchanged without the env var.
- **`pyproject.toml` / `requirements.txt`** — added `opentelemetry-sdk`,
  `-instrumentation-fastapi`, `-instrumentation-logging`,
  `-exporter-otlp-proto-grpc` (1.44.0 / 0.65b0) and
  `prometheus-fastapi-instrumentator==8.1.0` (8.x required — 7.x pins
  starlette<1 which conflicts with starlette 1.6.0 here) plus transitives.

### Notes / honest limits

- `ONCALL_DRY_RUN=1` in compose: evidence + escalation run for real, proposed
  actions never execute. Set `ONCALL_AGENT_CMD` to enable the agent leg.
- Grafana is on :3001 (frontend owns :3000); default admin/admin — change
  before exposing beyond localhost.
- Local pytest not run for this change (DB env required); covered by
  `python-app.yml` CI.
