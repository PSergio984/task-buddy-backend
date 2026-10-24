#!/usr/bin/env bash
# collect-evidence.sh <evidence-dir>
# Bounded, repeatable, READ-ONLY evidence packet. Runs before any model is
# involved. Every query here is allowlisted — add new sources only as reads.
set -u
DIR="${1:?usage: collect-evidence.sh <evidence-dir>}"
mkdir -p "$DIR"
T() { local out="$1"; shift; timeout "${EVIDENCE_TIMEOUT:-15}" "$@" >"$DIR/$out" 2>&1 || echo "FAILED: $*" >>"$DIR/$out"; }

# deployed state
T docker-ps.txt docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
T compose-ps.txt docker compose -f "${COMPOSE_FILE:-compose.yaml}" ps

# recent logs, tail-bounded (no secrets: keep --tail small, never env dump)
for c in ${MONITORED_CONTAINERS:-app db}; do
  T "logs-$c.txt" docker logs --tail 200 "$c"
done

# metrics — instant queries only
if [ -n "${PROMETHEUS_URL:-}" ]; then
  for q in 'up' 'rate(http_requests_total{status=~"5.."}[5m])'; do
    name=$(echo "$q" | tr -cd 'a-z0-9' | head -c 24)
    T "prom-$name.json" curl -sfG "$PROMETHEUS_URL/api/v1/query" --data-urlencode "query=$q"
  done
fi

# app liveness
[ -n "${APP_HEALTH_URL:-}" ] && T health.json curl -sf "$APP_HEALTH_URL"

# traces/logs lookup for the alert window — point at your Grafana/Loki/Tempo
# datasource proxies here if used; keep GET-only.
echo "collected at $(date -Is)" > "$DIR/_index.txt"
ls "$DIR" >> "$DIR/_index.txt"
