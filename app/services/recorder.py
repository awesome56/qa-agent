"""
Playwright recorder — screen records + highlights buttons to stress.
Injects playwright/highlight.js via addInitScript.
Now supports universal auth: login_url + username/password + optional admin to grant permission.
"""
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

HIGHLIGHT_JS = Path(__file__).parent.parent.parent / "playwright" / "highlight.js"

async def run_playwright_recording(
    target_url: str,
    test_id: str,
    storage_dir: Path,
    highlight: bool = True,
    auth: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    auth: {
      login_url, username, password, admin_username, admin_password,
      permission_feature, username_selector, password_selector, submit_selector
    }
    Returns {video_path, trace_path, log, button_stats, need_auth, need_admin, error}
    Falls back to no-op if playwright browsers not installed.
    """
    from app.config import VIDEOS, TRACES
    video_dir = VIDEOS / test_id
    video_dir.mkdir(parents=True, exist_ok=True)
    trace_path = str(TRACES / f"{test_id}.zip")

    logs = []
    def log(msg: str):
        # mask passwords in logs
        if auth and auth.get("password") and isinstance(auth["password"], str):
            msg = msg.replace(auth["password"], "***")
        if auth and auth.get("admin_password"):
            msg = msg.replace(str(auth["admin_password"]), "***")
        logs.append(f"[{datetime.utcnow().isoformat()}] {msg}")
        print(msg)

    try:
        from playwright.async_api import async_playwright
    except Exception as e:
        log(f"playwright not available: {e} — skipping browser recording")
        return {"video_path": None, "trace_path": None, "logs": logs, "button_stats": {}, "skipped": True}

    highlight_script = ""
    if highlight and HIGHLIGHT_JS.exists():
        highlight_script = HIGHLIGHT_JS.read_text()

    button_stats = {}

    async def _extract_secret(v):
        # SecretStr or plain
        try:
            return v.get_secret_value() if hasattr(v, "get_secret_value") else str(v)
        except: return str(v) if v else ""

    async def _do_login(page, login_url: str, username: str, password: str, u_sel: str, p_sel: str, s_sel: str) -> bool:
        try:
            log(f"login -> {login_url} as {username}")
            await page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
            # wait for form
            await page.wait_for_selector(p_sel, timeout=8000)
            # clear + fill — try both selectors
            try:
                await page.fill(u_sel, username, timeout=5000)
            except:
                # fallback: first visible input
                await page.fill("input[type='email'], input[name='email']", username, timeout=5000)
            await page.fill(p_sel, password, timeout=5000)
            await page.click(s_sel, timeout=8000)
            await page.wait_for_load_state("networkidle", timeout=15000)
            await asyncio.sleep(1.2)
            cur = page.url
            # check if still on login (error)
            if "login" in cur.lower() or "signin" in cur.lower():
                txt = (await page.content())[:3000].lower()
                if "invalid" in txt or "incorrect" in txt or "error" in txt:
                    log(f"login failed — still on {cur}")
                    return False
            log(f"login success now at {cur} title={await page.title()}")
            return True
        except Exception as e:
            log(f"login error: {e}")
            return False

    async def _enable_permission_via_admin(page, admin_user: str, admin_pass: str, target_user: str, feature: str, login_url: str, u_sel: str, p_sel: str, s_sel: str) -> bool:
        try:
            log(f"admin permission toggle: {admin_user} enabling {feature} for {target_user}")
            ok = await _do_login(page, login_url, admin_user, admin_pass, u_sel, p_sel, s_sel)
            if not ok:
                log("admin login failed")
                return False
            # heuristic: try common admin URLs
            for admin_url in [
                login_url.replace("/login","/admin/permissions"),
                login_url.replace("/login","/admin/users"),
                login_url.replace("/login","/settings/permissions"),
                target_url.rsplit("/",1)[0] + "/admin",
            ]:
                try:
                    await page.goto(admin_url, wait_until="domcontentloaded", timeout=10000)
                    await asyncio.sleep(1)
                    txt = (await page.content())[:3000].lower()
                    if "permission" in txt or "role" in txt or target_user.lower() in txt:
                        log(f"admin page candidate {admin_url} looks relevant")
                        # try to find checkbox/toggle for feature
                        # generic: search for feature string and click nearby checkbox
                        loc = page.locator(f"text={feature}").first
                        if await loc.count() > 0:
                            await page.evaluate("""(feat) => {
                                const els = Array.from(document.querySelectorAll('*')).filter(e=> e.textContent && e.textContent.includes(feat));
                                for(const el of els){
                                    const cb = el.querySelector('input[type=checkbox]') || el.closest('tr')?.querySelector('input[type=checkbox]') || el.nextElementSibling?.querySelector('input[type=checkbox]');
                                    if(cb && !cb.checked){ cb.click(); cb.dispatchEvent(new Event('change',{bubbles:true})); return true; }
                                }
                            }""", feature)
                            await asyncio.sleep(0.8)
                            # try save
                            for sel in ["button:has-text('Save')","button:has-text('Update')","button:has-text('Confirm')"]:
                                try:
                                    if await page.locator(sel).count() > 0:
                                        await page.click(sel, timeout=3000)
                                        await page.wait_for_timeout(1200)
                                        break
                                except: pass
                            log(f"admin toggled {feature} for {target_user}")
                            return True
                except Exception as e:
                    log(f"admin page {admin_url} error: {e}")
                    continue
            log("admin permission toggle did not find feature checkbox — you may need to enable manually")
            return False
        except Exception as e:
            log(f"admin toggle error: {e}")
            return False

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
            context = await browser.new_context(
                record_video_dir=str(video_dir),
                record_video_size={"width": 1280, "height": 720},
                viewport={"width": 1280, "height": 720},
            )
            if highlight_script:
                await context.add_init_script(highlight_script)
            await context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = await context.new_page()
            await page.expose_function("_qa_log", lambda m: log(f"[page] {m}"))

            # normalize auth
            auth = auth or {}
            login_url = auth.get("login_url") or target_url.rsplit("/",3)[0] + "/login" if "/login" not in target_url else target_url
            # if target itself is login, keep it
            if auth.get("login_url"):
                login_url = auth["login_url"]
            username = auth.get("username")
            password = await _extract_secret(auth.get("password")) if auth.get("password") else None
            admin_user = auth.get("admin_username")
            admin_pass = await _extract_secret(auth.get("admin_password")) if auth.get("admin_password") else None
            perm_feature = auth.get("permission_feature")
            u_sel = auth.get("username_selector") or "input[type='email'], input[name='email'], input[name='username']"
            p_sel = auth.get("password_selector") or "input[type='password']"
            s_sel = auth.get("submit_selector") or "button[type='submit'], button:has-text('Login'), button:has-text('Sign in')"

            # if auth provided, login first
            if username and password:
                ok = await _do_login(page, login_url, username, password, u_sel, p_sel, s_sel)
                if not ok:
                    await context.tracing.stop(path=trace_path)
                    await context.close(); await browser.close()
                    return {"video_path": None, "trace_path": trace_path, "logs": logs, "button_stats": {}, "need_auth": True, "error": "login failed — check username/password/selectors", "skipped": False}
                # after login, goto target
                log(f"post-login goto {target_url}")
                resp = await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                log(f"goto status={resp.status if resp else 'unknown'} title={await page.title()} url={page.url}")
                # check 403 permission
                if resp and resp.status == 403 and admin_user and admin_pass and perm_feature:
                    log("403 permission denied — trying admin toggle")
                    granted = await _enable_permission_via_admin(page, admin_user, admin_pass, username, perm_feature, login_url, u_sel, p_sel, s_sel)
                    if granted:
                        # re-login as tester
                        await _do_login(page, login_url, username, password, u_sel, p_sel, s_sel)
                        resp = await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                        log(f"retry after admin, status={resp.status if resp else 'unknown'}")
                    else:
                        return {"video_path": None, "trace_path": trace_path, "logs": logs, "button_stats": {}, "need_admin": True, "error": f"tester lacks {perm_feature}, admin toggle failed", "skipped": False}
                elif resp and resp.status == 403:
                    log("403 no admin provided — need_admin")
                    await context.tracing.stop(path=trace_path)
                    await context.close(); await browser.close()
                    return {"video_path": None, "trace_path": trace_path, "logs": logs, "button_stats": {}, "need_admin": True, "error": "403 permission denied — provide admin login + permission_feature", "skipped": False}
            else:
                # no auth — try direct goto and detect need_auth
                log(f"navigating to {target_url} (no auth provided)")
                resp = await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                log(f"goto status={resp.status if resp else 'unknown'} title={await page.title()} url={page.url}")
                # detect auth redirect
                try:
                    cur_url = page.url.lower()
                    txt = (await page.content())[:6000].lower()
                    is_login_page = any(k in cur_url for k in ["/login","/signin","/auth"]) or ("password" in txt and "email" in txt)
                    if resp and resp.status in (401,403) or is_login_page:
                        if not username:
                            log("detected login required but no auth provided -> need_auth")
                            await context.tracing.stop(path=trace_path)
                            await context.close(); await browser.close()
                            vids = list(video_dir.glob("*.webm"))
                            return {"video_path": str(vids[0]) if vids else None, "trace_path": trace_path, "logs": logs, "button_stats": {}, "need_auth": True, "error": "login required — please provide username/password", "skipped": False}
                except Exception as e:
                    log(f"auth detect error: {e}")

            # discover buttons to stress
            buttons = await page.query_selector_all("button, a[role='button'], [data-testid*='button'], input[type='button'], input[type='submit']")
            log(f"found {len(buttons)} button-like elements")
            stressed = 0
            for i, btn in enumerate(buttons[:50]):
                try:
                    await page.evaluate("""(el) => {
                        el.style.outline='3px solid #ff0055';
                        el.style.outlineOffset='2px';
                        el.style.boxShadow='0 0 12px #ff0055';
                        el.__qa_prev = el.style.transform;
                        el.style.transform='scale(1.06)';
                        setTimeout(()=> el.style.transform=el.__qa_prev, 400);
                    }""", btn)
                    await asyncio.sleep(0.35)
                    is_safe = await btn.get_attribute("data-qa-safe")
                    if is_safe == "true":
                        await btn.click(timeout=2000)
                        await page.wait_for_timeout(800)
                        stressed += 1
                except Exception as e:
                    log(f"button {i} stress error: {e}")

            button_stats = {"total": len(buttons), "stressed": stressed, "highlighted": min(len(buttons), 50)}
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.8)
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(0.5)

            await context.tracing.stop(path=trace_path)
            await context.close()
            await browser.close()
            vids = list(video_dir.glob("*.webm"))
            video_file = str(vids[0]) if vids else str(video_dir)
            log(f"recording done video={video_file} trace={trace_path}")
            return {"video_path": video_file, "trace_path": trace_path, "logs": logs, "button_stats": button_stats, "skipped": False}
    except Exception as e:
        log(f"playwright error: {e}")
        return {"video_path": None, "trace_path": None, "logs": logs, "button_stats": button_stats, "error": str(e), "skipped": False}
