"""Auth routes: one-time token exchange."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import OTT_KEY_PREFIX, create_jwt
from src.api.deps import get_session, get_token_store
from src.api.schemas import TelegramInitDataRequest, TokenExchangeRequest, TokenExchangeResponse
from src.api.token_store import TokenStore
from src.config import settings
from src.db.models import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _telegram_user_id_from_init_data(init_data: str) -> int:
    """Validate Telegram Mini App initData and return the Telegram user id."""
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise ValueError("missing Telegram initData hash")
    try:
        auth_date = int(pairs.get("auth_date") or 0)
    except ValueError as exc:
        raise ValueError("invalid auth_date") from exc
    if auth_date <= 0 or abs(int(time.time()) - auth_date) > 86400:
        raise ValueError("expired Telegram initData")
    data_check_string = "\\n".join(
        f"{key}={value}" for key, value in sorted(pairs.items())
    )
    secret_key = hmac.new(
        b"WebAppData", settings.BOT_TOKEN.encode("utf-8"), hashlib.sha256
    ).digest()
    expected_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise ValueError("invalid Telegram initData signature")
    try:
        user = json.loads(pairs.get("user") or "{}")
        telegram_id = int(user["id"])
    except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("invalid Telegram user data") from exc
    if telegram_id <= 0:
        raise ValueError("invalid Telegram user id")
    return telegram_id


@router.post(
    "/exchange",
    response_model=TokenExchangeResponse,
    responses={401: {"description": "Invalid or expired one-time token"}},
)
async def exchange_token(
    body: TokenExchangeRequest,
    store: Annotated[TokenStore, Depends(get_token_store)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenExchangeResponse:
    """Consume a one-time dashboard token and return a short-lived JWT."""
    try:
        raw_result = await _exchange_with_user(store, body.token, session)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from None

    return TokenExchangeResponse(**raw_result)


async def _exchange_with_user(
    store: TokenStore,
    token: str,
    session: AsyncSession,
) -> dict:
    """Exchange OTT; attach telegram_id claim when user still exists."""
    if not token or not str(token).strip():
        raise ValueError("token is required")

    key = f"{OTT_KEY_PREFIX}{str(token).strip()}"
    raw = await store.pop(key)
    if raw is None:
        raise ValueError("invalid or expired token")

    try:
        user_id = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid token payload") from exc

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError("user not found")

    access_token = create_jwt(user_id, telegram_id=user.telegram_id)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": int(settings.API_JWT_EXPIRE_MINUTES) * 60,
    }


@router.post("/telegram", response_model=TokenExchangeResponse)
async def exchange_telegram_init_data(
    body: TelegramInitDataRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenExchangeResponse:
    """Authenticate a Mini App directly from Telegram initData."""
    try:
        telegram_id = _telegram_user_id_from_init_data(body.init_data)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Telegram initData") from None
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return TokenExchangeResponse(
        access_token=create_jwt(user.id, telegram_id=telegram_id),
        token_type="bearer",
        expires_in=int(settings.API_JWT_EXPIRE_MINUTES) * 60,
    )
