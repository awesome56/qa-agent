"""
Playwright recorder — screen records + highlights buttons to stress.
Injects playwright/highlight.js via addInitScript.
"""
import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

HIGHLIGHT_JS = Path(__file__).parent.parent.parent / "playwright" / "highlight.js"

async def run_playwright_recording(target_url: str, test_id: str, storage_dir: Path, highlight: bool = True) -> Dict[str, Any]:
    """
    Returns {video_path, trace_path, log, button_stats}
    Falls back to no-op if playwright browsers not installed (for CI without deps).
    """
    from app.config import VIDEOS, TRACES
    video_dir = VIDEOS / test_id
    video_dir.mkdir(parents=True, exist_ok=True)
    trace_path = str(TRACES / f"{test_id}.zip")
    video_path = str(video_dir)

    logs = []
    def log(msg: str):
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

            # expose function to collect button highlights from page
            await page.expose_function("_qa_log", lambda m: log(f"[page] {m}"))

            log(f"navigating to {target_url}")
            resp = await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            log(f"goto status={resp.status if resp else 'unknown'} title={await page.title()}")

            # discover buttons to stress
            buttons = await page.query_selector_all("button, a[role='button'], [data-testid*='button'], input[type='button'], input[type='submit']")
            log(f"found {len(buttons)} button-like elements")

            # stress-highlight: sequentially pulse each button and click if safe (opt-in via data-qa-safe)
            stressed = 0
            for i, btn in enumerate(buttons[:50]):  # cap 50
                try:
                    box = await btn.bounding_box()
                    text = (await btn.inner_text())[:40] if await btn.is_visible() else ""
                    await page.evaluate("""(el) => {
                        el.style.outline='3px solid #ff0055';
                        el.style.outlineOffset='2px';
                        el.style.boxShadow='0 0 12px #ff0055';
                        el.__qa_prev = el.style.transform;
                        el.style.transform='scale(1.06)';
                        setTimeout(()=> el.style.transform=el.__qa_prev, 400);
                    }""", btn)
                    await asyncio.sleep(0.35)
                    # only auto-click buttons marked safe to avoid destructive actions
                    is_safe = await btn.get_attribute("data-qa-safe")
                    if is_safe == "true":
                        await btn.click(timeout=2000)
                        await page.wait_for_timeout(800)
                        stressed += 1
                except Exception as e:
                    log(f"button {i} stress error: {e}")

            button_stats = {"total": len(buttons), "stressed": stressed, "highlighted": min(len(buttons), 50)}

            # scroll + capture a bit
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.8)
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(0.5)

            await context.tracing.stop(path=trace_path)
            await context.close()
            await browser.close()

            # find actual video file (playwright saves as .webm after close)
            vids = list(video_dir.glob("*.webm"))
            video_file = str(vids[0]) if vids else str(video_dir)
            log(f"recording done video={video_file} trace={trace_path}")

            return {
                "video_path": video_file,
                "trace_path": trace_path,
                "logs": logs,
                "button_stats": button_stats,
                "skipped": False,
            }
    except Exception as e:
        log(f"playwright error: {e}")
        return {"video_path": None, "trace_path": None, "logs": logs, "button_stats": button_stats, "error": str(e), "skipped": False}
