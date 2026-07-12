"""One-time token issue/exchange and JWT helpers for the stats API."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from src.api.token_store import TokenStore
from src.config import settings

OTT_KEY_PREFIX = "dash:ott:"
JWT_ALGORITHM = "HS256"


def _ott_redis_key(token: str) -> str:
    return f"{OTT_KEY_PREFIX}{token}"


async def create_ott(
    store: TokenStore,
    user_id: int,
    *,
    ttl_seconds: int | None = None,
) -> str:
    """Create a one-time dashboard token bound to *user_id*."""
    token = secrets.token_urlsafe(32)
    ttl = ttl_seconds if ttl_seconds is not None else settings.API_OTT_TTL_SECONDS
    await store.set(_ott_redis_key(token), str(user_id), ttl)
    return token


async def exchange_ott(
    store: TokenStore,
    token: str,
    *,
    jwt_secret: str | None = None,
    expire_minutes: int | None = None,
    telegram_id: int | None = None,
) -> dict[str, Any]:
    """Consume a one-time token and return a JWT access payload dict.

    Raises:
        ValueError: if token is missing, empty, or already used/expired.
    """
    if not token or not str(token).strip():
        raise ValueError("token is required")

    raw = await store.pop(_ott_redis_key(str(token).strip()))
    if raw is None:
        raise ValueError("invalid or expired token")

    try:
        user_id = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid token payload") from exc

    access_token = create_jwt(
        user_id,
        telegram_id=telegram_id,
        jwt_secret=jwt_secret,
        expire_minutes=expire_minutes,
    )
    exp_minutes = (
        expire_minutes
        if expire_minutes is not None
        else settings.API_JWT_EXPIRE_MINUTES
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": int(exp_minutes) * 60,
    }


def create_jwt(
    user_id: int,
    *,
    telegram_id: int | None = None,
    jwt_secret: str | None = None,
    expire_minutes: int | None = None,
) -> str:
    """Create a signed HS256 JWT with ``sub`` = internal user id."""
    secret = jwt_secret if jwt_secret is not None else settings.API_JWT_SECRET
    minutes = (
        expire_minutes
        if expire_minutes is not None
        else settings.API_JWT_EXPIRE_MINUTES
    )
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=int(minutes)),
    }
    if telegram_id is not None:
        payload["tg"] = int(telegram_id)
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def decode_jwt(
    token: str,
    *,
    jwt_secret: str | None = None,
) -> dict[str, Any]:
    """Decode and validate a JWT; raises jwt exceptions on failure."""
    secret = jwt_secret if jwt_secret is not None else settings.API_JWT_SECRET
    return jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])


def user_id_from_payload(payload: dict[str, Any]) -> int:
    """Extract internal user id from JWT payload ``sub``."""
    sub = payload.get("sub")
    if sub is None:
        raise ValueError("missing sub")
    return int(sub)
