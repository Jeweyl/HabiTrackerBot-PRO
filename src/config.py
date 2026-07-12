"""Application configuration loaded from environment variables."""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from .env file and environment variables.

    Attributes:
        BOT_TOKEN: Telegram bot token from @BotFather.
        DATABASE_URL: Async PostgreSQL connection string (asyncpg driver).
        REDIS_URL: Redis connection string.
        ADMIN_ID: Telegram user ID of the bot administrator (0 = disabled).
        ROUTER_API_KEY: API key for OpenRouter AI service.
        AI_MODEL: AI model identifier (default: "deepseek/deepseek-v4-flash").
        AI_FALLBACK_MODEL: Fallback model when primary returns empty (default:
            "meta-llama/llama-3.1-8b-instruct").
    """

    BOT_TOKEN: str = ""
    DATABASE_URL: str = ""
    REDIS_URL: str = ""
    ADMIN_ID: int = 0
    ROUTER_API_KEY: str = ""
    AI_MODEL: str = "deepseek/deepseek-v4-flash"
    AI_FALLBACK_MODEL: str = "meta-llama/llama-3.1-8b-instruct"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("BOT_TOKEN")
    @classmethod
    def validate_bot_token(cls, v: str) -> str:
        """Strip whitespace and validate Telegram bot token format.

        Token must be non-empty, contain a colon, and have no newlines.
        """
        v = v.strip()
        if not v:
            raise ValueError(
                "BOT_TOKEN is not set. "
                "Provide it via environment variable or .env file."
            )
        if "\n" in v or "\r" in v:
            raise ValueError(
                "BOT_TOKEN contains newline characters. "
                "Re-copy the token from @BotFather without trailing newlines."
            )
        if ":" not in v:
            raise ValueError(
                f"BOT_TOKEN format is invalid (no ':' found). "
                f"Got: {v[:10]}..."
            )
        return v

    @field_validator("DATABASE_URL")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        """Auto-convert ``postgresql://`` to ``postgresql+asyncpg://``.

        Railway provides ``postgresql://`` by default, but SQLAlchemy async
        engine requires the ``+asyncpg`` driver suffix.
        """
        v = v.strip()
        if v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v


settings = Settings()
