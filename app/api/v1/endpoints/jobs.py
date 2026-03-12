"""Jobs / Reports 엔드포인트.

POST /jobs                    — 분석 job 생성 (즉시 job_id 반환)
GET  /jobs                    — 내 job 목록
GET  /jobs/{job_id}           — job 상태 조회
GET  /jobs/{job_id}/stream    — SSE로 진행상황 구독 (재접속 가능)
GET  /reports                 — 내 완료 리포트 목록
GET  /reports/{report_id}     — 리포트 상세
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.auth import get_optional_user_id
from app.core.dependencies import get_report_pipeline
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
from app.services.report_pipeline import ReportPipeline

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _job_to_response(job: AnalysisJobDB, report_id: Optional[str] = None) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=str(job.id),
        status=JobStatus(job.status),
        current_step=job.current_step,
        step_label=job.step_label,
        step_detail=job.step_detail,
        progress_pct=job.progress_pct,
        company=job.company,
        job_title=job.job_title,
        industry=job.industry,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error_msg=job.error_msg,
        report_id=report_id,
    )


def _report_to_summary(report: AnalysisReportDB, job: AnalysisJobDB) -> ReportSummaryResponse:
    return ReportSummaryResponse(
        report_id=str(report.id),
        job_id=str(report.job_id),
        company=job.company,
        job_title=job.job_title,
        industry=job.industry,
        created_at=report.created_at,
        matched_news_count=report.matched_news_count,
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
    """자소서 PDF + 파라미터를 받아 분석 Job을 생성하고 job_id를 즉시 반환.

    실제 분석은 Worker가 비동기로 처리하며, GET /jobs/{job_id} 또는
    GET /jobs/{job_id}/stream 으로 진행상황을 확인한다.
    """
    from app.api.v1.endpoints.analysis import _parse_career_level, _validate_pdf
    from app.api.v1.endpoints.resume import _extract_text_from_pdf

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
    result = []
    for job in jobs:
        rid = None
        if job.status == "completed":
            report = repo.get_report_by_job(job.id)
            rid = str(report.id) if report else None
        result.append(_job_to_response(job, rid))
    return JobListResponse(jobs=result)


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

    # report_id를 포함하기 위해 report 로드
    report = repo.get_report_by_job(jid)
    report_id = str(report.id) if report and job.status == "completed" else None

    return JobStatusResponse(
        job_id=str(job.id),
        status=JobStatus(job.status),
        current_step=job.current_step,
        step_label=job.step_label,
        step_detail=job.step_detail,
        progress_pct=job.progress_pct,
        company=job.company,
        job_title=job.job_title,
        industry=job.industry,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error_msg=job.error_msg,
        report_id=report_id,
    )


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}/stream — SSE 진행상황 구독 (재접속 지원)
# ---------------------------------------------------------------------------

@router.get("/{job_id}/stream")
async def stream_job_progress(
    job_id: str,
    user_id: Optional[str] = Depends(get_optional_user_id),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """SSE로 job 진행상황을 구독한다.

    - 진행중: DB를 1.5초마다 폴링해 변화가 있을 때만 이벤트 발송
    - 완료/실패: 현재 상태를 즉시 발송 후 스트림 종료
    - 재접속 시: 이미 완료된 job이면 결과를 바로 돌려줌

    이벤트 형식 (기존 /report/stream 과 동일):
        {"type": "progress", "step": N, "status": "done", "label": "...", "detail": "..."}
        {"type": "result",   "data": {...ReportResponse...}}
        {"type": "error",    "message": "..."}
    """
    try:
        jid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="job not found")

    # 초기 job 존재 확인
    repo = JobRepository(db)
    job = repo.get_job(jid)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")

    async def event_gen():
        from app.db.base import SessionLocal

        prev_pct = -1

        while True:
            s = SessionLocal()
            try:
                r = JobRepository(s)
                job = r.get_job(jid)
                if not job:
                    yield _sse_error("job not found")
                    return

                # 진행상황 변화 시 emit
                if job.progress_pct != prev_pct or job.status in ("completed", "failed"):
                    prev_pct = job.progress_pct
                    if job.current_step is not None:
                        yield _sse_progress(
                            job.current_step,
                            job.step_label or "",
                            "done",
                            job.step_detail or "",
                            job.progress_pct,
                        )

                if job.status == "completed":
                    report = r.get_report_by_job(jid)
                    if report:
                        yield _sse_result(report)
                    return

                if job.status == "failed":
                    yield _sse_error(job.error_msg or "분석 중 오류가 발생했습니다.")
                    return

            finally:
                s.close()

            await asyncio.sleep(1.5)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


def _sse_progress(step: int, label: str, status_str: str, detail: str, pct: int) -> str:
    msg = {
        "type": "progress",
        "step": step,
        "status": status_str,
        "label": label,
        "detail": detail,
        "progress_pct": pct,
    }
    return f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"


def _sse_result(report: AnalysisReportDB) -> str:
    data = {
        "resume_profile": report.resume_profile,
        "matched_news": report.matched_news,
        "matched_news_count": report.matched_news_count,
        "relevance_analysis": report.relevance_analysis,
        "swot": report.swot,
        "final_report": report.final_report,
    }
    msg = {"type": "result", "data": data}
    return f"data: {json.dumps(msg, ensure_ascii=False, default=str)}\n\n"


def _sse_error(message: str) -> str:
    return f"data: {json.dumps({'type': 'error', 'message': message}, ensure_ascii=False)}\n\n"


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
    reports = repo.get_reports_by_user(user_id)
    result = []
    for r in reports:
        job = repo.get_job(r.job_id)
        if job:
            result.append(_report_to_summary(r, job))
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

    return ReportDetailResponse(
        report_id=str(report.id),
        job_id=str(report.job_id),
        resume_profile=report.resume_profile,
        matched_news=report.matched_news,
        matched_news_count=report.matched_news_count,
        relevance_analysis=report.relevance_analysis,
        swot=report.swot,
        final_report=report.final_report,
        created_at=report.created_at,
    )
