"""
뉴스 하이브리드 검색 엔드포인트.

파이프라인:
    1. (선택) Claude Haiku로 질의 변환 → 핵심 키워드 + 압축 쿼리
    2. 벡터 검색 100건 + 키워드 검색 100건 (hybrid_search)
    3. RRF 융합 → top_k 반환
    [4. Cross-Encoder 리랭킹 — 미구현]

POST /api/v1/search
"""

import time
import logging
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.dependencies import get_news_service, get_llm_service
from app.schemas.data_models import SearchRequest, SearchResponse, SearchResult
from app.services.news_service import NewsService
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("", response_model=SearchResponse)
def search_news(
    request: SearchRequest,
    news_service: NewsService = Depends(get_news_service),
    llm_service: LLMService = Depends(get_llm_service),
) -> SearchResponse:
    """
    자소서·검색어 기반 관련 뉴스 청크 검색.

    - `transform_query=true`: Claude Haiku가 긴 자소서를 핵심 쿼리로 압축 후 검색
    - `transform_query=false`: 입력 텍스트를 그대로 검색어로 사용

    ### 응답 필드
    - `transformed_query`: 실제 검색에 사용된 쿼리 (변환 시)
    - `keywords`: 추출된 핵심 키워드
    - `results[].chunk_text`: 관련 뉴스 본문 발췌
    - `results[].rrf_score`: RRF 점수 (높을수록 관련도 높음)
    """
    start_time = time.time()

    # ── Step 1. 질의 변환 (선택적) ─────────────────────────────────────────
    transformed_query = request.query
    keywords: list[str] = []

    if request.transform_query and len(request.query) > 30:
        try:
            result = llm_service.transform_query(request.query)
            transformed_query = result.get("query") or request.query
            keywords = result.get("keywords") or []
            logger.info(
                "Query transformed: '%s...' → '%s'",
                request.query[:30],
                transformed_query[:60],
            )
        except Exception as exc:
            logger.warning("Query transformation skipped: %s", exc)

    # ── Step 2. 하이브리드 검색 (벡터 + ILIKE → RRF) ─────────────────────
    try:
        chunks = news_service.hybrid_search(
            query=transformed_query,
            category_l2=request.category_l2,
            top_k=request.top_k,
        )
    except Exception as exc:
        logger.error("hybrid_search failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="검색 서비스에 일시적인 오류가 발생했습니다.",
        ) from exc

    # ── Step 3. 응답 조립 ──────────────────────────────────────────────────
    results = [
        SearchResult(
            rank=i + 1,
            article_id=chunk.article_id,
            chunk_no=chunk.chunk_no,
            title=chunk.article.title if chunk.article else "",
            published_at=chunk.article.published_at if chunk.article else None,
            category_l2=chunk.article.category_l2 if chunk.article else None,
            chunk_text=chunk.chunk_text,
        )
        for i, chunk in enumerate(chunks)
    ]

    elapsed_ms = (time.time() - start_time) * 1000

    return SearchResponse(
        original_query=request.query,
        transformed_query=transformed_query if transformed_query != request.query else None,
        keywords=keywords,
        results=results,
        total_results=len(results),
        search_time_ms=round(elapsed_ms, 1),
    )
