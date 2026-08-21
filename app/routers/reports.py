from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from datetime import date, datetime
from pathlib import Path
from app.workers import queue
from app.services.reporter import build_daily_report
from app.config import REPORTS

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])

@router.get("/daily/{day}")
async def daily_report(day: str):
    """
    day = YYYY-MM-DD or 'today'
    """
    if day == "today":
        day = date.today().isoformat()
    try:
        d = date.fromisoformat(day)
    except ValueError:
        raise HTTPException(400, "day must be YYYY-MM-DD or today")

    # collect in-memory runs for that day
    all_runs = await queue.list_all()
    todays = [r for r in all_runs.values() if r.created_at.date() == d]
    # also include persisted json if exists but memory is primary for demo
    html_path = build_daily_report(todays, d)
    return FileResponse(str(html_path), media_type="text/html")

@router.get("/daily/{day}/json")
async def daily_json(day: str):
    if day == "today":
        day = date.today().isoformat()
    p = REPORTS / f"{day}.json"
    if not p.exists():
        # build empty
        all_runs = await queue.list_all()
        from datetime import date as d2
        try:
            dd = d2.fromisoformat(day)
        except: 
            raise HTTPException(400, "invalid day")
        todays = [r for r in all_runs.values() if r.created_at.date() == dd]
        from app.services.reporter import build_daily_report as b
        b(todays, dd)
    if not p.exists():
        raise HTTPException(404, "no report")
    return FileResponse(str(p), media_type="application/json")

@router.post("/daily/generate")
async def generate_now():
    d = date.today()
    all_runs = await queue.list_all()
    todays = [r for r in all_runs.values() if r.created_at.date() == d]
    path = build_daily_report(todays, d)
    return {"date": d.isoformat(), "count": len(todays), "html": str(path), "url": f"/api/v1/reports/daily/{d.isoformat()}"}
