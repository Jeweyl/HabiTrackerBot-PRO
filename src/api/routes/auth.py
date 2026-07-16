"""Auth routes: one-time token exchange."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import OTT_KEY_PREFIX, create_jwt
from src.api.deps import get_session, get_token_store
from src.api.schemas import TokenExchangeRequest, TokenExchangeResponse
from src.api.token_store import TokenStore
from src.config import settings
from src.db.models import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


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
