"""
Simple async in-memory queue + registry for test runs.
Swap to Redis/Celery later by setting USE_REDIS=1 — keeps Lenovo deploy simple (no extra infra required).
"""
import asyncio
from typing import Dict, Optional
from app.models import TestResult, TestStatus
from datetime import datetime

_registry: Dict[str, TestResult] = {}
_queues: Dict[str, asyncio.Queue] = {}  # per-test SSE queue
_lock = asyncio.Lock()

async def register(result: TestResult):
    async with _lock:
        _registry[result.id] = result
        _queues[result.id] = asyncio.Queue()

async def get(test_id: str) -> Optional[TestResult]:
    return _registry.get(test_id)

async def list_all() -> Dict[str, TestResult]:
    return dict(_registry)

async def push_log(test_id: str, msg: str):
    r = _registry.get(test_id)
    if r:
        r.logs.append(msg)
        q = _queues.get(test_id)
        if q:
            await q.put({"type": "log", "msg": msg, "ts": datetime.utcnow().isoformat()})

async def push_event(test_id: str, event: dict):
    q = _queues.get(test_id)
    if q:
        await q.put(event)
    # also log
    r = _registry.get(test_id)
    if r and event.get("type"):
        r.logs.append(f"[{event['type']}] {event}")

async def update_status(test_id: str, status: TestStatus, **kwargs):
    r = _registry.get(test_id)
    if not r:
        return
    r.status = status
    for k, v in kwargs.items():
        setattr(r, k, v)
    if status == TestStatus.running and not r.started_at:
        r.started_at = datetime.utcnow()
    if status in (TestStatus.passed, TestStatus.failed, TestStatus.error):
        r.finished_at = datetime.utcnow()
    await push_event(test_id, {"type": "status", "status": status, "test_id": test_id})

def get_queue(test_id: str) -> Optional[asyncio.Queue]:
    return _queues.get(test_id)

async def complete_queue(test_id: str):
    q = _queues.get(test_id)
    if q:
        await q.put({"type": "done"})
