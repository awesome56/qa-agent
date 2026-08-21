import asyncio
from app.models import TestResult, TestStatus
from app.workers import queue
from app.services.recorder import run_playwright_recording
from app.workers.stress_worker import run_k6
from app.rag.vector_store import vector_store
from app.rag.graph import graph_store
from app.config import REPORTS
from datetime import date

async def execute_test(result: TestResult):
    test_id = result.id
    await queue.update_status(test_id, TestStatus.running)
    await queue.push_log(test_id, f"starting test {test_id} {result.request.target_url} scenario={result.request.scenario}")

    playwright_summary = None
    k6_summary = None
    try:
        # 1. Playwright recording + highlight
        if result.request.record_video:
            await queue.push_log(test_id, "phase: playwright recording + button highlight")
            await queue.push_event(test_id, {"type": "phase", "phase": "playwright"})
            pw = await run_playwright_recording(
                target_url=result.request.target_url,
                test_id=test_id,
                storage_dir=None,
                highlight=result.request.highlight_buttons,
            )
            playwright_summary = pw
            # forward pw logs to SSE
            for l in pw.get("logs", [])[-20:]:
                await queue.push_log(test_id, l)
            result.video_path = pw.get("video_path")
            result.trace_path = pw.get("trace_path")
            result.playwright_summary = pw

            # RAG ingest
            await vector_store.embed_and_upsert(test_id, "\n".join(pw.get("logs", [])), {"kind": "playwright", "target": result.request.target_url})

        # 2. Stress/load via k6
        await queue.push_log(test_id, f"phase: k6 stress vus={result.request.vus} duration={result.request.duration}")
        await queue.push_event(test_id, {"type": "phase", "phase": "k6"})
        k6 = await run_k6(result.request.target_url, result.request.vus, result.request.duration, test_id)
        k6_summary = k6
        result.k6_summary = k6
        await queue.push_log(test_id, f"k6 done p95={k6['metrics']['http_req_duration']['p95']} checks {k6['checks_passed']}/{k6['checks_total']} simulated={k6.get('simulated')}")

        await vector_store.embed_and_upsert(test_id, f"k6: {k6}", {"kind": "k6", "target": result.request.target_url})

        # 3. Determine status
        failed = k6.get("checks_failed", 0) > 0 or (playwright_summary and playwright_summary.get("error"))
        status = TestStatus.failed if failed else TestStatus.passed
        graph_store.add_run(test_id, result.request.target_url, result.request.scenario, status, meta={"failed_checks": k6.get("checks_failed")})

        await queue.update_status(test_id, status, k6_summary=k6, playwright_summary=playwright_summary)
        await queue.push_log(test_id, f"finished status={status}")

    except Exception as e:
        await queue.push_log(test_id, f"error: {e}")
        await queue.update_status(test_id, TestStatus.error, error=str(e))
    finally:
        await queue.complete_queue(test_id)
        # webhook callback if configured
        if result.request.webhook_callback_url:
            try:
                import httpx
                async with httpx.AsyncClient() as c:
                    await c.post(result.request.webhook_callback_url, json=result.model_dump(mode="json"), timeout=5)
            except Exception as e:
                await queue.push_log(test_id, f"webhook callback failed: {e}")
