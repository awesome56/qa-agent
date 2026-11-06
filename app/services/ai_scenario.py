"""
Generic AI executor — turns any feature/edge_case description into real Playwright actions.

Used by playwright_worker to give video proof for every edge_case/test_case, not just login highlight.
Works for any project (hrms-new, aperte, examco, ...) without pre-programmed scenarios.

Flow:
  feature="create leave sub-category with Company=Virdi" + page DOM -> muse-spark -> actions JSON -> Playwright executes while record_video captures.

Actions format:
  [{"action":"fill","selector":"#SubCategoryName","value":"QA-123"}, {"action":"select2","selector":"select[name=company]","values":["Virdi"]}, {"action":"click","selector":"button:has-text('Create')"}]
"""
import json
from typing import List, Dict, Any

FALLBACK_ACTIONS = [
    {"action": "fill", "selector": "input[type='text']", "value": "QA Test"},
    {"action": "click", "selector": "button[type='submit']"},
]

async def generate_actions(feature: str, target_url: str, project: str, step_desc: str, page_html_snippet: str = "", model: str | None = None) -> List[Dict[str, Any]]:
    """Ask LLM to turn a step description into Playwright actions."""
    from app.rag.agent_loop import _call_llm
    prompt = f"""You are a Playwright code generator for QA.
Project: {project}
Target URL: {target_url}
Feature: {feature}
Step to execute: {step_desc}
Page snippet (first 2000 chars): {page_html_snippet[:2000]}

Generate a JSON array of Playwright actions to execute this step.
Each action is one of:
  {{"action":"goto","url":"..."}}
  {{"action":"fill","selector":"css","value":"text"}}
  {{"action":"select","selector":"select css","value":"option text"}}
  {{"action":"select2","selector":"select css","values":["a","b"]}}  // for Select2 multi-select
  {{"action":"click","selector":"css"}}
  {{"action":"wait","selector":"css","timeout":3000}}
Use robust selectors: #id, [name=...], button:has-text('...'), select2 should use select[name=...] etc.
Return ONLY JSON array, e.g. [{{"action":"fill","selector":"#name","value":"x"}}]
"""
    txt = await _call_llm(prompt, model=model)
    if txt:
        try:
            start = txt.find("[")
            end = txt.rfind("]") + 1
            if start != -1 and end != 0:
                data = json.loads(txt[start:end])
                if isinstance(data, list) and data:
                    # sanitize
                    out = []
                    for a in data[:12]:
                        if isinstance(a, dict) and "action" in a and "selector" in a:
                            out.append(a)
                    if out:
                        return out
        except Exception:
            pass
    # fallback — try to infer from step_desc
    low = step_desc.lower()
    if "empty" in low:
        return [{"action": "click", "selector": "button[type='submit']"}]
    if "xss" in low:
        return [{"action": "fill", "selector": "input[type='text']", "value": "<script>alert(1)</script>"}, {"action": "click", "selector": "button[type='submit']"}]
    if "1000" in low:
        return [{"action": "fill", "selector": "input[type='text'], textarea", "value": "a"*100}, {"action": "click", "selector": "button[type='submit']"}]
    return FALLBACK_ACTIONS

async def execute_actions(page, actions: List[Dict[str, Any]], log_fn) -> Dict[str, Any]:
    """Execute actions on Playwright page, return {executed, errors}"""
    executed = 0
    errors = []
    for act in actions:
        try:
            kind = act.get("action")
            sel = act.get("selector", "")
            if kind == "goto":
                await page.goto(act.get("url"), wait_until="domcontentloaded", timeout=15000)
            elif kind == "fill":
                await page.fill(sel, str(act.get("value","")), timeout=5000)
            elif kind in ("select","select2"):
                vals = act.get("values") or [act.get("value")]
                vals = [str(v) for v in vals if v]
                try:
                    await page.select_option(sel, vals, timeout=4000)
                except:
                    await page.click(sel, timeout=3000)
                    for v in vals:
                        await page.keyboard.type(v)
                        await page.keyboard.press("Enter")
            elif kind == "click":
                await page.click(sel, timeout=5000)
            elif kind == "wait":
                await page.wait_for_selector(sel, timeout=act.get("timeout",3000))
            executed += 1
            await page.wait_for_timeout(400)
        except Exception as e:
            errors.append(f"{act} -> {e}")
            if log_fn:
                log_fn(f"ai_scenario action failed {act}: {e}")
    return {"executed": executed, "errors": errors, "total": len(actions)}

