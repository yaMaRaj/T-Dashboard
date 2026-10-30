from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


SelectorType = Literal["css", "role", "text", "testid", "placeholder", "label"]
StepAction = Literal[
    "navigate",
    "click",
    "fill",
    "select",
    "hover",
    "press",
    "wait",
    "assert_visible",
    "assert_text",
    "assert_url",
    "assert_attribute",
    "custom",
]


class Step(BaseModel):
    id: str
    action: StepAction
    name: Optional[str] = None
    url: Optional[str] = None
    selector: Optional[str] = None
    selectorType: SelectorType = "css"
    value: Optional[str] = None
    key: Optional[str] = None
    timeoutMs: Optional[int] = None
    attribute: Optional[str] = None
    code: Optional[str] = None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    base_url: str = ""
    default_browser: str = "chromium"
    default_timeout_ms: int = 30000


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    base_url: Optional[str] = None
    default_browser: Optional[str] = None
    default_timeout_ms: Optional[int] = None


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str
    base_url: str
    default_browser: str
    default_timeout_ms: int
    created_at: datetime
    updated_at: datetime
    case_count: int = 0

    model_config = {"from_attributes": True}


class CaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True
    mode: str = "steps"
    steps: list[Step] = Field(default_factory=list)
    script: str = ""


class CaseUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    enabled: Optional[bool] = None
    mode: Optional[str] = None
    steps: Optional[list[Step]] = None
    script: Optional[str] = None


class CaseOut(BaseModel):
    id: int
    project_id: int
    name: str
    description: str
    tags: list[str]
    enabled: bool
    mode: str = "steps"
    steps: list[dict[str, Any]]
    script: str = ""
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    case_ids: list[int] = Field(default_factory=list)
    browser: str = "chromium"
    headless: bool = True
    retries: int = 0
    timeout_ms: int = 30000
    capture_screenshots: bool = False
    record_video: bool = False
    run_immediately: bool = True


class TaskOut(BaseModel):
    id: int
    project_id: int
    name: str
    case_ids: list[int]
    browser: str
    headless: bool
    retries: int
    timeout_ms: int
    capture_screenshots: bool = False
    record_video: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class CaseResultOut(BaseModel):
    id: int
    run_id: int
    case_id: int
    case_name: str
    status: str
    duration_ms: float
    error_message: str
    error_type: str
    screenshot_path: str
    step_results: list[dict[str, Any]]
    artifacts: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class RunOut(BaseModel):
    id: int
    task_id: int
    status: str
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    total: int
    passed: int
    failed: int
    skipped: int
    duration_ms: float
    error_summary: str
    created_at: datetime
    allure_results_path: str = ""
    allure_report_path: str = ""
    task_name: Optional[str] = None
    project_id: Optional[int] = None
    project_name: Optional[str] = None

    model_config = {"from_attributes": True}


class RunDetailOut(RunOut):
    case_results: list[CaseResultOut] = Field(default_factory=list)
    logs: list[dict[str, Any]] = Field(default_factory=list)


class AllureStatusOut(BaseModel):
    run_id: int
    has_results: bool
    has_report: bool
    results_path: Optional[str] = None
    report_path: Optional[str] = None
    report_url: Optional[str] = None
    allure_cli: bool = False
    status: Optional[str] = None
    total: Optional[int] = None
    passed: Optional[int] = None
    failed: Optional[int] = None
    skipped: Optional[int] = None
    duration_ms: Optional[float] = None
    pass_rate: Optional[float] = None
    error_summary: Optional[str] = None
    failed_cases: list[dict[str, Any]] = Field(default_factory=list)


class AllureGenerateOut(BaseModel):
    ok: bool
    run_id: int
    results_path: str
    report_path: str
    report_url: str


class AnalyticsSummary(BaseModel):
    total_runs: int
    total_cases_executed: int
    pass_rate: float
    avg_duration_ms: float
    recent_pass_rates: list[dict[str, Any]]
    failure_top: list[dict[str, Any]]
    slowest_cases: list[dict[str, Any]]
