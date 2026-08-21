# QA Stress Agent — Private Closed Build

Autonomous testing daemon that screen-records web interactions, highlights buttons, runs stress/load tests, and drops a daily report.

Designed as **standalone service** (not a skill) so you can deploy anywhere, run its own RAG/graph/agentic loop via SSE, and let any agent call it. Thin opencode skill wrapper included for DX.

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

## Quick Start

```bash
cd qa-agent
cp .env.example .env
docker compose up --build          # dev, with source
# or closed build locally:
make build-closed
docker compose -f docker-compose.prod.yml up -d  # pulls closed image
```

Trigger a run:
```bash
curl -X POST http://localhost:8000/api/v1/test/run \
  -H "Content-Type: application/json" \
  -d '{"target_url":"https://example.com","scenario":"smoke","vus":50,"duration":"30s"}'

# stream via SSE
curl -N http://localhost:8000/api/v1/test/<id>/stream
```

Opencode:
```
/qa-stress target=https://example.com vus=100 duration=60s
```

## Repo Layout

See `app/` for FastAPI, `playwright/` for highlight injection, `k6/` for load scripts, `.github/workflows/build-and-push.yml` for GHCR private build.

## Deploy to Lenovo

```bash
# one-time: create GH private repo, add GHCR PAT
./scripts/deploy-lenovo.sh  # ssh + pull + up

# Lenovo always pulls latest closed build (no source):
./scripts/pull-lenovo.sh
```

## Security

* GitHub repo: **Private**
* GHCR package: **Private** (`ghcr.io/awesome56/qa-agent`)
* Lenovo only has image, never `git clone`
* Add `GHCR_PAT` with `read:packages` on Lenovo `.env`