async def run_agentic_loop(page=None, feature: str = "", target_url: str = "", project: str = "other", model: str | None = None, log_fn=None, max_steps: int = 8, auth: Dict[str, Any] | None = None, test_id: str | None = None) -> Dict[str, Any]:
    """Browser -> LLM -> Browser loop: keep page open, snapshot DOM, ask LLM for next action, execute, repeat.
    If page is None, creates its own browser (with video if test_id provided)."""
    from app.rag.agent_loop import _call_llm
    history = []
    # if no page, create one (with video if test_id)
    created_browser = None
    if page is None:
        from playwright.async_api import async_playwright
        from pathlib import Path as _P
        from app.config import VIDEOS, TRACES
        import asyncio
        video_dir = VIDEOS / (test_id or "agentic")
        video_dir.mkdir(parents=True, exist_ok=True)
        trace_path = str(TRACES / f"{test_id or 'agentic'}.zip") if test_id else None
        p = await async_playwright().start()
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context_kwargs = {"record_video_dir": str(video_dir), "record_video_size": {"width": 1280, "height": 720}} if test_id else {}
        context = await browser.new_context(**context_kwargs)
        if trace_path:
            await context.tracing.start(screenshots=True, snapshots=True)
        page = await context.new_page()
        created_browser = (p, browser, context, trace_path, video_dir)
        if auth and auth.get("username"):
            try:
                login_url = auth.get("login_url") or target_url
                await page.goto(login_url, wait_until="domcontentloaded", timeout=15000)
                await page.fill(auth.get("username_selector") or "input[name='name'], #name, input[name='username'], input[type='email']", auth["username"], timeout=5000)
                await page.fill(auth.get("password_selector") or "input[name='password'], #password, input[type='password']", auth["password"], timeout=5000)
                await page.click(auth.get("submit_selector") or "button[type='submit']", timeout=5000)
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception as e:
                if log_fn: log_fn(f"agentic auth failed: {e}")
        # goto target
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
        except Exception as e:
            if log_fn: log_fn(f"agentic goto failed: {e}")
    for step in range(max_steps):
        # snapshot DOM + URL
        try:
            url = page.url
            title = await page.title()
            html = (await page.content())[:4000]
            # also get visible buttons/inputs for hint
            buttons = await page.evaluate("""() => Array.from(document.querySelectorAll('button, a[role=button], input[type=submit]')).slice(0,10).map(b=>b.innerText||b.value||b.tagName).join(', ')""")
        except Exception as e:
            if log_fn: log_fn(f"agentic snapshot failed: {e}")
            break
        # ask LLM for next action
        prompt = f"""You are a QA browser agent for {project}.
Goal: {feature}
Target URL: {target_url}
Current URL: {url} Title: {title}
Visible buttons: {buttons}
Page HTML snippet: {html[:2500]}
History: {history[-3:]}

Decide next Playwright action to progress toward the goal.
Return JSON: {{"action":"fill|click|select|goto|wait|done","selector":"css","value":"...","reason":"..."}}
If goal is achieved, return {{"action":"done","reason":"..."}}
Return ONLY JSON.
"""
        txt = await _call_llm(prompt, model=model)
        if not txt:
            if log_fn: log_fn(f"agentic step {step}: no LLM response, fallback")
            break
        try:
            # extract JSON
            s = txt.find("{")
            e = txt.rfind("}")+1
            data = json.loads(txt[s:e])
            act = data.get("action")
            if act == "done":
                history.append(f"step{step}: done - {data.get('reason','')}")
                if log_fn: log_fn(f"agentic done: {data.get('reason')}")
                break
            # single action -> wrap as list
            action = {"action": act, "selector": data.get("selector",""), "value": data.get("value"), "values": data.get("values")}
            # clean None
            action = {k:v for k,v in action.items() if v is not None}
            if log_fn: log_fn(f"agentic step {step}: {action} reason:{data.get('reason','')}")
            # execute
            res = await execute_actions(page, [action], log_fn)
            history.append(f"step{step}: {action} -> {res}")
            await page.wait_for_timeout(800)
            # check if page changed to success
            if "success" in (await page.content())[:2000].lower() or "created" in (await page.title()).lower():
                continue
        except Exception as e:
            if log_fn: log_fn(f"agentic step {step} parse/exec failed: {e} txt:{txt[:200]}")
            try:
                await page.evaluate("""() => window.scrollTo(0, document.body.scrollHeight)""")
            except: pass
            break
    # cleanup if we created browser
    if created_browser:
        p, browser, context, trace_path, video_dir = created_browser
        try:
            if trace_path:
                await context.tracing.stop(path=trace_path)
            await context.close()
            await browser.close()
            await p.stop()
            import pathlib
            vids = list(video_dir.glob("*.webm"))
            video_path = str(vids[0]) if vids else str(video_dir)
            history.append(f"video:{video_path} trace:{trace_path}")
            return {"history": history, "steps": max_steps, "video_path": video_path, "trace_path": trace_path}
        except Exception as e:
            if log_fn: log_fn(f"agentic cleanup failed: {e}")
    return {"history": history, "steps": max_steps}
