# QA Stress Agent — Private Closed Build — `qa.awesometech.com.ng`

Autonomous testing daemon that screen-records web interactions, highlights buttons, runs stress/load tests, and drops a daily report.

**Standalone repo** at `/Users/apple/qa-agent` (NOT under `Awesome_App`). Deploys to Lenovo as `https://qa.awesometech.com.ng` via Caddy auto-TLS. Closed Docker image like opencode v2 — source never leaves GitHub.

Designed as **standalone service** (not a skill) so you can deploy anywhere, run its own RAG/graph/agentic loop via SSE, and let any agent call it. Thin opencode skill wrapper in `Awesome_App/.opencode/skills/qa-stress` points to `https://qa.awesometech.com.ng`.

## Architecture

```
Git Push (GitHub webhook) ──> FastAPI (webhook)
                                ├─> Playwright Worker — records video, injects highlight.js, traces buttons
                                ├─> Stress Worker — k6 / Artillery orchestration
                                ├─> RAG + Graph — ingests logs/traces -> Qdrant/pgvector + Neo4j
                                ├─> Reporter — aggregates -> /reports/daily/{date}.html
                                └─> SSE Daemon — streams progress to any client (opencode, web, other agents)

Any Agent ──> HTTP / MCP ──> QA Agent <──> opencode skill `qa-stress`
Lenovo Server <── docker compose pull (GHCR private image, no source exposed)
```

## Closed Build (like opencode v2)

Source is **never** shipped to Lenovo. You push to private GitHub, CI builds a distroless Docker image to `ghcr.io/<org>/qa-agent:closed` and Lenovo only does `docker compose pull`.

* Dev image: contains `.py` source (for debugging)
* Closed image: `Dockerfile.closed` — compiles to `.pyc` only + strips source + non-root distroless + no shell. Code not readable without decompilation.

## Quick Start (Standalone)

```bash
cd /Users/apple/qa-agent
cp .env.example .env
docker compose up --build          # dev at http://localhost:8000
# or prod locally:
cp .env.example .env.prod
docker compose -f docker-compose.prod.yml up -d  # Caddy + api, auto-TLS if DOMAIN ready
```

Trigger a run:
```bash
# prod
curl -X POST https://qa.awesometech.com.ng/api/v1/test/run \
  -H "Content-Type: application/json" \
  -d '{"target_url":"https://example.com","scenario":"smoke","vus":50,"duration":"30s"}'

# local dev
curl -X POST http://localhost:8000/api/v1/test/run -H "Content-Type: application/json" -d '{"target_url":"https://example.com","vus":50,"duration":"30s"}'

# stream via SSE
curl -N https://qa.awesometech.com.ng/api/v1/test/<id>/stream
```

Opencode (after `opencode.json` points to `https://qa.awesometech.com.ng`):
```
/qa-stress target=https://example.com vus=100 duration=60s
```

## Repo Layout

See `app/` for FastAPI, `playwright/` for highlight injection, `k6/` for load scripts, `.github/workflows/build-and-push.yml` for GHCR private build.

## Deploy to Lenovo `qa.awesometech.com.ng`

```bash
# 1. DNS: add A qa -> <LENOVO_PUBLIC_IP>, open 80/443
# 2. one-time private repo:
./scripts/create-private-repo.sh

# 3. first deploy (pushes closed image to GHCR, Caddy gets cert)
LENOVO_HOST=192.168.1.100 GHCR_PAT=ghp_xxx ./scripts/deploy-lenovo.sh

# Lenovo always pulls latest closed build (no source):
ssh lenovo "cd ~/qa-agent && ./scripts/pull-lenovo.sh"
# or directly: curl https://qa.awesometech.com.ng/health
```

## Security

* GitHub repo: **Private**
* GHCR package: **Private** (`ghcr.io/awesome56/qa-agent`)
* Lenovo only has image, never `git clone`
* Add `GHCR_PAT` with `read:packages` on Lenovo `.env`
