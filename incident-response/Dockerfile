# alert-bridge needs bash (spawns collect-evidence.sh), docker CLI
# (evidence: docker ps/logs via mounted socket), and curl (Prometheus/health).
# Debian's docker.io ships an API-too-old client for modern daemons —
# take the official CLI matching Docker 29's minimum API instead.
FROM docker:29-cli AS dockercli

FROM node:22-slim

COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/incident-response
# Explicit file list — a blanket COPY could sweep secrets or incident output
# into the image; incidents/ is runtime state, created below.
COPY alert-bridge.mjs autonomy-policy.yaml collect-evidence.sh responder-task.md response.schema.json test-incident.sh ./
COPY runbooks/ ./runbooks/
# Only runtime state is writable — the policy file and scripts the bridge
# executes stay root-owned so the long-lived process can't rewrite its own
# policy boundary.
RUN mkdir -p incidents && chown node:node incidents
USER node

EXPOSE 9099
CMD ["node", "alert-bridge.mjs"]
