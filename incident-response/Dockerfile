# alert-bridge needs bash (spawns collect-evidence.sh), docker CLI
# (evidence: docker ps/logs via mounted socket), and curl (Prometheus/health).
FROM node:22-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl docker.io \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/incident-response
COPY . .

EXPOSE 9099
CMD ["node", "alert-bridge.mjs"]
