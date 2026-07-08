"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from .env file and environment variables.

    Attributes:
        BOT_TOKEN: Telegram bot token from @BotFather.
        DATABASE_URL: Async PostgreSQL connection string (asyncpg driver).
        REDIS_URL: Redis connection string.
        ADMIN_ID: Telegram user ID of the bot administrator.
        OPENROUTER_API_KEY: API key for OpenRouter AI service.
        AI_MODEL: AI model identifier (default: "google/gemini-1.5-flash").
    """

    BOT_TOKEN: str
    DATABASE_URL: str
    REDIS_URL: str
    ADMIN_ID: int
    OPENROUTER_API_KEY: str = ""
    AI_MODEL: str = "google/gemini-1.5-flash"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
