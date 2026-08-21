import asyncio
from app.models import TestResult, TestStatus
from app.workers import queue
from app.services.recorder import run_playwright_recording
from app.workers.stress_worker import run_k6
from app.rag.vector_store import vector_store
from app.rag.graph import graph_store
from app.rag.agent_loop import generate_edge_cases
from datetime import date

async def execute_test(result: TestResult):
    test_id = result.id
    scope = result.request.scope.value if hasattr(result.request.scope, 'value') else str(result.request.scope)
    await queue.update_status(test_id, TestStatus.running)
    await queue.push_log(test_id, f"starting test {test_id} project={result.request.project} target={result.request.target_url} scenario={result.request.scenario} scope={scope}")
    await queue.push_event(test_id, {"type": "scope", "scope": scope})

    playwright_summary = None
    k6_summary = None
    edge_cases = None
    try:
        # 1. Playwright recording + highlight (+ auth)
        if result.request.record_video:
            await queue.push_log(test_id, "phase: playwright recording + button highlight")
            await queue.push_event(test_id, {"type": "phase", "phase": "playwright"})
            # prepare auth dict (handle SecretStr)
            auth_dict = None
            if result.request.auth:
                ad = result.request.auth.model_dump() if hasattr(result.request.auth, 'model_dump') else dict(result.request.auth)
                # unwrap SecretStr
                for k in ["password","admin_password"]:
                    v = ad.get(k)
                    if v is not None:
                        try:
                            ad[k] = v.get_secret_value() if hasattr(v, "get_secret_value") else str(v)
                        except: ad[k] = str(v)
                auth_dict = {k:v for k,v in ad.items() if v is not None}

            pw = await run_playwright_recording(
                target_url=result.request.target_url,
                test_id=test_id,
                storage_dir=None,
                highlight=result.request.highlight_buttons,
                auth=auth_dict,
            )
            playwright_summary = pw
            for l in pw.get("logs", [])[-30:]:
                await queue.push_log(test_id, l)
            result.video_path = pw.get("video_path")
            result.trace_path = pw.get("trace_path")
            result.playwright_summary = pw

            # handle need_auth / need_admin -> ask back via SSE
            if pw.get("need_auth"):
                await queue.push_event(test_id, {"type": "need_auth", "msg": pw.get("error","login required"), "hint": "Please provide username/password via intake. Use auth.login_url, auth.username, auth.password"})
                await queue.push_log(test_id, "NEED_AUTH: waiting for credentials — SSE client should prompt user")
                await queue.update_status(test_id, TestStatus.error, error="need_auth: " + pw.get("error","login required"), playwright_summary=pw)
                await vector_store.embed_and_upsert(test_id, "\n".join(pw.get("logs", [])), {"kind": "playwright_need_auth", "target": result.request.target_url})
                await queue.complete_queue(test_id)
                return
            if pw.get("need_admin"):
                await queue.push_event(test_id, {"type": "need_admin", "msg": pw.get("error","permission denied"), "hint": "Provide admin_username/admin_password + permission_feature to grant"})
                await queue.push_log(test_id, "NEED_ADMIN: tester lacks permission")
                await queue.update_status(test_id, TestStatus.error, error="need_admin: " + pw.get("error",""), playwright_summary=pw)
                await queue.complete_queue(test_id)
                return

            await vector_store.embed_and_upsert(test_id, "\n".join(pw.get("logs", [])), {"kind": "playwright", "target": result.request.target_url, "project": str(result.request.project)})

        # 1b. Edge cases generation if scope includes edge_cases / all / test_cases
        if scope in ("edge_cases","test_cases","all"):
            await queue.push_log(test_id, f"phase: generating edge cases via muse-spark-1.2 for scope={scope}")
            await queue.push_event(test_id, {"type": "phase", "phase": "edge_cases"})
            try:
                edge_cases = await generate_edge_cases(
                    feature=result.request.scenario,
                    target_url=result.request.target_url,
                    project=str(result.request.project),
                    scope=scope,
                )
                playwright_summary = playwright_summary or {}
                playwright_summary["edge_cases"] = edge_cases
                await queue.push_log(test_id, f"edge cases: {len(edge_cases.get('cases',[]))} cases generated")
                await queue.push_event(test_id, {"type": "edge_cases", "cases": edge_cases.get("cases",[])[:10]})
                await vector_store.embed_and_upsert(test_id, str(edge_cases), {"kind": "edge_cases", "project": str(result.request.project)})
            except Exception as e:
                await queue.push_log(test_id, f"edge case generation failed: {e}")

        # 2. Stress/load via k6 if scope includes load/stress/all OR vus>10 explicitly
        should_k6 = scope in ("load","stress","all") or result.request.vus > 10 or "load" in result.request.scenario.lower() or "stress" in result.request.scenario.lower()
        if should_k6:
            await queue.push_log(test_id, f"phase: k6 {scope} vus={result.request.vus} duration={result.request.duration}")
            await queue.push_event(test_id, {"type": "phase", "phase": "k6"})
            k6 = await run_k6(result.request.target_url, result.request.vus, result.request.duration, test_id)
            k6_summary = k6
            result.k6_summary = k6
            await queue.push_log(test_id, f"k6 done p95={k6['metrics']['http_req_duration']['p95']} checks {k6['checks_passed']}/{k6['checks_total']} simulated={k6.get('simulated')}")
            await vector_store.embed_and_upsert(test_id, f"k6: {k6}", {"kind": "k6", "target": result.request.target_url})
        else:
            await queue.push_log(test_id, f"skip k6 for scope={scope} (feature-only) — enable with scope=load/stress/all or vus>10")
            k6_summary = {"skipped": True, "scope": scope}

        # 3. Determine status
        failed = False
        if k6_summary and not k6_summary.get("skipped") and k6_summary.get("checks_failed",0) > 0:
            failed = True
        if playwright_summary and playwright_summary.get("error") and not playwright_summary.get("need_auth") and not playwright_summary.get("need_admin"):
            failed = True
        status = TestStatus.failed if failed else TestStatus.passed
        graph_store.add_run(test_id, result.request.target_url, result.request.scenario, status, meta={"failed_checks": k6_summary.get("checks_failed") if k6_summary else 0, "scope": scope, "project": str(result.request.project)})

        # attach summaries
        result.k6_summary = k6_summary
        result.playwright_summary = playwright_summary
        await queue.update_status(test_id, status, k6_summary=k6_summary, playwright_summary=playwright_summary)
        await queue.push_log(test_id, f"finished status={status} scope={scope}")

    except Exception as e:
        await queue.push_log(test_id, f"error: {e}")
        await queue.update_status(test_id, TestStatus.error, error=str(e))
    finally:
        # ensure queue completed unless we already returned early
        try:
            q = queue.get_queue(test_id)
            if q and not q.empty() or True:
                await queue.complete_queue(test_id)
        except: pass
        if result.request.webhook_callback_url:
            try:
                import httpx
                async with httpx.AsyncClient() as c:
                    await c.post(result.request.webhook_callback_url, json=result.model_dump(mode="json"), timeout=5)
            except Exception as e:
                await queue.push_log(test_id, f"webhook callback failed: {e}")
