from fastapi import APIRouter, Request, BackgroundTasks, Header, HTTPException
import hmac
import hashlib
import json
from app.models import TestRequest, TestResult
from app.workers import queue
from app.workers.playwright_worker import execute_test
from app.config import settings

router = APIRouter(prefix="/webhook", tags=["webhook"])

def verify_github_signature(body: bytes, signature: str) -> bool:
    if not settings.github_webhook_secret or settings.github_webhook_secret == "change-me-too":
        return True  # skip if not configured
    if not signature:
        return False
    expected = "sha256=" + hmac.new(settings.github_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

@router.post("/github")
async def github_webhook(request: Request, bg: BackgroundTasks, x_hub_signature_256: str = Header(None)):
    raw = await request.body()
    if not verify_github_signature(raw, x_hub_signature_256):
        raise HTTPException(401, "invalid signature")
    try:
        payload = json.loads(raw)
    except:
        payload = {}

    # only act on push to main/master
    ref = payload.get("ref", "")
    if ref and ref not in ("refs/heads/main", "refs/heads/master", "refs/heads/dev"):
        return {"ignored": True, "ref": ref}

    # infer target_url from payload or fallback
    target_url = payload.get("repository", {}).get("homepage") or settings.target_url_default
    # allow override via commit message tag e.g. [qa:url=https://staging.example.com]
    head_msg = ""
    try:
        head_msg = payload.get("head_commit", {}).get("message", "") or ""
    except: pass
    import re
    m = re.search(r"\[qa:url=([^\]]+)\]", head_msg)
    if m:
        target_url = m.group(1).strip()

    req = TestRequest(target_url=target_url, scenario="smoke", vus=20, duration="30s", metadata={"trigger": "github_push", "ref": ref, "repo": payload.get("repository", {}).get("full_name")})
    result = TestResult(request=req)
    await queue.register(result)
    bg.add_task(execute_test, result)
    return {"queued": True, "id": result.id, "target_url": target_url, "stream": f"/api/v1/test/{result.id}/stream"}
