"""Unit tests for application configuration defaults (src/config.py)."""

from src.config import Settings


def test_ai_timeout_default() -> None:
    """AI_TIMEOUT must default to 30 seconds."""
    assert Settings.model_fields["AI_TIMEOUT"].default == 30


def test_reminder_poll_seconds_default() -> None:
    """REMINDER_POLL_SECONDS must default to 300 seconds (5 minutes)."""
    assert Settings.model_fields["REMINDER_POLL_SECONDS"].default == 300


def test_db_pool_size_default() -> None:
    """DB_POOL_SIZE must default to 5 (current hardcode)."""
    assert Settings.model_fields["DB_POOL_SIZE"].default == 5


def test_bot_http_timeout_default() -> None:
    """BOT_HTTP_TIMEOUT must default to 10 seconds (Telegram API)."""
    assert Settings.model_fields["BOT_HTTP_TIMEOUT"].default == 10


def test_bot_public_url_default_empty() -> None:
    """BOT_PUBLIC_URL must default to empty string (optional onboarding link)."""
    assert Settings.model_fields["BOT_PUBLIC_URL"].default == ""


def test_channel_url_default_empty() -> None:
    """CHANNEL_URL must default to empty string (optional onboarding link)."""
    assert Settings.model_fields["CHANNEL_URL"].default == ""


def test_original_bot_username_default_empty() -> None:
    """ORIGINAL_BOT_USERNAME must default to empty string (optional)."""
    assert Settings.model_fields["ORIGINAL_BOT_USERNAME"].default == ""


def test_api_jwt_expire_minutes_default() -> None:
    """API_JWT_EXPIRE_MINUTES must default to 60."""
    assert Settings.model_fields["API_JWT_EXPIRE_MINUTES"].default == 60


def test_api_ott_ttl_seconds_default() -> None:
    """API_OTT_TTL_SECONDS must default to 60."""
    assert Settings.model_fields["API_OTT_TTL_SECONDS"].default == 60


def test_api_port_default() -> None:
    """API_PORT must default to 8000."""
    assert Settings.model_fields["API_PORT"].default == 8000



