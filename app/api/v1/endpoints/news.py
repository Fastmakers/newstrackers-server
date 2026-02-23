from fastapi import APIRouter, Query

from app.services.vector_store import vector_store_service
from app.core.config import settings

router = APIRouter()


@router.get("/search")
async def search_news(
    query: str = Query(..., description="검색 쿼리"),
    industry: str | None = Query(None, description="산업군 필터"),
    limit: int = Query(10, ge=1, le=50, description="결과 개수"),
):
    """Vector DB에서 유사한 뉴스를 검색합니다."""
    results = await vector_store_service.search(
        query=query,
        job_category=industry,
        n_results=limit,
    )
    return {
        "query": query,
        "industry": industry,
        "count": len(results),
        "results": results,
    }


@router.get("/stats")
async def get_news_stats():
    """Vector DB 통계 정보를 반환합니다."""
    stats = await vector_store_service.get_stats()
    return {
        **stats,
        "industries": settings.INDUSTRY_KEYWORDS,
    }


@router.get("/industries")
async def get_industries():
    """설정된 산업군 목록을 반환합니다."""
    return {
        "industries": settings.INDUSTRY_KEYWORDS,
    }
