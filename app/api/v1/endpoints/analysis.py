"""Analysis endpoints."""

import json

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from fastapi.responses import PlainTextResponse, StreamingResponse

from app.analysis.company_analyzer import CompanyAnalyzer
from app.analysis.industry_analyzer import IndustryAnalyzer
from app.core.dependencies import (
    get_company_analyzer,
    get_industry_analyzer,
    get_llm_service,
    get_news_service,
)
from app.schemas.data_models import (
    CompanyAnalysis,
    CompanyAnalysisRequest,
    IndustryAnalysisRequest,
    IndustryData,
)
from app.services.llm_service import LLMService
from app.services.news_service import NewsService

router = APIRouter()


@router.post("/industry", response_model=IndustryData)
def analyze_industry(
    request: IndustryAnalysisRequest,
    analyzer: IndustryAnalyzer = Depends(get_industry_analyzer),
) -> IndustryData:
    """Run industry analysis."""
    try:
        return analyzer.analyze(industry=request.industry, days_back=request.days_back)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="External service unavailable",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Industry analysis failed",
        ) from exc


@router.post("/company", response_model=CompanyAnalysis)
def analyze_company(
    request: CompanyAnalysisRequest,
    analyzer: CompanyAnalyzer = Depends(get_company_analyzer),
) -> CompanyAnalysis:
    """Run company interview analysis."""
    try:
        return analyzer.analyze(
            company=request.company,
            industry=request.industry,
            resume=request.resume,
            days_back=request.days_back,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="External service unavailable",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Company analysis failed",
        ) from exc


@router.post("/company/upload", response_model=CompanyAnalysis)
async def analyze_company_with_resume_file(
    company: str = Form(..., description="지원 기업명 (예: 삼성전자)"),
    industry: str = Form(..., description="산업군 (예: 반도체)"),
    days_back: int = Form(default=365, ge=1, le=365),
    file: UploadFile = None,
    analyzer: CompanyAnalyzer = Depends(get_company_analyzer),
) -> CompanyAnalysis:
    """PDF 또는 DOCX 자소서 파일 + 기업/산업 정보를 한 번에 받아 기업 분석을 수행합니다.

    Postman: Body → form-data
      - company  (Text): 삼성전자
      - industry (Text): 반도체
      - file     (File): 자소서.pdf
    """
    from app.api.v1.endpoints.resume import _extract_text_from_docx, _extract_text_from_pdf

    resume_text = ""
    if file and file.filename:
        data = await file.read()
        filename = file.filename or ""
        if filename.endswith(".pdf") or file.content_type == "application/pdf":
            resume_text = _extract_text_from_pdf(data).strip()
        else:
            resume_text = _extract_text_from_docx(data).strip()

    if not resume_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="자소서 파일에서 텍스트를 추출할 수 없습니다.",
        )

    try:
        return analyzer.analyze(
            company=company,
            industry=industry,
            resume=resume_text,
            days_back=days_back,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Company analysis failed",
        ) from exc


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
        articles = news_service.get_articles(
            request.industry, category_l2=None, limit=100
        )
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
        articles = news_service.get_articles(
            request.company, category_l2=None, limit=100
        )
        yield f"data: {json.dumps({'type': 'status', 'articles': len(articles)})}\n\n"

        for chunk in llm_service.stream_swot(request.company, articles):
            yield f"data: {json.dumps({'type': 'chunk', 'text': chunk})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/graph/industry", response_class=PlainTextResponse)
def get_industry_graph() -> str:
    """Return Mermaid diagram of the industry analysis graph.

    Uses stub services — no API key required, graph structure is static.
    """
    from app.agents.graphs.industry_graph import build_industry_graph
    graph = build_industry_graph(news_service=object(), llm_service=object())
    return graph.get_graph().draw_mermaid()


@router.get("/graph/company", response_class=PlainTextResponse)
def get_company_graph() -> str:
    """Return Mermaid diagram of the company analysis graph.

    Uses stub services — no API key required, graph structure is static.
    """
    from app.agents.graphs.company_graph import build_company_graph
    graph = build_company_graph(news_service=object(), llm_service=object())
    return graph.get_graph().draw_mermaid()
