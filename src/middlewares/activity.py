"""Middleware that keeps user profile and last-activity timestamp in sync."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User as TgUser
from sqlalchemy import select

from src.db.models import User
from src.db.session import get_db

logger = logging.getLogger(__name__)


def _extract_from_user(event: TelegramObject) -> TgUser | None:
    """Return Telegram user from message/callback events, if present."""
    if isinstance(event, Message):
        return event.from_user
    if isinstance(event, CallbackQuery):
        return event.from_user
    return getattr(event, "from_user", None)


class UserActivityMiddleware(BaseMiddleware):
    """Update username/name and ``updated_at`` on every user interaction.

    Does not create users (that remains the job of ``/start`` and AI apply).
    Failures are logged and never block the handler chain.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = _extract_from_user(event)
        if tg_user is not None and not tg_user.is_bot:
            try:
                await self._touch_user(tg_user)
            except Exception:
                logger.warning(
                    "Failed to update activity for telegram_id=%s",
                    getattr(tg_user, "id", None),
                    exc_info=True,
                )
        return await handler(event, data)

    async def _touch_user(self, tg_user: TgUser) -> None:
        """Sync profile fields and bump ``updated_at`` for an existing user."""
        async with get_db() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == tg_user.id)
            )
            user = result.scalar_one_or_none()
            if user is None:
                return

            user.username = tg_user.username
            user.first_name = tg_user.first_name
            user.last_name = tg_user.last_name
            # Explicit touch: onupdate may not fire if only some fields match.
            user.updated_at = datetime.now(timezone.utc)
            await session.commit()
