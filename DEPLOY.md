# Deploy — Private GitHub + Lenovo `qa.awesometech.com.ng`

Standalone agent, not under `Awesome_App`. Source stays private, Lenovo only pulls closed Docker image (no `.py`).

## 1. Standalone Location

```
/Users/apple/qa-agent  <-- this repo (private)
  NOT /Users/apple/Awesome_App/qa-agent (deleted, left README pointer)
```

`Awesome_App/.opencode/skills/qa-stress` is thin wrapper that calls `https://qa.awesometech.com.ng`.

## 2. DNS (one-time)

In your domain registrar (awesometech.com.ng):

```
Type  Name  Value                TTL
A     qa    <LENOVO_PUBLIC_IP>   300
```

Check: `dig qa.awesometech.com.ng +short` should return Lenovo IP. Open ports 80,443 on Lenovo firewall/router.

## 3. Private GitHub Repo (one-time)

```bash
cd /Users/apple/qa-agent
./scripts/create-private-repo.sh qa-agent   # needs `gh auth login` or manual at github.com/new

# manual:
#  github.com/new -> qa-agent -> Private
#  git init -b main && git add . && git commit -m "feat: qa-agent"
#  git remote add origin https://github.com/awesome56/qa-agent.git
#  git push -u origin main
# GHCR package ghcr.io/awesome56/qa-agent:closed will be Private automatically
```

CI: `.github/workflows/build-and-push.yml` builds `Dockerfile.closed` (no `.py`) and pushes to GHCR private.

## 4. Lenovo — First Deploy (serves qa.awesometech.com.ng)

```bash
cd /Users/apple/qa-agent
cp .env.example .env.prod
# edit .env.prod: SECRET_TOKEN, GITHUB_WEBHOOK_SECRET, OPENAI_API_KEY etc
# ensure DOMAIN=qa.awesometech.com.ng  PUBLIC_URL=https://qa.awesometech.com.ng

export LENOVO_HOST=192.168.1.100  # or lenovo.tailnet.ts.net / public IP
export LENOVO_USER=apple
export GHCR_USER=awesome56
export GHCR_PAT=ghp_xxx  # read:packages at github.com/settings/tokens

./scripts/deploy-lenovo.sh
# does: scp compose+Caddyfile+env -> ~/qa-agent, docker login, compose pull, up
# Caddy auto-requests Let's Encrypt cert for qa.awesometech.com.ng
```

Verify:
```bash
ssh apple@lenovo "curl -sk http://localhost:8000/health"
curl https://qa.awesometech.com.ng/health
curl https://qa.awesometech.com.ng/api/v1/test/run -X POST -H "Content-Type: application/json" -d '{"target_url":"https://example.com","vus":5,"duration":"2s"}'
```

## 5. Lenovo — Daily Pull (no source)

On Lenovo:
```bash
cd ~/qa-agent && ./scripts/pull-lenovo.sh
# or: docker compose pull && docker compose up -d
```

Cron auto-pull 04:00:
```bash
(crontab -l 2>/dev/null; echo "0 4 * * * cd ~/qa-agent && docker compose pull && docker compose up -d >> ~/qa-agent/pull.log 2>&1") | crontab -
```

## 6. GitHub Webhook (auto-test on push)

Repo -> Settings -> Webhooks -> Add:
```
Payload URL: https://qa.awesometech.com.ng/webhook/github
Content: application/json
Secret: <GITHUB_WEBHOOK_SECRET from .env.prod>
Events: push (main)
```

Test: `git push` and watch `curl -N https://qa.awesometech.com.ng/api/v1/test/<id>/stream`

## 7. Opencode Integration

`Awesome_App/opencode.json` already points to `https://qa.awesometech.com.ng`:

```json
{
  "mcp": {
    "qa-agent": { "type": "remote", "url": "https://qa.awesometech.com.ng/mcp/call", "enabled": true },
    "qa-agent-local": { "type": "remote", "url": "http://localhost:8000/mcp/call", "enabled": false }
  }
}
```

Restart opencode after edit. Skill `qa-stress` will use public URL; fallback to local if Lenovo down.

## 8. Local Dev (with source)

```bash
cd /Users/apple/qa-agent
cp .env.example .env
docker compose up --build   # dev, exposes 8000 directly
# or without docker:
pip install -r requirements.txt && playwright install chromium
uvicorn app.main:app --reload --port 8000
```

## 9. Closed Build Verification (like opencode v2)

```bash
make build-closed
make verify-closed  # should print 0 .py files
docker run --rm -p 8000:8000 --env-file .env ghcr.io/awesome56/qa-agent:closed
```
