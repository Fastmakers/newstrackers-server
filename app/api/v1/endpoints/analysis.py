"""산업 트렌드 · 기업 면접 준비 분석 엔드포인트.

파이프라인 (batch):
    Industry: fetch_articles → (extract_trends ‖ extract_keywords ‖ monthly_sentiment ‖ source_stats) → 조립
    Company:  (fetch_articles ‖ analyze_resume) → (swot ‖ interview_qna ‖ radar ‖ themes ‖ risks ‖ info) → 조립

파이프라인 (stream):
    Industry/Company: fetch_articles → SSE stream (Claude Haiku)
"""

import json
import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from app.core.dependencies import get_llm_service, get_news_service
from app.schemas.data_models import (
    CompanyAnalysis,
    CompanyAnalysisRequest,
    CompanyInfo,
    CompanyNewsArticle,
    IndustryAnalysisRequest,
    IndustryData,
    InterviewQNA,
    Keyword,
    MonthlySentiment,
    NewsArticle,
    RadarChart,
    ResumeAnalysis,
    RiskAssessment,
    SourceStats,
    SWOT,
)
from app.services.llm_service import LLMService
from app.services.news_service import NewsService

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 휴리스틱 헬퍼 (LLM 불필요 — 키워드 빈도 기반)
# ---------------------------------------------------------------------------

_POSITIVE_WORDS = ["성장", "증가", "확대", "강화", "개선", "혁신", "성공", "달성"]
_NEGATIVE_WORDS = ["하락", "감소", "위기", "악화", "문제", "도전", "어려움", "손실"]

_DIMENSION_KEYWORDS = [
    ["성장", "매출", "증수", "확대", "상장", "시장 점유율"],   # 성장성
    ["안정", "일관", "지속", "신뢰", "신용등급", "건전성"],   # 안정성
    ["혁신", "기술", "R&D", "개발", "특허"],                  # 혁신성
    ["ESG", "환경", "지속가능", "사회", "윤리", "탄소중립"],  # ESG
    ["점유율", "시장", "지위", "경쟁", "리더", "선두"],        # 시장점유율
]

_RISK_KEYWORDS = {
    "규제 리스크": ["규제", "제재", "조사"],
    "시장 변화": ["하락", "감소", "경쟁"],
    "기술 리스크": ["구식", "교체", "위협"],
    "공급망 리스크": ["공급", "부족", "중단"],
}
_OPPORTUNITY_KEYWORDS = {
    "AI/기술": ["AI", "머신러닝", "자동화", "데이터"],
    "시장 확대": ["신시장", "해외", "확장"],
    "혁신 제품": ["신상품", "출시", "개발"],
    "파트너십": ["협력", "제휴", "인수"],
}


