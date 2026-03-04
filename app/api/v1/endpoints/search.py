"""RAG 파이프라인 검색 엔드포인트.

파이프라인 버전:
    V1 (Baseline):  [자소서 + 기업 + 직무] → 벡터 검색 Top 5 → Claude 답변
    V2 (Hybrid):    [자소서 + 기업 + 직무] → Haiku 질의변환 → Hybrid(Vector 100 + BM25 100 → RRF Top 5) → Claude 답변
    V3 (Reranker):  V2 동일 (RRF Top 20) → Cross-Encoder Top 5 → Claude 답변

실험 결과는 logs/experiment.jsonl에 자동 저장됨.

POST /api/v1/search
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.dependencies import get_llm_service, get_news_service
from app.schemas.data_models import (
    LatencyBreakdown,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from app.services.llm_service import LLMService
from app.services.news_service import NewsService, _V3_RERANK_POOL

logger = logging.getLogger(__name__)
router = APIRouter()

_EXPERIMENT_LOG = Path("logs/experiment.jsonl")


def _ms(start: float) -> float:
    return round((time.time() - start) * 1000, 1)


def _log_experiment(record: dict) -> None:
    """실험 결과를 JSONL 파일에 한 줄 추가."""
    try:
        _EXPERIMENT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _EXPERIMENT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.warning("실험 로그 저장 실패: %s", exc)


@router.post("", response_model=SearchResponse)
def search_news(
    request: SearchRequest,
    news_service: NewsService = Depends(get_news_service),
    llm_service: LLMService = Depends(get_llm_service),
) -> SearchResponse:
    """RAG 파이프라인으로 관련 뉴스를 검색하고 Claude 답변을 생성합니다.

    - `pipeline=v1`: 자소서 원문 → 벡터 검색 (하한선)
    - `pipeline=v2`: 자소서 원문 → Haiku 질의변환 → Hybrid 검색 (권장)
    - `pipeline=v3`: v2 + Cross-Encoder 재배열 (최고 정밀도)

    각 단계 소요 시간은 `latency` 필드에서 확인할 수 있습니다.
    실험 결과는 logs/experiment.jsonl에 자동 저장됩니다.
    """
    t_total = time.time()

    # 모든 파이프라인 공통 입력: [자소서 + 기업 + 직무]
    # V1: 그대로 임베딩, V2/V3: Haiku가 압축 쿼리로 변환
    transform_input = f"지원 기업: {request.company}\n지원 직군: {request.position}\n\n{request.resume}"

    # ── Step 1. 질의 변환 (V2/V3 전용) ────────────────────────────────────────
    transformed_query: str = ""
    keywords: list[str] = []
    transform_ms: float | None = None

    if request.pipeline in ("v2", "v3"):
        t0 = time.time()
        try:
            result = llm_service.transform_query(transform_input)
            transformed_query = result.get("query") or transform_input
            keywords = result.get("keywords") or []
            logger.info("쿼리 변환 완료: '%s'", transformed_query[:60])
        except Exception as exc:
            logger.warning("쿼리 변환 실패 (원문 사용): %s", exc)
            transformed_query = transform_input
        transform_ms = _ms(t0)

    # ── Step 2. 검색 ──────────────────────────────────────────────────────────
    t0 = time.time()
    rerank_ms: float | None = None

    try:
        if request.pipeline == "v1":
            chunks = news_service.vector_search(
                query=transform_input,
                company=request.company,
                top_k=request.top_k,
            )
        elif request.pipeline == "v2":
            chunks = news_service.hybrid_search(
                query=transformed_query,
                keyword_query=" ".join(k for k in ([request.company] + keywords[:1]) if k) or request.company,
                top_k=request.top_k,
            )
        else:  # v3
            chunks = news_service.hybrid_search(
                query=transformed_query,
                keyword_query=" ".join(k for k in ([request.company] + keywords[:1]) if k) or request.company,
                top_k=_V3_RERANK_POOL,
            )
    except Exception as exc:
        logger.error("검색 실패 (pipeline=%s): %s", request.pipeline, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="검색 서비스에 일시적인 오류가 발생했습니다.",
        ) from exc

    retrieval_ms = _ms(t0)

    # ── Step 3. Cross-Encoder 재배열 (V3 전용) ────────────────────────────────
    if request.pipeline == "v3" and chunks:
        t0 = time.time()
        try:
            chunks = news_service.rerank_chunks(
                query=f"{request.company} 관련: {transformed_query}",
                chunks=chunks,
                top_k=request.top_k,
            )
        except Exception as exc:
            logger.warning("Reranker 실패 (RRF 결과 사용): %s", exc)
            chunks = chunks[:request.top_k]
        rerank_ms = _ms(t0)

    # ── Step 4. 답변 생성 (Claude Sonnet) ────────────────────────────────────
    answer: str | None = None
    answer_ms: float | None = None
    if not request.skip_answer:
        t0 = time.time()
        try:
            answer = llm_service.generate_rag_answer(
                query=transformed_query,
                chunks=chunks,
                resume=request.resume,
                company=request.company,
                position=request.position,
            )
        except Exception as exc:
            logger.error("답변 생성 실패: %s", exc)
        answer_ms = _ms(t0)

    # ── Step 5. 응답 조립 ─────────────────────────────────────────────────────
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
    latency = LatencyBreakdown(
        query_transform_ms=transform_ms,
        retrieval_ms=retrieval_ms,
        rerank_ms=rerank_ms,
        answer_ms=answer_ms,
        total_ms=total_ms,
    )

    # ── Step 6. 실험 로그 저장 ────────────────────────────────────────────────
    _log_experiment({
        "timestamp": datetime.now().isoformat(),
        "pipeline": request.pipeline,
        "company": request.company,
        "position": request.position,
        "resume_preview": request.resume[:100],
        "top_k": request.top_k,
        "num_results": len(results),
        "transformed_query": transformed_query or None,
        "keywords": keywords,
        "latency": {
            "query_transform_ms": transform_ms,
            "retrieval_ms": retrieval_ms,
            "rerank_ms": rerank_ms,
            "answer_ms": answer_ms,
            "total_ms": total_ms,
        },
        "answer_preview": answer[:200] if answer else None,
    })

    return SearchResponse(
        pipeline=request.pipeline,
        transformed_query=transformed_query if transformed_query != request.resume else None,
        keywords=keywords,
        results=results,
        total_results=len(results),
        answer=answer,
        latency=latency,
    )
