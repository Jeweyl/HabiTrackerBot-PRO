"""Build one-time dashboard login links for Telegram users."""

from __future__ import annotations

import logging
from typing import Protocol
from urllib.parse import quote

from src.api.auth import create_ott
from src.api.token_store import TokenStore
from src.config import settings

logger = logging.getLogger(__name__)


class SupportsCreateOtt(Protocol):
    """Minimal store protocol used by :func:`issue_dashboard_link`."""

    async def set(self, key: str, value: str, ttl_seconds: int) -> None: ...


def normalize_dashboard_base_url(raw: str | None) -> str | None:
    """Return a clean public dashboard base URL, or ``None`` if unset.

    Empty / whitespace / placeholder values disable the dashboard button.
    Trailing slashes are stripped so callers can safely append paths.
    """
    if raw is None:
        return None
    base = str(raw).strip().rstrip("/")
    if not base:
        return None
    lowered = base.lower()
    if lowered in {"none", "null", "false", "0"}:
        return None
    return base


def build_login_url(base_url: str, token: str) -> str:
    """Compose ``{base}/login?token=...`` with a URL-encoded token."""
    safe_token = quote(str(token), safe="")
    return f"{base_url.rstrip('/')}/login?token={safe_token}"


async def issue_bot_dashboard_url(user_id: int) -> str | None:
    """Issue a dashboard login URL using the bot process Redis client.

    Used by Telegram handlers (main menu, statistics). Returns ``None`` when
    the dashboard is not configured or Redis/token creation fails — never
    raises for those cases.
    """
    try:
        from src.api.token_store import RedisTokenStore
        from src.bot import redis as bot_redis

        store = RedisTokenStore(bot_redis)
        return await issue_dashboard_link(user_id, store)
    except Exception:
        logger.exception("Dashboard link failed for user_id=%s", user_id)
        return None


async def issue_dashboard_link(
    user_id: int,
    store: TokenStore | SupportsCreateOtt,
    *,
    base_url: str | None = None,
    ttl_seconds: int | None = None,
) -> str | None:

    """Issue a one-time dashboard login URL for *user_id*.

    Returns:
        Full login URL, or ``None`` when the dashboard is not configured
        (empty ``DASHBOARD_PUBLIC_URL``) or token creation fails.

    Never raises for configuration / store errors — callers can safely
    omit the button when the result is ``None``.
    """
    base = normalize_dashboard_base_url(
        base_url if base_url is not None else settings.DASHBOARD_PUBLIC_URL
    )
    if base is None:
        logger.info(
            "Dashboard link skipped: DASHBOARD_PUBLIC_URL is empty/unset "
            "(user_id=%s)",
            user_id,
        )
        return None

    if user_id is None:
        return None
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        logger.warning("issue_dashboard_link: invalid user_id=%r", user_id)
        return None
    if uid <= 0:
        return None

    # Keep the Telegram Mini App URL stable. Authentication is performed
    # by the frontend using Telegram WebApp.initData on every launch.
    return f"{base}/login"
