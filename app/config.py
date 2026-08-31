"""
Application configuration via pydantic-settings.

All settings are read from environment variables (or a .env file) and validated
at startup. This keeps secrets out of code and makes the app trivially
deployable across environments.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the Sahaara Score platform."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ────────────────────────────────────────────────────────────
    # Default is a placeholder — the real URL comes from .env.
    database_url: str = (
        "postgresql+psycopg://user:pass@localhost:5432/sahaara_score"
    )

    # ── Application ─────────────────────────────────────────────────────────
    app_env: str = "development"
    app_debug: bool = True
    app_secret_key: str = "change-me-in-production"

    # ── Scoring ─────────────────────────────────────────────────────────────
    # The minimum number of non-null feature values required before the
    # ML model is trusted.  Below this threshold the rule-based fallback fires.
    min_model_data_points: int = 6

    # Semantic version stamped on every assessment produced by the current
    # model artefact.  Bump when retraining.
    model_version: str = "0.1.0"


@lru_cache
def get_settings() -> Settings:
    """Cached singleton so every module reads the same config."""
    return Settings()
