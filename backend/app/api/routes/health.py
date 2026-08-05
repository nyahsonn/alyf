"""Health and readiness endpoints."""

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import SessionDep
from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness: does the API process respond at all?"""
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}


@router.get("/health/db")
async def health_db(session: SessionDep) -> dict[str, object]:
    """Readiness: can we reach PostgreSQL, and is pgvector installed?"""
    await session.execute(text("SELECT 1"))
    result = await session.execute(
        text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    )
    version = result.scalar_one_or_none()
    return {
        "status": "ok",
        "database": "connected",
        "pgvector": version or "not installed",
        "embedding_dimensions": settings.embedding_dimensions,
    }
