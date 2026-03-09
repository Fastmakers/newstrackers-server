"""분석 엔드포인트 — 얇은 HTTP 핸들러.

비즈니스 로직은 ReportPipeline에 위임한다.

POST /report        — JSON 응답
POST /report/stream — SSE 스트리밍 응답
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from app.core.dependencies import get_report_pipeline
from app.schemas.data_models import ReportResponse
from app.services.report_pipeline import ReportInput, ReportPipeline

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 공유 헬퍼
# ---------------------------------------------------------------------------

def _validate_pdf(file: UploadFile | None, data: bytes) -> None:
    """파일 유효성 검사 — 실패 시 HTTPException 발생."""
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
# POST /report — JSON 응답
# ---------------------------------------------------------------------------

@router.post("/report", response_model=ReportResponse)
async def create_report(
    file: UploadFile = None,
    industry: str = Form(default=""),
    company: str = Form(default=""),
    job_title: str = Form(default=""),
    career_level: str = Form(default="신입"),
    include_raw_news: str = Form(default="true"),
    report_mode: str = Form(default="fast"),
    pipeline: ReportPipeline = Depends(get_report_pipeline),
) -> ReportResponse:
    """자소서 PDF → 종합 취업 전략 리포트 (JSON)."""
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

    inp = ReportInput(
        resume_text=resume_text,
        company=company.strip(),
        job_title=job_title.strip(),
        industry=industry.strip(),
        career_level=_parse_career_level(career_level),
    )

    return await loop.run_in_executor(None, pipeline.run, inp)


# ---------------------------------------------------------------------------
# POST /report/stream — SSE 스트리밍 응답
# ---------------------------------------------------------------------------

@router.post("/report/stream")
async def create_report_stream(
    file: UploadFile = None,
    industry: str = Form(default=""),
    company: str = Form(default=""),
    job_title: str = Form(default=""),
    career_level: str = Form(default="신입"),
    include_raw_news: str = Form(default="true"),
    report_mode: str = Form(default="fast"),
    pipeline: ReportPipeline = Depends(get_report_pipeline),
) -> StreamingResponse:
    """자소서 PDF → 단계별 SSE 진행 이벤트 + 최종 ReportResponse 전송.

    이벤트 형식:
        {"type": "progress", "step": 1..6, "status": "start"|"done", "label": "...", "detail": "..."}
        {"type": "result",   "data": {...ReportResponse...}}
        {"type": "error",    "message": "..."}
    """
    from app.api.v1.endpoints.resume import _extract_text_from_pdf

    # 파일 유효성 검사 — 스트림 시작 전 (HTTPException은 JSON 응답으로 처리됨)
    data = await file.read() if file else b""
    _validate_pdf(file, data)

    inp = ReportInput(
        resume_text="",  # step 1 이후 채워짐
        company=company.strip(),
        job_title=job_title.strip(),
        industry=industry.strip(),
        career_level=_parse_career_level(career_level),
    )

    def _emit(step: int, label: str, s: str = "start", detail: str = "") -> str:
        msg: dict = {"type": "progress", "step": step, "status": s, "label": label}
        if detail:
            msg["detail"] = detail
        return f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"

    async def event_stream():
        loop = asyncio.get_running_loop()
        try:
            # Step 1: PDF 파싱 (HTTP 레이어 책임)
            yield _emit(1, "PDF 파싱 중...")
            resume_text = await loop.run_in_executor(None, _extract_text_from_pdf, data)
            resume_text = resume_text.strip()
            if not resume_text:
                yield f"data: {json.dumps({'type': 'error', 'message': 'PDF에서 텍스트를 추출할 수 없습니다.'}, ensure_ascii=False)}\n\n"
                return
            yield _emit(1, "PDF 파싱 완료", "done", f"{len(resume_text):,}자 추출")

            # Step 2~6: 파이프라인에 위임
            inp.resume_text = resume_text
            async for event in pipeline.stream(inp):
                yield event

        except Exception as exc:
            logger.error("report/stream 오류: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
