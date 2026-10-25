#!/usr/bin/env bash
# test-incident.sh — fires a synthetic alert through the real pipeline.
# Optional arg: real alertname to simulate (default: TestHighErrorRate).
set -eu
PORT="${ONCALL_PORT:-9099}"
NAME="${1:-TestHighErrorRate}"
curl -sf -X POST "http://localhost:$PORT/alert" \
  -H 'content-type: application/json' \
  -d "{
    \"alerts\": [{
      \"status\": \"firing\",
      \"labels\": {\"alertname\": \"$NAME\", \"severity\": \"critical\", \"service\": \"app\"},
      \"annotations\": {\"summary\": \"synthetic test incident — error rate above threshold\"},
      \"startsAt\": \"$(date -Is)\"
    }]
  }" | node -e "let d='';process.stdin.on('data',c=>d+=c).on('end',()=>console.log(JSON.stringify(JSON.parse(d),null,2)))"
