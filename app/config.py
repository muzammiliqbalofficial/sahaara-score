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

    # ── CORS ────────────────────────────────────────────────────────────────
    # Comma-separated origins allowed to call the API.  In production this
    # comes from the CORS_ORIGINS env var (e.g. "https://app.vercel.app").
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # ── Database tuning ─────────────────────────────────────────────────────
    sql_echo: bool = False  # Log every SQL statement (dev only)

    # ── Scoring ─────────────────────────────────────────────────────────────
    # The minimum number of non-null feature values required before the
    # ML model is trusted.  Below this threshold the rule-based fallback fires.
    min_model_data_points: int = 6

    # Semantic version stamped on every assessment produced by the current
    # model artefact.  Bump when retraining.
    model_version: str = "0.1.0"

    # ── Alibaba Cloud Model Studio (Qwen-VL document parsing) ──────────────
    # DashScope API key from https://bailian.console.aliyun.com/.  When the
    # key is empty (or the API call fails), the document parser falls back to
    # deterministic mock extraction so demos work offline without spending
    # API quota — every response reports which mode produced it.
    dashscope_api_key: str = ""
    alibaba_qwen_model: str = "qwen-vl-max"


@lru_cache
def get_settings() -> Settings:
    """Cached singleton so every module reads the same config."""
    return Settings()
