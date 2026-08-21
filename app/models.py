from pydantic import BaseModel, Field, HttpUrl, SecretStr
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

class ProjectType(str, Enum):
    hrms_new = "hrms-new"
    aperte = "aperte"
    examco = "examco"
    power = "power"
    phonestation = "phonestation"
    awesometech = "awesometech"
    other = "other"

class TestScope(str, Enum):
    feature = "feature"          # just the feature/bugfix stated
    test_cases = "test_cases"    # functional test cases
    edge_cases = "edge_cases"    # edge / negative cases
    load = "load"                # soak load
    stress = "stress"            # spike/stress
    all = "all"                  # everything

class AuthConfig(BaseModel):
    login_url: Optional[str] = Field(default=None, description="Login page, defaults to {target_url}/login")
    username: Optional[str] = None
    password: Optional[SecretStr] = None
    # second login to grant permission
    admin_username: Optional[str] = None
    admin_password: Optional[SecretStr] = None
    permission_feature: Optional[str] = Field(default=None, description="e.g. leave_approval, hrms:manage_staff")
    # selectors override if hrms form differs
    username_selector: str = Field(default="input[type='email'], input[name='email'], input[name='username']")
    password_selector: str = Field(default="input[type='password']")
    submit_selector: str = Field(default="button[type='submit'], button:has-text('Login'), button:has-text('Sign in')")

class TestRequest(BaseModel):
    project: ProjectType = Field(default=ProjectType.other, description="hrms-new | aperte | examco | other")
    target_url: str = Field(description="URL to test, e.g. https://hrms.awesometech.com.ng/leave")
    scenario: str = Field(default="smoke", description="free text: bugfix/feature description")
    scope: TestScope = Field(default=TestScope.feature, description="feature | test_cases | edge_cases | load | stress | all")
    vus: int = Field(default=10, ge=1, le=5000, description="virtual users for k6 (used if scope includes load/stress)")
    duration: str = Field(default="30s", description="k6 duration e.g. 30s, 2m")
    record_video: bool = True
    highlight_buttons: bool = True
    auth: Optional[AuthConfig] = None
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
