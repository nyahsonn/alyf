"""ALYF API entrypoint.

Run locally with:  uvicorn app.main:app --reload --port 8000
Interactive docs:  http://localhost:8000/docs
"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import sentry_sdk
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

if settings.sentry_dsn:
    # No traces_sample_rate -- this is error monitoring, not performance
    # tracing, so nothing is sampled/dropped: every exception reported via
    # sentry_sdk.capture_exception (see extraction.py, ingestion.py) is
    # sent. FastAPI/Starlette integrations are auto-enabled by sentry_sdk
    # whenever it detects those packages installed, so unhandled exceptions
    # anywhere in a request are also captured with no extra code here.
    sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment)


def _write_google_credentials_file() -> None:
    """Write GOOGLE_CREDENTIALS_JSON out to the path GOOGLE_APPLICATION_CREDENTIALS
    points at, for platforms (Railway) that only offer environment variables,
    not a real file on disk, for the service account key. A no-op if either is
    unset -- local dev, and any deployment that already has a real key file
    mounted, are untouched. Runs on every startup, since platforms like Railway
    give each deploy/restart a fresh, empty filesystem -- a file written by a
    one-off manual step would silently disappear on the next restart.
    """
    if not settings.google_credentials_json:
        return
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not path:
        return
    Path(path).write_text(settings.google_credentials_json)
    logger.info("Wrote Google service account credentials to %s", path)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Set up the schema on startup, close the connection pool on shutdown."""
    _write_google_credentials_file()
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
