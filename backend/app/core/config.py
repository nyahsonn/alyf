"""Application settings, loaded from environment variables / backend/.env."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ALYF API"
    environment: str = "local"
    debug: bool = True
    api_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://alyf:alyf@localhost:5432/alyf"

    # Dimension of vectors stored in the `facts.embedding` column.
    embedding_dimensions: int = 384

    # Stored as a comma-separated string so it is easy to set in a .env file.
    cors_origins: str = "http://localhost:3000"

    # Ingestion tuning: chunk size and overlap are measured in words.
    chunk_size_words: int = 180
    chunk_overlap_words: int = 30

    # Claude API key used by app/extraction/home_inspection.py and
    # action_plan.py. Read from backend/.env like everything else above; falls
    # back to a real ANTHROPIC_API_KEY environment variable if unset here (see
    # those modules' `anthropic.Anthropic(api_key=...)` calls).
    anthropic_api_key: str = ""

    # Google Document AI, used by app/ingestion/ocr.py to read PDFs. The
    # pipeline never calls it on its own. GOOGLE_APPLICATION_CREDENTIALS is
    # deliberately not listed: the Google auth library reads that from the real
    # environment, not from this file.
    docai_project_id: str = ""
    docai_location: str = "us"
    docai_processor_id: str = ""

    # Alternative to a real GOOGLE_APPLICATION_CREDENTIALS file on disk, for
    # platforms that only offer environment variables (e.g. Railway) --
    # the service account key's JSON content, written to the path
    # GOOGLE_APPLICATION_CREDENTIALS points at on startup (see main.py's
    # lifespan). Blank locally, where a real key file + a real
    # GOOGLE_APPLICATION_CREDENTIALS env var already work as documented above.
    google_credentials_json: str = ""

    # Cloud Storage bucket used as scratch space for PDFs over ONLINE_PAGE_LIMIT
    # pages, which go through Document AI's batch API instead (see ocr.py,
    # _process_batch). Only needed for those; left blank, batch requests fail
    # with a message that says so rather than the pipeline refusing to start.
    docai_gcs_bucket: str = ""

    # Resend (resend.com), used by app/notifications/emailer.py to send weekly
    # roadmap reminders (scripts/send_roadmap_reminders.py). The default
    # sender is Resend's own sandbox address -- works immediately with no
    # domain verification, fine until a custom domain is set up.
    resend_api_key: str = ""
    resend_from_email: str = "onboarding@resend.dev"

    # Base URL used to build links back into the report in reminder emails
    # (app/notifications/service.py). Not read from the browser, so this is
    # the deployed frontend's real URL in production, not NEXT_PUBLIC_API_URL.
    frontend_base_url: str = "http://localhost:3000"

    # How long a report can sit at status="pending_review" before
    # scripts/auto_send_pending_reports.py moves it to "auto_sent" on its
    # own, so a slow inspector doesn't block delivery to the buyer. Midpoint
    # of the 24-48h window the product calls for.
    auto_send_after_hours: int = 36

    # Inspector accounts (app/auth). jwt_secret gets the same treatment as
    # POSTGRES_PASSWORD's default elsewhere in this repo: a working local
    # value with no setup required, which MUST be overridden by a real
    # secret in any deployment that isn't a laptop -- anyone who has it can
    # mint a session for any inspector id. cookie_secure stays False for
    # local http:// dev; set True once served over https.
    jwt_secret: str = "dev-secret-change-me-in-any-real-deployment-32bytes"
    jwt_expires_days: int = 14
    auth_cookie_name: str = "alyf_session"
    cookie_secure: bool = False

    # Sign in with Google (app/auth/oauth.py). Left blank,
    # provider_configured() returns False and /auth/google/login responds
    # with a clear "not configured" error instead of redirecting to Google
    # with an empty client id. session_secret backs Starlette's
    # SessionMiddleware, used only for the transient state/nonce during the
    # OAuth redirect round-trip -- deliberately separate from jwt_secret,
    # which signs long-lived session cookies.
    session_secret: str = "dev-session-secret-change-me-in-any-real-deployment"
    backend_base_url: str = "http://localhost:8000"

    google_client_id: str = ""
    google_client_secret: str = ""

    # Error monitoring (https://sentry.io). Left blank, sentry_sdk is never
    # initialized -- the app runs exactly as it does today, just without
    # alerting. See app/main.py and README, "Error monitoring".
    sentry_dsn: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is only parsed once per process."""
    return Settings()


settings = get_settings()
