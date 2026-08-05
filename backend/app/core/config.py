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

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is only parsed once per process."""
    return Settings()


settings = get_settings()
