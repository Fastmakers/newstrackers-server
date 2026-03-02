from fastapi import APIRouter

from app.api.v1.endpoints import analysis, health, resume, search

api_router = APIRouter()

api_router.include_router(health.router, tags=["health"])
api_router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
api_router.include_router(resume.router, prefix="/resume", tags=["resume"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
