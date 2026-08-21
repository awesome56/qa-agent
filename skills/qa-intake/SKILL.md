---
name: qa-intake
description: Use ONLY when user wants to test any project (hrms-new, aperte, examco, power, phonestation, awesometech) — collects project, target URL, login credentials, admin permission toggle, feature description, and asks scope (feature/test_cases/edge_cases/load/stress/all) before calling qa-agent at qa.awesometech.com.ng.
---

# QA Intake — Universal (qa-agent)

You are the universal intake for the standalone `qa-agent` at `/Users/apple/qa-agent` serving `https://qa.awesometech.com.ng` (Lenovo `qa-agent.service:8228` via `cloudflared`). Works for any project on Lenovo — not just `hrms-new`.

## When to trigger
User says: `test feature`, `check bug fix`, `qa this`, `run QA`, mentions `hrms-new`, `aperte`, `examco`, `power`, `phonestation`, or `I built a feature`.

## Step 1 — Collect (ask via `question` tool if missing, mask passwords)
Ask in order, one question at a time if user didn't provide:

1. **Project** — `hrms-new` | `aperte` | `examco` | `power` | `phonestation` | `awesometech` | `other` (maps to default URL)
   - `hrms-new` -> `https://hrms.awesometech.com.ng`
   - `aperte` -> `https://aparte.awesometech.com.ng`
   - `examco` -> `https://examco.awesometech.com.ng`
   - `power` -> `https://power.awesometech.com.ng`
   - `phonestation` -> `https://phonestation.awesometech.com.ng`
   - else ask `target_url`
2. **Target URL** — exact feature URL to test (e.g. `https://hrms.awesometech.com.ng/leave/create`). If not given, infer from project + feature.
3. **Login** — `login_url` (default `{target}/login`), `username`, `password` (SecretStr, never log). If not provided and page needs auth, `qa-agent` will return `need_auth` SSE and you must ask again.
4. **Permission toggle** — If tester may lack permission: ask `Do you have admin login to grant permission?` -> `admin_username`, `admin_password`, `permission_feature` (e.g. `leave_approval`).
5. **Feature description** — free text bug/feature to verify (e.g. `cannot approve expired leave`).

## Step 2 — Ask scope (required)
Always ask via `question`:
```
What should I test?
- feature      — just verify the feature/bugfix works
- test_cases   — functional test cases
- edge_cases   — edge/negative cases (uses muse-spark-1.2)
- load         — steady load (k6 vus 50, 5m)
- stress       — spike to breaking point (k6 stages 200)
- all          — feature + edge + load + stress
```
Default `feature` if user says "just check it works". Store as `scope`.

## Step 3 — Call qa-agent
Build JSON and `POST https://qa.awesometech.com.ng/api/v1/test/run` (or fallback `http://100.119.144.46:8228` via tailscale):
```json
{
  "project":"hrms-new",
  "target_url":"https://hrms.awesometech.com.ng/leave",
  "scenario":"cannot approve expired leave",
  "scope":"edge_cases",
  "vus":50,"duration":"30s",
  "auth":{"login_url":"https://hrms.awesometech.com.ng/login","username":"...","password":"...","admin_username":"...","admin_password":"...","permission_feature":"leave_approval"},
  "record_video":true,"highlight_buttons":true
}
```
Use `auth.password` as `SecretStr`. Never echo password in logs.

## Step 4 — Stream & handle asks
Stream `GET https://qa.awesometech.com.ng/api/v1/test/{id}/stream` (SSE). If event `need_auth` or `need_admin`, ask user for missing credentials and re-POST with same `target_url` + new `auth`.

If `scope` includes `edge_cases/test_cases/all`, the agent's `muse-spark-1.2` (`app/rag/agent_loop.py:generate_edge_cases`) will return cases — show them.

## Step 5 — Report
After `done`, show `video_path`, `trace_path`, `k6_summary`, and `https://qa.awesometech.com.ng/api/v1/reports/daily/today`. Offer to open `https://qa.awesometech.com.ng/intake` web form for next run.

## Rules
- Always mask passwords (`***`) in logs/SSE.
- Always ask `scope` before running.
- Always collect `project` first to set defaults.
- If `auth` missing and page needs login, ask back — don't guess.
- If `403` and no `admin`, ask for admin to grant `permission_feature`.
