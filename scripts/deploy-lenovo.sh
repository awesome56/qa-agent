#!/usr/bin/env bash
set -e
# Deploy closed image to Lenovo server and expose as https://qa.awesometech.com.ng via Caddy (auto HTTPS)
# Usage: LENOVO_HOST=192.168.1.100 LENOVO_USER=apple ./scripts/deploy-lenovo.sh
# Prereq on Lenovo: Docker + 80/443 open + DNS A qa.awesometech.com.ng -> Lenovo public IP

HOST=${LENOVO_HOST:-lenovo}
USER=${LENOVO_USER:-$USER}
REMOTE_DIR=${REMOTE_DIR:-~/qa-agent}
REG=${REG:-ghcr.io/awesome56/qa-agent}
TAG=${TAG:-closed}

echo "-> Preparing remote dir $USER@$HOST:$REMOTE_DIR"
ssh $USER@$HOST "mkdir -p $REMOTE_DIR/storage"

echo "-> Copying prod compose + Caddyfile + env"
scp docker-compose.prod.yml $USER@$HOST:$REMOTE_DIR/docker-compose.yml
scp Caddyfile $USER@$HOST:$REMOTE_DIR/Caddyfile
scp nginx.conf $USER@$HOST:$REMOTE_DIR/nginx.conf
# copy .env.prod if exists, else example
if [ -f .env.prod ]; then scp .env.prod $USER@$HOST:$REMOTE_DIR/.env.prod; else scp .env.example $USER@$HOST:$REMOTE_DIR/.env.prod; fi

echo "-> On Lenovo: login GHCR + pull closed image + up with Caddy"
ssh $USER@$HOST bash <<'REMOTE'
set -e
cd ~/qa-agent
if [ -n "$GHCR_PAT" ]; then echo "$GHCR_PAT" | docker login ghcr.io -u ${GHCR_USER:-awesome56} --password-stdin; fi
# also try local PAT
if [ -f ~/.ghcr_pat ]; then cat ~/.ghcr_pat | docker login ghcr.io -u awesome56 --password-stdin; fi
docker compose pull
docker compose up -d
docker compose ps
echo "--- caddy logs (last 20) ---"
docker compose logs caddy --tail 20 || true
echo "--- api health ---"
sleep 3
curl -sk http://localhost:8000/health | head -c 300; echo
echo "Try public: https://qa.awesometech.com.ng/health (needs DNS + 80/443)"
REMOTE

echo "-> Done. If DNS ready, check: curl https://qa.awesometech.com.ng/health"
echo "-> GitHub webhook: https://qa.awesometech.com.ng/webhook/github"
