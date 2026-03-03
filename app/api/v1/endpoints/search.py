"""RAG 파이프라인 검색 엔드포인트.

파이프라인 버전:
    V1 (Baseline):  자소서 원문 → 벡터 검색 Top 5 → Claude 답변
    V2 (Hybrid):    자소서 원문 → Haiku 질의변환 → Hybrid(Vector+trgm→RRF) Top 5 → Claude 답변
    V3 (Reranker):  V2 동일 (RRF Top 20) → Cross-Encoder → Top 5 → Claude 답변

POST /api/v1/search
"""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.dependencies import get_llm_service, get_news_service
from app.schemas.data_models import (
    LatencyBreakdown,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from app.services.llm_service import LLMService
from app.services.news_service import NewsService

logger = logging.getLogger(__name__)
router = APIRouter()


def _ms(start: float) -> float:
    return round((time.time() - start) * 1000, 1)


@router.post("", response_model=SearchResponse)
def search_news(
    request: SearchRequest,
    news_service: NewsService = Depends(get_news_service),
    llm_service: LLMService = Depends(get_llm_service),
) -> SearchResponse:
    """RAG 파이프라인으로 관련 뉴스를 검색하고 Claude 답변을 생성합니다.

    - `pipeline=v1`: 가장 단순한 벡터 검색 (하한선 기준)
    - `pipeline=v2`: Haiku 질의변환 + Hybrid 검색 (권장)
    - `pipeline=v3`: v2 + Cross-Encoder 재배열 (최고 정밀도)

    각 단계 소요 시간은 `latency` 필드에서 확인할 수 있습니다.
    """
    t_total = time.time()

    # ── Step 1. 질의 변환 (V2/V3 전용) ────────────────────────────────────────
    transformed_query = request.query
    keywords: list[str] = []
    transform_ms: float | None = None

    if request.pipeline in ("v2", "v3") and len(request.query) > 30:
        t0 = time.time()
        try:
            result = llm_service.transform_query(request.query)
            transformed_query = result.get("query") or request.query
            keywords = result.get("keywords") or []
            logger.info(
                "쿼리 변환 완료: '%s...' → '%s'",
                request.query[:30],
                transformed_query[:60],
            )
        except Exception as exc:
            logger.warning("쿼리 변환 실패 (원문 사용): %s", exc)
        transform_ms = _ms(t0)

    # ── Step 2. 검색 ──────────────────────────────────────────────────────────
    t0 = time.time()
    try:
        if request.pipeline == "v1":
            chunks = news_service.vector_search(
                query=request.query,
                category_l2=request.category_l2,
                top_k=request.top_k,
            )
        elif request.pipeline == "v2":
            chunks = news_service.hybrid_search(
                query=transformed_query,
                category_l2=request.category_l2,
                top_k=request.top_k,
                use_reranker=False,
            )
        else:  # v3
            chunks = news_service.hybrid_search(
                query=transformed_query,
                category_l2=request.category_l2,
                top_k=request.top_k,
                use_reranker=True,
            )
    except Exception as exc:
        logger.error("검색 실패 (pipeline=%s): %s", request.pipeline, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="검색 서비스에 일시적인 오류가 발생했습니다.",
        ) from exc

    retrieval_ms = _ms(t0)

    # V3 Reranker 소요 시간은 hybrid_search 내부에서 처리되므로
    # retrieval_ms에 포함됨. 별도 측정이 필요하면 NewsService 시그니처 확장 필요.
    rerank_ms: float | None = None

    # ── Step 3. 답변 생성 (Claude Sonnet) ────────────────────────────────────
    t0 = time.time()
    try:
        answer = llm_service.generate_rag_answer(request.query, chunks)
    except Exception as exc:
        logger.error("답변 생성 실패: %s", exc)
        answer = None
    answer_ms = _ms(t0)

    # ── Step 4. 응답 조립 ─────────────────────────────────────────────────────
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

    total_ms = _ms(t_total)

    return SearchResponse(
        pipeline=request.pipeline,
        original_query=request.query,
        transformed_query=transformed_query if transformed_query != request.query else None,
        keywords=keywords,
        results=results,
        total_results=len(results),
        answer=answer,
        latency=LatencyBreakdown(
            query_transform_ms=transform_ms,
            retrieval_ms=retrieval_ms,
            rerank_ms=rerank_ms,
            answer_ms=answer_ms,
            total_ms=total_ms,
        ),
    )
