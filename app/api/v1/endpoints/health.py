"""Health check endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health_check() -> dict:
    """Liveness endpoint for API v1."""
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}