def _compute_monthly_sentiment(articles: list[NewsArticle]) -> list[MonthlySentiment]:
    """기사 키워드 빈도로 월별 감성 점수 산출 (휴리스틱)."""
    monthly: dict[str, dict] = {}
    for article in articles:
        if not article.published_at:
            continue
        key = article.published_at.strftime("%Y-%m")
        if key not in monthly:
            monthly[key] = {"count": 0, "positive": 0, "negative": 0, "keywords": []}
        monthly[key]["count"] += 1
        text = f"{article.title} {article.content[:200]}".lower()
        if any(w in text for w in _POSITIVE_WORDS):
            monthly[key]["positive"] += 1
        if any(w in text for w in _NEGATIVE_WORDS):
            monthly[key]["negative"] += 1
        monthly[key]["keywords"].extend(
            t.title() for t in article.title.split() if len(t) > 2
        )

    result = []
    for key in sorted(monthly)[-12:]:
        d = monthly[key]
        total = d["count"]
        pos_r = d["positive"] / total if total else 0
        neg_r = d["negative"] / total if total else 0
        score = round(max(0.0, min(10.0, 5 + (pos_r - neg_r) * 5)), 1)
        intensity = min(10, max(1, total // 2))
        top_kw = [k for k, _ in Counter(d["keywords"]).most_common(3)]
        result.append(MonthlySentiment(
            month=key,
            intensity=intensity,
            score=score,
            issue=", ".join(top_kw) if top_kw else "뉴스 추적 중",
        ))
    return result


def _compute_source_stats(articles: list[NewsArticle], days_back: int) -> SourceStats:
    sources = Counter(a.source for a in articles if a.source)
    return SourceStats(
        total_articles=len(articles),
        date_range_days=days_back,
        top_sources=[s for s, _ in sources.most_common(5)],
        last_updated=datetime.now(),
    )


def _extract_company_info(company: str, articles: list[NewsArticle]) -> CompanyInfo:
    snippet = next((a.content[:200] for a in articles[:5] if a.content), None)
    return CompanyInfo(
        description=snippet or f"{company}에 대한 정보가 제한적입니다.",
    )


def _score_five_dimensions(articles: list[NewsArticle]) -> RadarChart:
    text = " ".join(f"{a.title} {a.content[:200]}" for a in articles[:20]).lower()

    def _score(keywords: list[str]) -> float:
        count = sum(text.count(kw) for kw in keywords)
        raw = min(10.0, (count / 5.0) * 10.0)
        return round(max(1.0, min(9.0, 5.0 + raw + (count % 3) * 0.5 - 3.0)), 1)

    return RadarChart(scores=[_score(kws) for kws in _DIMENSION_KEYWORDS])


def _extract_news_themes(articles: list[NewsArticle]) -> list[str]:
    themes: list[str] = []
    for a in articles[:10]:
        words = a.title.split()
        themes.extend(
            " ".join(words[i:i + 3])
            for i in range(len(words) - 2)
            if len(" ".join(words[i:i + 3])) > 5
        )
    top = [t for t, _ in Counter(themes).most_common(4)]
    return top if top else ["뉴스 분석 중"]


def _assess_risks(company: str, articles: list[NewsArticle]) -> RiskAssessment:
    text = " ".join(f"{a.title} {a.content[:200]}" for a in articles[:15]).lower()
    risks = [r for r, kws in _RISK_KEYWORDS.items() if any(kw in text for kw in kws)]
    opps = [o for o, kws in _OPPORTUNITY_KEYWORDS.items() if any(kw in text for kw in kws)]
    return RiskAssessment(
        critical_risks=risks[:3] or ["기본 시장 리스크"],
        growth_opportunities=opps[:3] or ["지속적 성장"],
        recommended_focus=(
            f"{company}의 성공을 위해 "
            f"{'기술 혁신' if opps else '시장 안정성'} 중심의 전략이 필요합니다."
        ),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/industry", response_model=IndustryData)
def analyze_industry(
    request: IndustryAnalysisRequest,
    news_service: NewsService = Depends(get_news_service),
    llm_service: LLMService = Depends(get_llm_service),
) -> IndustryData:
    """산업 트렌드 배치 분석.

    트렌드·키워드 (LLM) + 월별 감성·출처 통계 (휴리스틱)를 병렬 산출합니다.
    """
    articles = news_service.get_articles(request.industry)

    with ThreadPoolExecutor(max_workers=4) as ex:
        f_trends = ex.submit(llm_service.extract_trends, articles, request.industry)
        f_keywords = ex.submit(llm_service.extract_keywords, articles)
        f_sentiment = ex.submit(_compute_monthly_sentiment, articles)
        f_stats = ex.submit(_compute_source_stats, articles, request.days_back)

        trends = f_trends.result()
        keywords_raw = f_keywords.result()
        sentiment = f_sentiment.result()
        source_stats = f_stats.result()

    if len(trends) < 3:
        trends = (trends + ["뉴스 데이터를 찾을 수 없습니다."] * 3)[:3]

    now = datetime.now()
    return IndustryData(
        industry=request.industry,
        period={
            "from": (now - timedelta(days=request.days_back)).strftime("%Y-%m-%d"),
            "to": now.strftime("%Y-%m-%d"),
        },
        trends=trends,
        keywords=[Keyword(**kw) for kw in keywords_raw],
        monthly_sentiment=sentiment,
        source_stats=source_stats,
    )


@router.post("/company", response_model=CompanyAnalysis)
def analyze_company(
    request: CompanyAnalysisRequest,
    news_service: NewsService = Depends(get_news_service),
    llm_service: LLMService = Depends(get_llm_service),
) -> CompanyAnalysis:
    """기업 면접 준비 배치 분석.

    Step 1 (병렬): 기사 검색 + 자소서 분석
    Step 2 (병렬): SWOT · 면접 Q&A (LLM) + 레이더 · 테마 · 리스크 (휴리스틱)
    """
    # Step 1: 기사 검색 + 자소서 분석 (병렬)
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_articles = ex.submit(news_service.get_articles, request.company)
        f_resume = ex.submit(llm_service.analyze_resume, request.resume)
        articles = f_articles.result()
        resume_raw = f_resume.result()

    if not articles:
        articles = news_service.get_articles(request.industry)

    resume_analysis = ResumeAnalysis(
        skills=resume_raw.get("skills") or [],
        experience_keywords=resume_raw.get("experience_keywords") or [],
        target_role=resume_raw.get("target_role"),
        strengths=resume_raw.get("strengths") or [],
        search_keywords=resume_raw.get("search_keywords") or [],
    )

    # 자소서 원문에 구조화된 요약을 prefix로 추가해 면접 질문 품질 향상
    resume_context = (
        f"[분석 요약] 스킬: {', '.join(resume_analysis.skills[:5])} | "
        f"강점: {', '.join(resume_analysis.strengths[:3])} | "
        f"희망 직무: {resume_analysis.target_role or '미정'}\n\n"
        f"{request.resume}"
    )

    # Step 2: LLM + 휴리스틱 분석 병렬 실행
    with ThreadPoolExecutor(max_workers=6) as ex:
        f_swot = ex.submit(llm_service.generate_swot_analysis, request.company, articles)
        f_qna = ex.submit(
            llm_service.generate_interview_questions,
            request.company, resume_context, articles,
        )
        f_radar = ex.submit(_score_five_dimensions, articles)
        f_themes = ex.submit(_extract_news_themes, articles)
        f_risks = ex.submit(_assess_risks, request.company, articles)
        f_info = ex.submit(_extract_company_info, request.company, articles)

        swot_dict = f_swot.result()
        qna_list = f_qna.result()
        radar = f_radar.result()
        themes = f_themes.result()
        risk = f_risks.result()
        info = f_info.result()

    return CompanyAnalysis(
        company=request.company,
        industry=request.industry,
        analysis_date=datetime.now(),
        company_info=info,
        radar_chart=radar,
        swot=SWOT(
            strengths=swot_dict.get("strengths", ""),
            weaknesses=swot_dict.get("weaknesses", ""),
            opportunities=swot_dict.get("opportunities", ""),
            threats=swot_dict.get("threats", ""),
        ),
        recent_news_themes=themes,
        interview_qna=[InterviewQNA(**q) for q in qna_list],
        risk_assessment=risk,
        news_sources=[
            CompanyNewsArticle(
                title=a.title,
                date=str(a.published_at or ""),
                source=a.source or "",
            )
            for a in articles[:5]
        ],
    )


@router.post("/company/upload", response_model=CompanyAnalysis)
async def analyze_company_with_resume_file(
    company: str = Form(..., description="지원 기업명 (예: 삼성전자)"),
    industry: str = Form(..., description="산업군 (예: 반도체)"),
    days_back: int = Form(default=365, ge=1, le=365),
    file: UploadFile = None,
    news_service: NewsService = Depends(get_news_service),
    llm_service: LLMService = Depends(get_llm_service),
) -> CompanyAnalysis:
    """자소서 파일(PDF/DOCX) + 기업 정보로 면접 준비 분석을 수행합니다.

    Postman: Body → form-data
      - company  (Text): 삼성전자
      - industry (Text): 반도체
      - file     (File): 자소서.pdf
    """
    from app.api.v1.endpoints.resume import _extract_text_from_docx, _extract_text_from_pdf

    if not (file and file.filename):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="자소서 파일이 필요합니다.",
        )

    data = await file.read()
    filename = file.filename or ""
    resume_text = (
        _extract_text_from_pdf(data)
        if filename.endswith(".pdf") or file.content_type == "application/pdf"
        else _extract_text_from_docx(data)
    ).strip()

    if not resume_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="자소서 파일에서 텍스트를 추출할 수 없습니다.",
        )

    return analyze_company(
        CompanyAnalysisRequest(
            company=company,
            industry=industry,
            resume=resume_text,
            days_back=days_back,
        ),
        news_service=news_service,
        llm_service=llm_service,
    )


@router.post("/industry/stream")
def stream_industry_analysis(
    request: IndustryAnalysisRequest,
    news_service: NewsService = Depends(get_news_service),
    llm_service: LLMService = Depends(get_llm_service),
) -> StreamingResponse:
    """산업 트렌드 분석 — SSE 스트리밍.

    응답 형식 (text/event-stream):
        data: {"type": "status", "articles": N}\\n\\n
        data: {"type": "chunk",  "text": "..."}\\n\\n  (반복)
        data: {"type": "done"}\\n\\n
    """
    def event_stream():
        articles = news_service.get_articles(request.industry)
        yield f"data: {json.dumps({'type': 'status', 'articles': len(articles)})}\n\n"
        for chunk in llm_service.stream_industry_trends(articles, request.industry):
            yield f"data: {json.dumps({'type': 'chunk', 'text': chunk})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/company/stream")
def stream_company_swot(
    request: CompanyAnalysisRequest,
    news_service: NewsService = Depends(get_news_service),
    llm_service: LLMService = Depends(get_llm_service),
) -> StreamingResponse:
    """기업 SWOT 분석 — SSE 스트리밍.

    응답 형식 (text/event-stream):
        data: {"type": "status", "articles": N}\\n\\n
        data: {"type": "chunk",  "text": "..."}\\n\\n  (반복)
        data: {"type": "done"}\\n\\n
    """
    def event_stream():
        articles = news_service.get_articles(request.company)
        yield f"data: {json.dumps({'type': 'status', 'articles': len(articles)})}\n\n"
        for chunk in llm_service.stream_swot(request.company, articles):
            yield f"data: {json.dumps({'type': 'chunk', 'text': chunk})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
