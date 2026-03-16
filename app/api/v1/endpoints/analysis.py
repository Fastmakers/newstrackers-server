"""POST /api/v1/analysis/stream — 단계별 결과 스트리밍 엔드포인트.

docs/07_progressive_stream_spec.md Phase 2 구현.

흐름:
    1. PDF 파싱 (step 1, HTTP 레이어)
    2. ReportPipeline.stream() → SSE 이벤트 실시간 전달
    3. 스트림 완료 후 Job(completed) + Report DB 저장
    4. 최종 result 이벤트에 job_id, report_id 포함하여 전송
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.auth import get_optional_user_id
from app.core.dependencies import get_report_pipeline
from app.db.base import get_db
from app.db.repositories.job_repository import JobRepository
from app.services.report_pipeline import ReportInput, ReportPipeline

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 헬퍼 (jobs.py 와 동일, 로컬 복사)
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
# POST /stream
# ---------------------------------------------------------------------------

@router.post("/stream")
async def stream_analysis(
    file: UploadFile = None,
    company: str = Form(default=""),
    job_title: str = Form(default=""),
    industry: str = Form(default=""),
    career_level: str = Form(default="신입"),
    user_id: Optional[str] = Depends(get_optional_user_id),
    pipeline: ReportPipeline = Depends(get_report_pipeline),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """PDF + 지원 정보를 받아 단계별 분석 결과를 SSE로 스트리밍한다.

    이벤트 형식은 docs/07_progressive_stream_spec.md §2 참고.
    스트리밍 완료 후 Job(completed) + Report 를 DB에 저장하고,
    최종 result 이벤트에 job_id / report_id 를 포함한다.
    """
    # Step 1: PDF 파싱 (HTTP 레이어)
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

    inp = ReportInput(
        resume_text=resume_text,
        company=company.strip(),
        job_title=job_title.strip(),
        industry=industry.strip(),
        career_level=_parse_career_level(career_level),
    )

    async def _sse():
        result_data: dict | None = None

        try:
            async for raw in pipeline.stream(inp):
                line = raw.strip()
                if line.startswith("data: "):
                    try:
                        ev = json.loads(line[6:])
                        if ev.get("type") == "result":
                            result_data = ev
                            continue  # DB 저장 후 job_id/report_id 추가해서 yield
                    except json.JSONDecodeError:
                        pass
                yield raw
        except Exception as exc:
            logger.error("stream_analysis 파이프라인 오류: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"
            return

        # 스트림 완료 후 DB 저장
        if result_data is not None:
            try:
                uid = uuid.UUID(user_id) if user_id else None
                repo = JobRepository(db)

                job = repo.create_job(
                    user_id=user_id,
                    company=inp.company,
                    job_title=inp.job_title,
                    industry=inp.industry,
                    career_level=inp.career_level,
                    resume_text=inp.resume_text,
                )
                db.flush()  # job.id 확보

                report_payload = result_data.get("data", {})
                report = repo.save_report(
                    job_id=job.id,
                    user_id=uid,
                    report_data=report_payload,
                )

                job.status = "completed"
                job.progress_pct = 100
                job.completed_at = datetime.now(timezone.utc)

                db.commit()

                result_data["job_id"] = str(job.id)
                result_data["report_id"] = str(report.id)
                logger.info(
                    "stream_analysis 완료 — job_id=%s report_id=%s",
                    job.id, report.id,
                )
            except Exception as exc:
                logger.error("stream_analysis DB 저장 실패: %s", exc)
                try:
                    db.rollback()
                except Exception:
                    pass

            yield f"data: {json.dumps(result_data, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
