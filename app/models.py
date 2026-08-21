from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, Literal, List, Dict, Any
from datetime import datetime
from enum import Enum
import uuid

class TestStatus(str, Enum):
    queued = "queued"
    running = "running"
    passed = "passed"
    failed = "failed"
    error = "error"

class TestRequest(BaseModel):
    target_url: str = Field(description="URL to test, e.g. https://my-app.com")
    scenario: str = Field(default="smoke", description="smoke | stress | load | full")
    vus: int = Field(default=10, ge=1, le=5000, description="virtual users for k6")
    duration: str = Field(default="30s", description="k6 duration e.g. 30s, 2m")
    record_video: bool = True
    highlight_buttons: bool = True
    webhook_callback_url: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class TestResult(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: TestStatus = TestStatus.queued
    request: TestRequest
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    video_path: Optional[str] = None
    trace_path: Optional[str] = None
    k6_summary: Optional[Dict[str, Any]] = None
    playwright_summary: Optional[Dict[str, Any]] = None
    report_path: Optional[str] = None
    error: Optional[str] = None
    logs: List[str] = Field(default_factory=list)

class DailyReport(BaseModel):
    date: str
    total_runs: int
    passed: int
    failed: int
    avg_p95_ms: Optional[float] = None
    slowest_url: Optional[str] = None
    items: List[TestResult] = Field(default_factory=list)
    html_path: Optional[str] = None
