#!/usr/bin/env bash
set -e
# Run ON Lenovo to always pull latest closed build (no source, no git)
# https://qa.awesometech.com.ng is served via Caddy
REG=${REG:-ghcr.io/awesome56/qa-agent}
TAG=${TAG:-closed}
cd ~/qa-agent
echo "Pulling $REG:$TAG (private ghcr.io, requires login)..."
if [ -n "$GHCR_PAT" ]; then echo "$GHCR_PAT" | docker login ghcr.io -u ${GHCR_USER:-awesome56} --password-stdin; fi
if [ -f ~/.ghcr_pat ]; then cat ~/.ghcr_pat | docker login ghcr.io -u awesome56 --password-stdin; fi
docker compose pull
docker compose up -d
echo "Updated. Health:"
curl -sk http://localhost:8000/health | head -c 500; echo
curl -sk https://qa.awesometech.com.ng/health | head -c 500; echo || echo "(public HTTPS not yet — check DNS/Caddy)"
