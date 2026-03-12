"""Job / Report API 스키마."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class JobCreateResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    current_step: Optional[int] = None
    step_label: Optional[str] = None
    step_detail: Optional[str] = None
    progress_pct: int = 0
    company: Optional[str] = None
    job_title: Optional[str] = None
    industry: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_msg: Optional[str] = None
    report_id: Optional[str] = None  # completed 시 채워짐


class JobListResponse(BaseModel):
    jobs: list[JobStatusResponse]


class ReportSummaryResponse(BaseModel):
    report_id: str
    job_id: str
    company: Optional[str] = None
    job_title: Optional[str] = None
    industry: Optional[str] = None
    created_at: datetime
    matched_news_count: Optional[int] = None


class ReportDetailResponse(BaseModel):
    report_id: str
    job_id: str
    resume_profile: Optional[dict[str, Any]] = None
    matched_news: Optional[list[Any]] = None
    matched_news_count: Optional[int] = None
    relevance_analysis: Optional[str] = None
    swot: Optional[dict[str, Any]] = None
    final_report: Optional[str] = None
    created_at: datetime


class ReportListResponse(BaseModel):
    reports: list[ReportSummaryResponse]
