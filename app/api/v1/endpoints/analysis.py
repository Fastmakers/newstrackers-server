"""분석 엔드포인트 — 프론트엔드 전용 종합 리포트.

Pipeline Report:
    PDF 파싱 → 자소서 분석 → 쿼리 변환 → 하이브리드 검색
    → 병렬 LLM (SWOT ‖ relevance_analysis) → final_report
    → ReportResponse
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status

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
    # Step 4: 쿼리 변환 + 하이브리드 검색
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
    # Step 5: 병렬 LLM — SWOT + relevance_analysis
    # ------------------------------------------------------------------
    news_titles = [item.title for item in matched_news]

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_swot = ex.submit(
            llm_service.generate_swot_list,
            resume_text,
            resolved_company,
            resolved_job_title,
            chunks,
            resolved_industry,
        )
        f_relevance = ex.submit(
            llm_service.generate_relevance_analysis,
            resume_text,
            chunks,
            resolved_company,
            resolved_industry,
            resolved_job_title,
        )
        swot_dict = f_swot.result()
        relevance_analysis = f_relevance.result()

    final_report = llm_service.generate_final_report(
        resume=resume_text,
        company=resolved_company,
        job_title=resolved_job_title,
        industry=resolved_industry,
        swot=swot_dict,
        news_titles=news_titles,
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
