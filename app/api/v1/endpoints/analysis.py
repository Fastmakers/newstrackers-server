"""분석 엔드포인트 — 프론트엔드 전용 종합 리포트.

Pipeline Report:
    PDF 파싱 → 자소서 분석 → 쿼리 변환 → 하이브리드 검색 → Cross-Encoder 리랭킹
    → 병렬 LLM (SWOT ‖ relevance_analysis) → final_report
    → ReportResponse

POST /report        — JSON 응답 (기존)
POST /report/stream — SSE 스트리밍 응답 (진행 상황 실시간 전송)
"""

import asyncio
import functools
import json
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from app.core.dependencies import get_llm_service, get_news_service
from app.schemas.data_models import (
    MatchedNewsItem,
    ReportResponse,
    ResumeProfile,
    SWOTList,
)
from app.services.llm_service import LLMService
from app.services.news_service import NewsService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/report", response_model=ReportResponse)
async def create_report(
    file: UploadFile = None,
    industry: str = Form(default=""),
    company: str = Form(default=""),
    job_title: str = Form(default=""),
    career_level: str = Form(default="신입"),
    include_raw_news: str = Form(default="true"),
    report_mode: str = Form(default="fast"),
    news_service: NewsService = Depends(get_news_service),
    llm_service: LLMService = Depends(get_llm_service),
) -> ReportResponse:
    """자소서 PDF → 종합 취업 전략 리포트.

    파이프라인:
        1. PDF 파싱
        2. 자소서 분석 (Claude Haiku) → skills, experiences, target_role
        3. ResumeProfile 구성 (Form 파라미터 우선)
        4. 쿼리 변환 (Claude Haiku) → 뉴스 검색 최적화
        5. 하이브리드 검색 (Vector + pg_trgm → RRF, Top 15) → MatchedNewsItem[]
        6. 병렬 LLM (Claude Sonnet):
           ├─ generate_swot_list  → SWOTList
           ├─ generate_relevance_analysis → markdown
           └─ generate_final_report → markdown
        7. ReportResponse 반환
    """
    from app.api.v1.endpoints.resume import _extract_text_from_pdf

    # ------------------------------------------------------------------
    # Step 1: PDF 파싱
    # ------------------------------------------------------------------
    if not (file and file.filename):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="자소서 PDF 파일이 필요합니다.",
        )

    data = await file.read()
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

    resume_text = _extract_text_from_pdf(data).strip()
    if not resume_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="PDF에서 텍스트를 추출할 수 없습니다.",
        )

    # ------------------------------------------------------------------
    # Step 2: 자소서 분석 (Claude Haiku)
    # ------------------------------------------------------------------
    raw_resume = llm_service.analyze_resume(resume_text)

    # ------------------------------------------------------------------
    # Step 3: ResumeProfile 구성 (Form 파라미터 우선)
    # ------------------------------------------------------------------
    resolved_company = company.strip() or ""
    resolved_job_title = job_title.strip() or raw_resume.get("target_role") or ""
    resolved_industry = industry.strip() or ""
    resolved_skills: list[str] = raw_resume.get("skills") or []
    resolved_experiences: list[str] = raw_resume.get("experience_keywords") or []

    resume_profile = ResumeProfile(
        company=resolved_company,
        job_title=resolved_job_title,
        industry=resolved_industry,
        skills=resolved_skills,
        experiences=resolved_experiences,
    )

    # ------------------------------------------------------------------
    # Step 4: 쿼리 변환 + 하이브리드 검색 → Cross-Encoder 리랭킹 (V3)
    # ------------------------------------------------------------------
    search_input = resume_text[:1500]
    if resolved_company or resolved_job_title:
        meta = f"지원 기업: {resolved_company}\n지원 직무: {resolved_job_title}\n\n"
        search_input = meta + search_input

    transformed = llm_service.transform_query(search_input)
    search_query: str = transformed.get("query") or search_input[:200]
    keyword_query: str = resolved_company or search_query

    chunks = news_service.hybrid_search(
        query=search_query,
        keyword_query=keyword_query,
        top_k=15,
    )

    matched_news: list[MatchedNewsItem] = []
    for chunk in chunks:
        article = chunk.article
        if article is None:
            continue
        distance = getattr(chunk, "distance", 0.0) or 0.0
        matched_news.append(
            MatchedNewsItem(
                id=article.id,
                title=article.title,
                job_category=article.category_l2 or "",
                published_at=article.published_at,
                url=article.article_url or "",
                distance=float(distance),
            )
        )

    # ------------------------------------------------------------------
    # Step 5: 병렬 LLM — swot_list ‖ relevance_analysis → final_report
    # ------------------------------------------------------------------
    resolved_career_level = career_level.strip() if career_level.strip() in ("신입", "경력") else "신입"

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_swot = ex.submit(
            llm_service.generate_swot_list,
            resume_text, resolved_company, resolved_job_title, chunks, resolved_industry, resolved_career_level,
        )
        f_relevance = ex.submit(
            llm_service.generate_relevance_analysis,
            resume_text, chunks, resolved_company, resolved_industry, resolved_job_title, resolved_career_level,
        )
        swot_dict = f_swot.result()
        relevance_analysis = f_relevance.result()

    final_report = llm_service.generate_final_report(
        resume=resume_text,
        company=resolved_company,
        job_title=resolved_job_title,
        industry=resolved_industry,
        swot=swot_dict,
        relevance_analysis=relevance_analysis,
        career_level=resolved_career_level,
    )

    # ------------------------------------------------------------------
    # Step 6: 응답 조립
    # ------------------------------------------------------------------
    return ReportResponse(
        resume_profile=resume_profile,
        matched_news=matched_news,
        matched_news_count=len(matched_news),
        relevance_analysis=relevance_analysis,
        swot=SWOTList(
            strengths=swot_dict.get("strengths", []),
            weaknesses=swot_dict.get("weaknesses", []),
            opportunities=swot_dict.get("opportunities", []),
            threats=swot_dict.get("threats", []),
        ),
        final_report=final_report,
    )


