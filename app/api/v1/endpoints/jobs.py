"""Jobs / Reports 엔드포인트.

POST /jobs                    — 분석 job 생성 (즉시 job_id 반환)
GET  /jobs                    — 내 job 목록
GET  /jobs/{job_id}           — job 상태 조회 (프론트 폴링용)
GET  /reports                 — 내 완료 리포트 목록
GET  /reports/{report_id}     — 리포트 상세
"""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.auth import get_optional_user_id
from app.db.base import get_db
from app.db.models import AnalysisJobDB, AnalysisReportDB
from app.db.repositories.job_repository import JobRepository
from app.schemas.job_models import (
    JobCreateResponse,
    JobListResponse,
    JobStatus,
    JobStatusResponse,
    ReportDetailResponse,
    ReportListResponse,
    ReportSummaryResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _extract_text_from_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="pypdf is not installed.",
        )


def _validate_pdf(file: UploadFile | None, data: bytes) -> None:
    if not (file and file.filename):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="자소서 PDF 파일이 필요합니다.",
        )
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"파일 크기 초과 ({len(data) // 1024} KB). 최대 5 MB.",
        )
    filename = file.filename or ""
    if not (filename.endswith(".pdf") or file.content_type == "application/pdf"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="PDF 파일만 지원합니다.",
        )


def _parse_career_level(career_level: str) -> str:
    v = career_level.strip()
    return v if v in ("신입", "경력") else "신입"


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _job_to_response(job: AnalysisJobDB) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=str(job.id),
        status=JobStatus(job.status),
        progress_pct=job.progress_pct,
        retry_count=job.retry_count,
        company=job.company,
        job_title=job.job_title,
        industry=job.industry,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error_msg=job.error_msg,
        report_id=str(job.report_id) if job.report_id else None,
    )


# ---------------------------------------------------------------------------
# POST /jobs — job 생성
# ---------------------------------------------------------------------------

@router.post("", response_model=JobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    file: UploadFile = None,
    company: str = Form(default=""),
    job_title: str = Form(default=""),
    industry: str = Form(default=""),
    career_level: str = Form(default="신입"),
    user_id: Optional[str] = Depends(get_optional_user_id),
    db: Session = Depends(get_db),
) -> JobCreateResponse:
    data = await file.read() if file else b""
    _validate_pdf(file, data)

    loop = asyncio.get_running_loop()
    resume_text = await loop.run_in_executor(None, _extract_text_from_pdf, data)
    resume_text = resume_text.strip()
    if not resume_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="PDF에서 텍스트를 추출할 수 없습니다.",
        )

    repo = JobRepository(db)
    job = repo.create_job(
        user_id=user_id,
        company=company.strip(),
        job_title=job_title.strip(),
        industry=industry.strip(),
        career_level=_parse_career_level(career_level),
        resume_text=resume_text,
    )
    db.commit()
    db.refresh(job)

    return JobCreateResponse(
        job_id=str(job.id),
        status=JobStatus.pending,
        message="분석 요청이 접수되었습니다. GET /jobs/{job_id} 로 진행상황을 확인하세요.",
    )


# ---------------------------------------------------------------------------
# GET /jobs — 내 job 목록
# ---------------------------------------------------------------------------

@router.get("", response_model=JobListResponse)
def list_jobs(
    user_id: Optional[str] = Depends(get_optional_user_id),
    db: Session = Depends(get_db),
) -> JobListResponse:
    if not user_id:
        return JobListResponse(jobs=[])
    repo = JobRepository(db)
    jobs = repo.get_jobs_by_user(user_id)
    return JobListResponse(jobs=[_job_to_response(j) for j in jobs])


# ---------------------------------------------------------------------------
# GET /jobs/{job_id} — job 상태 단건 조회 (폴링용)
# ---------------------------------------------------------------------------

@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job_status(
    job_id: str,
    user_id: Optional[str] = Depends(get_optional_user_id),
    db: Session = Depends(get_db),
) -> JobStatusResponse:
    try:
        jid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="job not found")

    repo = JobRepository(db)
    job = repo.get_job(jid)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")

    return _job_to_response(job)


# ---------------------------------------------------------------------------
# GET /reports — 내 완료 리포트 목록
# ---------------------------------------------------------------------------

@router.get("/reports", response_model=ReportListResponse)
def list_reports(
    user_id: Optional[str] = Depends(get_optional_user_id),
    db: Session = Depends(get_db),
) -> ReportListResponse:
    if not user_id:
        return ReportListResponse(reports=[])
    repo = JobRepository(db)
    rows = repo.get_reports_by_user(user_id)
    result = [
        ReportSummaryResponse(
            report_id=str(report.id),
            job_id=str(job.id),
            company=job.company,
            job_title=job.job_title,
            industry=job.industry,
            created_at=report.created_at,
            matched_news_count=report.matched_news_count,
        )
        for report, job in rows
    ]
    return ReportListResponse(reports=result)


# ---------------------------------------------------------------------------
# GET /reports/{report_id} — 리포트 상세
# ---------------------------------------------------------------------------

@router.get("/reports/{report_id}", response_model=ReportDetailResponse)
def get_report(
    report_id: str,
    user_id: Optional[str] = Depends(get_optional_user_id),
    db: Session = Depends(get_db),
) -> ReportDetailResponse:
    try:
        rid = uuid.UUID(report_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="report not found")

    repo = JobRepository(db)
    report = repo.get_report(rid)
    if not report:
        raise HTTPException(status_code=404, detail="report not found")

    # job_id를 jobs 테이블에서 역조회
    job = db.query(AnalysisJobDB).filter(AnalysisJobDB.report_id == rid).first()

    return ReportDetailResponse(
        report_id=str(report.id),
        job_id=str(job.id) if job else "",
        resume_profile=report.resume_profile,
        matched_news=report.matched_news,
        matched_news_count=report.matched_news_count,
        relevance_analysis=report.relevance_analysis,
        swot=report.swot,
        final_report=report.final_report,
        created_at=report.created_at,
    )
