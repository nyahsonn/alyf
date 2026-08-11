"""ALYF API entrypoint.

Run locally with:  uvicorn app.main:app --reload --port 8000
Interactive docs:  http://localhost:8000/docs
"""

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.database import engine, init_db

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(name)s  %(message)s",
)
logger = logging.getLogger("alyf")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Set up the schema on startup, close the connection pool on shutdown."""
    try:
        await init_db()
        logger.info("Database ready (pgvector enabled, tables created if missing).")
    except Exception:
        logger.exception(
            "Could not reach the database at startup. Is `docker compose up -d` running, "
            "and does DATABASE_URL in backend/.env match your root .env?"
        )
        raise
    yield
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "ALYF backend — a modular monolith. Documents flow through four stages: "
        "ingestion → extraction → reasoning → reports."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Backs authlib's transient state/nonce during the Google OAuth redirect
# round-trip (app/auth/oauth.py, app/api/routes/auth.py) -- unrelated to
# and separate from our own long-lived alyf_session JWT cookie.
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)

app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "version": "0.1.0",
        "docs": "/docs",
        "api": settings.api_prefix,
    }