# ---------------------------------------------------------------------------
# SSE 스트리밍 엔드포인트 — 실시간 진행 상황 전송
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
    news_service=Depends(get_news_service),
    llm_service=Depends(get_llm_service),
) -> StreamingResponse:
    """자소서 PDF → 단계별 SSE 진행 이벤트 + 최종 ReportResponse 전송.

    이벤트 형식:
        {"type": "progress", "step": 1..6, "status": "start"|"done", "label": "...", "detail": "..."}
        {"type": "result",   "data": {...ReportResponse...}}
        {"type": "error",    "message": "..."}
    """
    from app.api.v1.endpoints.resume import _extract_text_from_pdf

    # 파일 유효성 검사 — 스트림 시작 전 (HTTPException은 JSON 응답으로 처리됨)
    if not (file and file.filename):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="자소서 PDF 파일이 필요합니다.",
        )
    data = await file.read()
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

    def _emit(step: int, label: str, s: str = "start", detail: str = "") -> str:
        msg: dict = {"type": "progress", "step": step, "status": s, "label": label}
        if detail:
            msg["detail"] = detail
        return f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"

    async def event_stream():
        loop = asyncio.get_running_loop()
        try:
            # ── Step 1: PDF 파싱 ──────────────────────────────────────────
            yield _emit(1, "PDF 파싱 중...")
            resume_text = await loop.run_in_executor(None, _extract_text_from_pdf, data)
            resume_text = resume_text.strip()
            if not resume_text:
                yield f"data: {json.dumps({'type': 'error', 'message': 'PDF에서 텍스트를 추출할 수 없습니다.'}, ensure_ascii=False)}\n\n"
                return
            yield _emit(1, "PDF 파싱 완료", "done", f"{len(resume_text):,}자 추출")

            # ── Step 2 ‖ 3: 자소서 분석 + 검색 쿼리 최적화 (병렬) ──────
            # Form 파라미터(company/job_title)는 이미 알고 있으므로
            # analyze_resume를 기다리지 않고 transform_query도 즉시 시작한다.
            yield _emit(2, "자소서 AI 분석 중...")
            yield _emit(3, "검색 쿼리 최적화 중...")
            search_input = resume_text[:1500]
            if company.strip() or job_title.strip():
                search_input = f"지원 기업: {company.strip()}\n지원 직무: {job_title.strip()}\n\n" + search_input
            raw_resume, transformed = await asyncio.gather(
                loop.run_in_executor(None, llm_service.analyze_resume, resume_text),
                loop.run_in_executor(None, llm_service.transform_query, search_input),
            )
            resolved_company = company.strip() or ""
            resolved_job_title = job_title.strip() or raw_resume.get("target_role") or ""
            resolved_industry = industry.strip() or ""
            resolved_career_level = career_level.strip() if career_level.strip() in ("신입", "경력") else "신입"
            resolved_skills: list[str] = raw_resume.get("skills") or []
            resolved_experiences: list[str] = raw_resume.get("experience_keywords") or []
            resume_profile = ResumeProfile(
                company=resolved_company, job_title=resolved_job_title,
                industry=resolved_industry, skills=resolved_skills, experiences=resolved_experiences,
            )
            search_query: str = transformed.get("query") or search_input[:200]
            keyword_query: str = resolved_company or search_query
            yield _emit(2, "자소서 분석 완료", "done", f"스킬 {len(resolved_skills)}개 추출")
            yield _emit(3, "검색 쿼리 최적화 완료", "done")

            # ── Step 4: 하이브리드 검색 + Cross-Encoder 리랭킹 ──────────
            yield _emit(4, "관련 뉴스 하이브리드 검색 중...")
            chunks = await loop.run_in_executor(
                None,
                functools.partial(news_service.hybrid_search, query=search_query, keyword_query=keyword_query, top_k=15),
            )
            matched_news: list[MatchedNewsItem] = []
            for chunk in chunks:
                article = chunk.article
                if article is None:
                    continue
                distance = getattr(chunk, "distance", 0.0) or 0.0
                matched_news.append(MatchedNewsItem(
                    id=article.id, title=article.title,
                    job_category=article.category_l2 or "",
                    published_at=article.published_at,
                    url=article.article_url or "",
                    distance=float(distance),
                ))
            yield _emit(4, "뉴스 검색 완료", "done", f"{len(matched_news)}건 매칭")

            # ── Step 5: SWOT + 산업 분석 (병렬) ─────────────────────────
            yield _emit(5, "SWOT + 산업 연관성 분석 중...")
            swot_dict, relevance_analysis = await asyncio.gather(
                loop.run_in_executor(None, functools.partial(
                    llm_service.generate_swot_list,
                    resume_text, resolved_company, resolved_job_title, chunks, resolved_industry, resolved_career_level,
                )),
                loop.run_in_executor(None, functools.partial(
                    llm_service.generate_relevance_analysis,
                    resume_text, chunks, resolved_company, resolved_industry, resolved_job_title, resolved_career_level,
                )),
            )
            yield _emit(5, "SWOT + 산업 분석 완료", "done")

            # ── Step 6: 최종 리포트 ──────────────────────────────────────
            yield _emit(6, "최종 면접 리포트 생성 중...")
            final_report = await loop.run_in_executor(
                None,
                functools.partial(
                    llm_service.generate_final_report,
                    resume=resume_text, company=resolved_company, job_title=resolved_job_title,
                    industry=resolved_industry, swot=swot_dict, relevance_analysis=relevance_analysis,
                    career_level=resolved_career_level,
                ),
            )
            yield _emit(6, "리포트 생성 완료", "done")

            # ── 최종 결과 전송 ────────────────────────────────────────────
            result = ReportResponse(
                resume_profile=resume_profile,
                matched_news=matched_news,
                matched_news_count=len(matched_news),
                relevance_analysis=relevance_analysis,
                swot=SWOTList(
                    strengths=swot_dict.get("strengths", []),
                    weaknesses=swot_dict.get("weaknesses", []),
                    opportunities=swot_dict.get("opportunities", []),
                    threats=swot_dict.get("threats", []),
                ),
                final_report=final_report,
            )
            yield f"data: {json.dumps({'type': 'result', 'data': result.model_dump(mode='json')}, ensure_ascii=False, default=str)}\n\n"

        except Exception as exc:
            logger.error("report/stream 오류: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
