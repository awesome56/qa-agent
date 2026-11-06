from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from app.workers import queue
from app.services.reporter import build_daily_report
from app.config import REPORTS
from app.services.r2 import list_reports as r2_list, list_folders as r2_folders

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

# R2 — Cloudflare bucket qa-reports with timestamp folders
@router.get("/r2/list")
async def r2_list_api(prefix: str = Query("reports/", description="R2 prefix, e.g. reports/hrms-new/2026-08-21/"), project: Optional[str] = None, max_keys: int = 100):
    # allow ?project=hrms-new to filter
    if project:
        prefix = f"reports/{project}/"
    items = r2_list(prefix=prefix, max_keys=max_keys)
    return {"prefix": prefix, "count": len(items), "items": items}

@router.get("/r2/folders")
async def r2_folders_api(prefix: str = Query("reports/", description="R2 prefix to list folders")):
    folders = r2_folders(prefix=prefix)
    return {"prefix": prefix, "folders": folders, "count": len(folders)}

@router.get("/r2/projects")
async def r2_projects():
    folders = r2_folders(prefix="reports/")
    projects = [f.replace("reports/","").rstrip("/") for f in folders]
    # normalize hrms_new -> hrms-new for display, keep both
    display = []
    for p in projects:
        display.append(p)
        if "_" in p:
            display.append(p.replace("_","-"))
    return {"projects": projects, "display": display}

@router.get("/r2/file")
async def r2_file(key: str = Query(..., description="R2 key, e.g. reports/hrms_new/2026-08-21/15-42-01/.../report.pdf")):
    from app.services.r2 import get_s3
    from app.config import settings
    from fastapi.responses import StreamingResponse
    import mimetypes
    s3 = get_s3()
    try:
        obj = s3.get_object(Bucket=settings.r2_bucket_name, Key=key)
        media = mimetypes.guess_type(key)[0] or "application/octet-stream"
        # for video/pdf ensure inline
        return StreamingResponse(obj["Body"].iter_chunks(chunk_size=8192), media_type=media, headers={"Content-Disposition": f'inline; filename="{key.split("/")[-1]}"', "Cache-Control": "public, max-age=3600"})
    except Exception as e:
        raise HTTPException(404, f"R2 file not found: {e}")

@router.delete("/r2/file")
async def r2_delete_file(key: str = Query(..., description="R2 key to delete")):
    from app.services.r2 import delete_file
    ok = delete_file(key)
    if not ok:
        raise HTTPException(500, "delete failed")
    return {"deleted": key}

@router.delete("/r2/folder")
async def r2_delete_folder(prefix: str = Query(..., description="R2 prefix folder to delete, e.g. reports/hrms_new/2026-08-21/15-42-01/")):
    from app.services.r2 import delete_prefix
    if not prefix.startswith("reports/"):
        raise HTTPException(400, "prefix must start with reports/")
    count = delete_prefix(prefix if prefix.endswith("/") else prefix + "/")
    return {"deleted_prefix": prefix, "count": count}
