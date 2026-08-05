"""Aggregates every module's routes into one router mounted under /api/v1."""

from fastapi import APIRouter

from app.api.routes import extraction, health, ingestion, reasoning, reports

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(ingestion.router)
api_router.include_router(extraction.router)
api_router.include_router(reasoning.router)
api_router.include_router(reports.router)
