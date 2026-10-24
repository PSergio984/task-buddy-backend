#!/usr/bin/env bash
# verify-recovery.sh — exit 0 only if the service is healthy again.
set -u
URL="${APP_HEALTH_URL:?set APP_HEALTH_URL to your app health endpoint}"
for i in 1 2 3; do
  curl -sf --max-time 10 "$URL" >/dev/null && exit 0
  sleep 5
done
echo "verify-recovery: $URL still failing" >&2
exit 1
