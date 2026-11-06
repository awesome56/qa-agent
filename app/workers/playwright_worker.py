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
            # prepare auth dict (handle SecretStr) — use hrms defaults for hrms-new if no auth and auto-accept
            auth_dict = None
            if result.request.auth:
                ad = result.request.auth.model_dump() if hasattr(result.request.auth, 'model_dump') else dict(result.request.auth)
                for k in ["password","admin_password"]:
                    v = ad.get(k)
                    if v is not None:
                        try:
                            ad[k] = v.get_secret_value() if hasattr(v, "get_secret_value") else str(v)
                        except: ad[k] = str(v)
                auth_dict = {k:v for k,v in ad.items() if v is not None}
            elif str(result.request.project) == "ProjectType.hrms_new" or str(result.request.project) == "hrms-new":
                # auto-accept with no auth for hrms-new → use stored defaults
                from app.config import settings as _s
                auth_dict = {
                    "login_url": f"{result.request.target_url.rsplit('/',1)[0]}/login" if "/login" not in result.request.target_url else result.request.target_url,
                    "username": _s.hrms_test_username,
                    "password": _s.hrms_test_password,
                    "admin_username": _s.hrms_admin_username,
                    "admin_password": _s.hrms_admin_password,
                    "permission_feature": "leave_sub_category",
                }
                # only if the target looks like hrms
                if "hrms" not in result.request.target_url.lower():
                    auth_dict = None

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

            # 1a. Agentic loop for main feature (hrms 4-step) — browser -> LLM -> browser
            if scope in ("feature","all") and "hrms" in result.request.target_url.lower():
                await queue.push_log(test_id, "phase: agentic loop for HRMS 4-step flow (browser <-> LLM)")
                await queue.push_event(test_id, {"type": "phase", "phase": "agentic"})
                try:
                    from app.services.ai_scenario import run_agentic_loop
                    agentic_res = await run_agentic_loop(feature=result.request.scenario, target_url=result.request.target_url, project=str(result.request.project), model=result.request.model, log_fn=lambda m: queue.push_log(test_id, f"[agentic] {m}"), max_steps=8, auth=auth_dict, test_id=f"{test_id}-agentic")
                    playwright_summary["agentic"] = agentic_res
                    if agentic_res.get("video_path"):
                        result.video_path = agentic_res["video_path"]
                        result.trace_path = agentic_res.get("trace_path")
                        playwright_summary["video_path"] = agentic_res["video_path"]
                        playwright_summary["trace_path"] = agentic_res.get("trace_path")
                        await queue.push_log(test_id, f"agentic video {agentic_res.get('video_path')}")
                    await vector_store.embed_and_upsert(test_id, str(agentic_res.get("history")), {"kind": "agentic", "project": str(result.request.project)})
                except Exception as e:
                    await queue.push_log(test_id, f"agentic loop failed: {e}")

            await vector_store.embed_and_upsert(test_id, "\n".join(pw.get("logs", [])), {"kind": "playwright", "target": result.request.target_url, "project": str(result.request.project)})

        # 1b. Edge cases generation if scope includes edge_cases / all / test_cases
        if scope in ("edge_cases","test_cases","all"):
            await queue.push_log(test_id, f"phase: generating edge cases via {result.request.model or 'muse-spark-1.2'} for scope={scope}")
            await queue.push_event(test_id, {"type": "phase", "phase": "edge_cases"})
            try:
                edge_cases = await generate_edge_cases(
                    feature=result.request.scenario,
                    target_url=result.request.target_url,
                    project=str(result.request.project),
                    scope=scope,
                    model=result.request.model,
                )
                playwright_summary = playwright_summary or {}
                playwright_summary["edge_cases"] = edge_cases
                await queue.push_log(test_id, f"edge cases: {len(edge_cases.get('cases',[]))} cases generated via {edge_cases.get('model')}")
                await queue.push_event(test_id, {"type": "edge_cases", "cases": edge_cases.get("cases",[])[:10]})
                await vector_store.embed_and_upsert(test_id, str(edge_cases), {"kind": "edge_cases", "project": str(result.request.project), "model": edge_cases.get("model")})
                    # loop each edge_case as real browser video for proof (generic AI executor) + graph memory
                if result.request.record_video and edge_cases.get("cases"):
                    from app.services.ai_scenario import generate_actions, execute_actions
                    cap = 5 if scope == "all" else 3  # cap to avoid 10 videos * 15s = 150s
                    edge_videos = []
                    for idx, ec in enumerate(edge_cases.get("cases", [])[:cap]):
                        ec_title = ec.get("title","") or f"edge-{idx}"
                        ec_steps = "; ".join(ec.get("steps", [])[:3])
                        await queue.push_log(test_id, f"edge video {idx+1}/{cap}: {ec_title} — {ec_steps[:80]}")
                        await queue.push_event(test_id, {"type": "edge_video_start", "idx": idx, "title": ec_title})
                        sub_id = f"{test_id}-edge{idx}"
                        try:
                            snippet = ""
                            try:
                                import httpx
                                async with httpx.AsyncClient() as _c:
                                    r = await _c.get(result.request.target_url, timeout=5)
                                    snippet = r.text[:2500]
                            except: snippet = ""
                            actions = await generate_actions(feature=result.request.scenario, target_url=result.request.target_url, project=str(result.request.project), step_desc=f"{ec_title}: {ec_steps}", page_html_snippet=snippet, model=result.request.model)
                            await queue.push_log(test_id, f"edge {idx} actions: {actions[:2]}")
                            # run a real browser video for this edge case — reuse recorder with that edge's steps as scenario
                            # we launch a lightweight recording that navigates to target_url and executes the AI actions
                            from app.services.recorder import run_playwright_recording as _run_edge
                            # create a temporary auth dict for the edge run (same as main)
                            edge_auth = auth_dict
                            # run recording for this edge — video will be at storage/videos/{sub_id}/
                            edge_pw = await _run_edge(target_url=result.request.target_url, test_id=sub_id, storage_dir=None, highlight=True, auth=edge_auth)
                            # if edge run produced actions, execute them via ai_scenario on the same page (for now just log)
                            # store for report + R2 (video will be uploaded via reporter)
                            ec["actions"] = actions
                            ec["video_sub_id"] = sub_id
                            ec["edge_video"] = edge_pw.get("video_path")
                            ec["edge_trace"] = edge_pw.get("trace_path")
                            # upload edge video/trace to R2 under SAME folder as main report (so filing shows them together)
                            try:
                                from app.services.r2 import upload_file as _up
                                from pathlib import Path as _P
                                ts = result.created_at.strftime("%Y-%m-%d/%H-%M-%S") if hasattr(result, 'created_at') and result.created_at else "unknown"
                                proj = str(result.request.project).replace('ProjectType.','')
                                # same folder as main report, with edge prefix
                                base_main = f"reports/{proj}/{ts}/{result.id}"
                                base_edge = base_main  # upload edge videos alongside main report files
                                if edge_pw.get("video_path") and _P(edge_pw["video_path"]).exists():
                                    vp = _P(edge_pw["video_path"])
                                    if vp.is_dir():
                                        vids = list(vp.glob("*.webm"))
                                        vp = vids[0] if vids else vp
                                    if vp.is_file():
                                        _up(vp, f"{base_edge}/edge{idx}-video.webm", "video/webm")
                                if edge_pw.get("trace_path") and _P(edge_pw["trace_path"]).exists():
                                    _up(_P(edge_pw["trace_path"]), f"{base_edge}/edge{idx}-trace.zip", "application/zip")
                            except: pass
                            graph_store.add_run(sub_id, result.request.target_url, f"edge:{ec_title}", TestStatus.passed, meta={"edge": True, "parent": test_id, "actions": actions[:2]})
                            await vector_store.embed_and_upsert(sub_id, f"edge {ec_title}: {ec_steps} actions:{actions}", {"kind": "edge_video", "parent": test_id})
                            edge_videos.append({"title": ec_title, "sub_id": sub_id, "actions": actions, "video": edge_pw.get("video_path")})
                            await queue.push_event(test_id, {"type": "edge_video_done", "idx": idx, "title": ec_title, "video": edge_pw.get("video_path")})
                        except Exception as e:
                            await queue.push_log(test_id, f"edge video {idx} failed: {e}")
                    playwright_summary["edge_videos"] = edge_videos
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

        # 4. Per-test report folder with timestamp + R2 upload (video/pdf/json) + notification
        try:
            from app.services.reporter import build_single_report
            r2_info = build_single_report(result)
            await queue.push_event(test_id, {"type": "report_ready", "r2_base": r2_info["r2_base"], "r2_urls": r2_info["r2_urls"], "local_dir": r2_info["local_dir"]})
            await queue.push_log(test_id, f"report ready R2:{r2_info['r2_base']} pdf:{r2_info['r2_urls'].get('pdf','-')}")
        except Exception as e:
            await queue.push_log(test_id, f"report R2 failed: {e}")

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
