from fastapi import APIRouter

from app.api.v1.endpoints import analysis, news

api_router = APIRouter()

api_router.include_router(news.router, prefix="/news", tags=["news"])
api_router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
