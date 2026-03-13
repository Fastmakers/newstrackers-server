from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.dependencies import get_worker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_directories()
    worker = None
    logger.info("FastAPI lifespan started run_worker_in_api=%s", settings.RUN_WORKER_IN_API)
    if settings.RUN_WORKER_IN_API:
        worker = get_worker()
        await worker.start()
    yield
    if worker:
        await worker.stop()
    logger.info("FastAPI lifespan stopped")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=settings.DESCRIPTION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=bool(settings.ALLOWED_ORIGINS),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
def root_health_check():
    return {"status": "healthy"}
