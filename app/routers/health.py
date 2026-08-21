from fastapi import APIRouter
from datetime import datetime

router = APIRouter()

@router.get("/health")
async def health():
    return {"status": "ok", "ts": datetime.utcnow().isoformat(), "service": "qa-agent"}

@router.get("/")
async def root():
    return {"service": "qa-agent", "version": "0.1.0", "docs": "/docs", "sse": "/api/v1/test/{id}/stream"}
