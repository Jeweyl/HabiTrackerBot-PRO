"""Application configuration loaded from environment variables.

Configuration source priority (highest to lowest):
    1. Process environment variables (Railway, docker, shell)
    2. ``.env.prod`` file (if exists)
    3. ``.env`` file (if exists)
"""

import os
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Detect available env files (for diagnostics + pydantic)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PROD = _PROJECT_ROOT / ".env.prod"
_ENV_LOCAL = _PROJECT_ROOT / ".env"

_env_file: str | None = None
if _ENV_PROD.exists():
    _env_file = ".env.prod"
elif _ENV_LOCAL.exists():
    _env_file = ".env"

# Print diagnostics at import time (names only, no values)
print("[config] env file detection:")
print(f"  .env.prod exists: {_ENV_PROD.exists()}")
print(f"  .env exists:      {_ENV_LOCAL.exists()}")
print(f"  using env_file:   {_env_file or 'none (process env only)'}")
print(f"  BOT_TOKEN in env:    {bool(os.getenv('BOT_TOKEN'))}")
print(f"  DATABASE_URL in env: {bool(os.getenv('DATABASE_URL'))}")
print(f"  REDIS_URL in env:    {bool(os.getenv('REDIS_URL'))}")

_PLACEHOLDERS = {
    "your_bot_token_here",
    "your_production_bot_token_here",
    "your_secure_password",
    "your_router_api_key_here",
    "change_me",
    "xxx",
    "",
}


def _is_placeholder(value: str) -> bool:
    """Return True if value is empty or a known placeholder."""
    v = value.strip().lower()
    if v in _PLACEHOLDERS:
        return True
    return v.startswith("your_") or v.startswith("change")


class Settings(BaseSettings):
    """Application settings loaded from env vars and/or .env file.

    Attributes:
        BOT_TOKEN: Telegram bot token from @BotFather.
        DATABASE_URL: Async PostgreSQL connection string (asyncpg driver).
        REDIS_URL: Redis connection string.
        ADMIN_ID: Telegram user ID of the bot administrator (0 = disabled).
        ROUTER_API_KEY: API key for OpenRouter AI service.
        AI_MODEL: AI model identifier (default: "deepseek/deepseek-v4-flash").
        AI_FALLBACK_MODEL: Fallback model when primary returns empty (default:
            "meta-llama/llama-3.1-8b-instruct").
        AI_TIMEOUT: OpenRouter HTTP timeout in seconds (default: 30).
        BOT_HTTP_TIMEOUT: Telegram Bot API HTTP timeout in seconds (default: 10).
        DB_POOL_SIZE: SQLAlchemy async connection pool size (default: 5).
        REMINDER_POLL_SECONDS: Reminder loop interval in seconds (default: 300).
        BOT_PUBLIC_URL: Public t.me link to this bot (optional, for onboarding).
        CHANNEL_URL: Public channel URL (optional, for onboarding).
        ORIGINAL_BOT_USERNAME: Original bot username without @ (optional).
        API_JWT_SECRET: HMAC secret for dashboard JWT (dev default ok for tests).
        API_JWT_EXPIRE_MINUTES: Access token lifetime in minutes (default 60).
        API_OTT_TTL_SECONDS: One-time dashboard token TTL in Redis (default 60).
        API_CORS_ORIGINS: Comma-separated CORS origins; empty = allow all.
        API_HOST: Uvicorn bind host for the stats API (default 0.0.0.0).
        API_PORT: Uvicorn bind port for the stats API (default 8000).
        DASHBOARD_PUBLIC_URL: Public base URL of the Vue dashboard (optional).
    """

    BOT_TOKEN: str = ""
    DATABASE_URL: str = ""
    REDIS_URL: str = ""
    ADMIN_ID: int = 0
    ROUTER_API_KEY: str = ""
    AI_MODEL: str = "deepseek/deepseek-v4-flash"
    AI_FALLBACK_MODEL: str = "meta-llama/llama-3.1-8b-instruct"
    AI_TIMEOUT: int = 30
    BOT_HTTP_TIMEOUT: int = 10
    DB_POOL_SIZE: int = 5
    REMINDER_POLL_SECONDS: int = 300
    BOT_PUBLIC_URL: str = ""
    CHANNEL_URL: str = ""
    ORIGINAL_BOT_USERNAME: str = ""
    API_JWT_SECRET: str = "dev-api-jwt-secret-change-me-32b!"

    API_JWT_EXPIRE_MINUTES: int = 60
    API_OTT_TTL_SECONDS: int = 60
    API_CORS_ORIGINS: str = ""
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    DASHBOARD_PUBLIC_URL: str = ""

    model_config = SettingsConfigDict(
        env_file=_env_file,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("BOT_TOKEN")
    @classmethod
    def validate_bot_token(cls, v: str) -> str:
        """Strip whitespace and validate Telegram bot token format.

        Rejects empty values, newlines, placeholders, and missing colon.
        """
        v = v.strip()
        if _is_placeholder(v):
            raise ValueError(
                "BOT_TOKEN is not set or is a placeholder. "
                "Set a real token from @BotFather via environment variable "
                "or .env / .env.prod file."
            )
        if "\n" in v or "\r" in v:
            raise ValueError(
                "BOT_TOKEN contains newline characters. "
                "Re-copy the token from @BotFather without trailing newlines."
            )
        if ":" not in v:
            raise ValueError(
                f"BOT_TOKEN format is invalid (no ':' found). " f"Got: {v[:10]}..."
            )
        return v

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def fallback_database_url(cls, v: str) -> str:
        """Fall back to ``DATABASE_PUBLIC_URL`` / ``POSTGRES_URL`` if empty.

        Auto-converts ``postgresql://`` to ``postgresql+asyncpg://``.
        Rejects placeholder values.
        """
        if isinstance(v, str):
            v = v.strip()
        if not v or _is_placeholder(v):
            import os

            v = (
                os.getenv("DATABASE_PUBLIC_URL") or os.getenv("POSTGRES_URL") or ""
            ).strip()
        if _is_placeholder(v):
            raise ValueError(
                "DATABASE_URL is not set or is a placeholder. "
                "Set a real PostgreSQL connection URL via environment variable "
                "or .env / .env.prod file."
            )
        if v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @field_validator("REDIS_URL", mode="before")
    @classmethod
    def fallback_redis_url(cls, v: str) -> str:
        """Fall back to ``REDIS_PUBLIC_URL`` if empty (Railway compatibility).

        Rejects placeholder values.
        """
        if isinstance(v, str):
            v = v.strip()
        if not v or _is_placeholder(v):
            import os

            v = (os.getenv("REDIS_PUBLIC_URL") or "").strip()
        if _is_placeholder(v):
            raise ValueError(
                "REDIS_URL is not set or is a placeholder. "
                "Set a real Redis connection URL via environment variable "
                "or .env / .env.prod file."
            )
        return v


settings = Settings()
