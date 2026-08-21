from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
import asyncio
import json
from app.models import TestRequest, TestResult, TestStatus
from app.workers import queue
from app.workers.playwright_worker import execute_test

router = APIRouter(prefix="/api/v1/test", tags=["tests"])

@router.post("/run")
async def run_test(req: TestRequest, bg: BackgroundTasks):
    result = TestResult(request=req)
    await queue.register(result)
    bg.add_task(execute_test, result)
    return {"id": result.id, "status": result.status, "stream": f"/api/v1/test/{result.id}/stream", "poll": f"/api/v1/test/{result.id}"}

@router.get("/{test_id}")
async def get_test(test_id: str):
    r = await queue.get(test_id)
    if not r:
        raise HTTPException(404, "test not found")
    return r

@router.get("/{test_id}/stream")
async def stream_test(test_id: str):
    r = await queue.get(test_id)
    if not r:
        raise HTTPException(404, "test not found")

    async def event_gen():
        # send initial snapshot
        yield {"event": "snapshot", "data": json.dumps(r.model_dump(mode="json"))}
        q = queue.get_queue(test_id)
        if not q:
            yield {"event": "done", "data": json.dumps({"status": r.status})}
            return
        while True:
            try:
                evt = await asyncio.wait_for(q.get(), timeout=30)
                if evt.get("type") == "done":
                    # final poll
                    final = await queue.get(test_id)
                    yield {"event": "done", "data": json.dumps(final.model_dump(mode="json") if final else {})}
                    break
                yield {"event": evt.get("type", "message"), "data": json.dumps(evt)}
            except asyncio.TimeoutError:
                # heartbeat
                yield {"event": "ping", "data": json.dumps({"ts": __import__("datetime").datetime.utcnow().isoformat()})}
                # if finished and queue drained, break
                cur = await queue.get(test_id)
                if cur and cur.status in (TestStatus.passed, TestStatus.failed, TestStatus.error):
                    # check if no more events after a bit
                    await asyncio.sleep(1)
                    if q.empty():
                        yield {"event": "done", "data": json.dumps(cur.model_dump(mode="json"))}
                        break

    return EventSourceResponse(event_gen())

@router.get("/")
async def list_tests():
    all_runs = await queue.list_all()
    return {"count": len(all_runs), "items": list(all_runs.values())}
