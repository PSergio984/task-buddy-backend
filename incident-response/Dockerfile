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
COPY . .

EXPOSE 9099
CMD ["node", "alert-bridge.mjs"]
