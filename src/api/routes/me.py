"""Authenticated user profile and account settings."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_session
from src.api.schemas import MeResponse, MeUpdateRequest
from src.db.models import User
from src.services import user_settings as settings_svc

router = APIRouter(prefix="/api/v1", tags=["me"])


def _user_to_me(user: User) -> MeResponse:
    return MeResponse(
        id=user.id,
        telegram_id=user.telegram_id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        language=(user.language or "ru").strip().lower()
        if (user.language or "").strip().lower() in {"ru", "en"}
        else "ru",
        timezone=user.timezone or "UTC",
        reminder_time=settings_svc.format_reminder_time(user.reminder_time),
        check_interval=int(user.check_interval or 15),
    )


def _http_422(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


@router.get(
    "/me",
    response_model=MeResponse,
    responses={401: {"description": "Unauthorized"}},
)
async def get_me(
    user: Annotated[User, Depends(get_current_user)],
) -> MeResponse:
    """Return the current user's profile and settings."""
    return _user_to_me(user)


@router.patch(
    "/me",
    response_model=MeResponse,
    responses={
        401: {"description": "Unauthorized"},
        422: {"description": "Validation error"},
    },
)
async def patch_me(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MeResponse:
    """Partially update account settings (language, timezone, reminders).

    Body is JSON. Omitted fields are left unchanged. To disable the daily
    reminder, send ``\"reminder_time\": null`` explicitly.
    """
    try:
        raw: Any = await request.json()
    except Exception as exc:
        raise _http_422("Invalid JSON body") from exc

    if raw is None or not isinstance(raw, dict):
        raise _http_422("Body must be a JSON object")

    # Detect explicit null for reminder_time (vs omit).
    reminder_provided = "reminder_time" in raw

    try:
        body = MeUpdateRequest.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    if body.language is not None:
        try:
            user.language = settings_svc.normalize_language(body.language)
        except ValueError as exc:
            raise _http_422(str(exc)) from exc

    if body.timezone is not None:
        try:
            user.timezone = settings_svc.normalize_timezone(body.timezone)
        except ValueError as exc:
            raise _http_422(str(exc)) from exc

    if reminder_provided:
        try:
            user.reminder_time = settings_svc.parse_reminder_time(
                body.reminder_time
            )
        except ValueError as exc:
            raise _http_422(str(exc)) from exc

    if body.check_interval is not None:
        try:
            user.check_interval = settings_svc.normalize_check_interval(
                body.check_interval
            )
        except ValueError as exc:
            raise _http_422(str(exc)) from exc

    session.add(user)
    await session.flush()
    await session.refresh(user)
    return _user_to_me(user)
