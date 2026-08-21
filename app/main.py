from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import asyncio
from datetime import date
from contextlib import asynccontextmanager

from app.routers import health, tests, reports, webhook, mcp, intake
from app.workers import queue
from app.services.reporter import build_daily_report
from app.config import REPORTS, STORAGE

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup: schedule daily report at midnight UTC (simple loop)
    async def daily_loop():
        while True:
            # sleep until next 23:59 UTC then generate
            # for demo: generate every 6h
            await asyncio.sleep(6*3600)
            try:
                all_runs = await queue.list_all()
                todays = [r for r in all_runs.values() if r.created_at.date() == date.today()]
                if todays:
                    build_daily_report(todays, date.today())
                    print(f"[reporter] daily report generated {len(todays)} runs")
            except Exception as e:
                print(f"[reporter] error {e}")
    task = asyncio.create_task(daily_loop())
    yield
    task.cancel()

app = FastAPI(title="QA Stress Agent", version="0.1.0", description="Screen-record + highlight + stress/load + RAG/graph + SSE — qa.awesometech.com.ng", lifespan=lifespan)

from app.config import settings
origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins != ["*"] else ["*"],
    allow_origin_regex=r"https://.*\.awesometech\.com\.ng",
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.include_router(health.router)
app.include_router(tests.router)
app.include_router(reports.router)
app.include_router(webhook.router)
app.include_router(mcp.router)
app.include_router(mcp.agent_router)
app.include_router(intake.router)

# serve storage (videos/reports) read-only
if STORAGE.exists():
    app.mount("/storage", StaticFiles(directory=str(STORAGE)), name="storage")
