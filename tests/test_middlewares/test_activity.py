"""Tests for UserActivityMiddleware."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import User as TgUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import User
from src.middlewares.activity import UserActivityMiddleware, _extract_from_user


def test_extract_from_user_message() -> None:
    tg = TgUser(id=1, is_bot=False, first_name="A")
    msg = MagicMock()
    msg.from_user = tg
    # isinstance checks Message — use real type via patch path not needed;
    # call with object that has from_user for generic path
    assert _extract_from_user(msg) is tg


@pytest.mark.asyncio
async def test_touch_user_updates_profile_and_timestamp(
    async_session: AsyncSession,
) -> None:
    user = User(
        telegram_id=42,
        username="old",
        first_name="Old",
        last_name=None,
        updated_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    async_session.add(user)
    await async_session.commit()

    @asynccontextmanager
    async def _mock_get_db():
        yield async_session

    mw = UserActivityMiddleware()
    tg = TgUser(
        id=42,
        is_bot=False,
        first_name="New",
        last_name="Name",
        username="new_nick",
    )

    with patch("src.middlewares.activity.get_db", side_effect=_mock_get_db):
        await mw._touch_user(tg)

    result = await async_session.execute(select(User).where(User.telegram_id == 42))
    refreshed = result.scalar_one()
    assert refreshed.username == "new_nick"
    assert refreshed.first_name == "New"
    assert refreshed.last_name == "Name"
    assert refreshed.updated_at is not None
    assert refreshed.updated_at.year >= 2026 or refreshed.updated_at > datetime(
        2020, 1, 1, tzinfo=timezone.utc
    )


@pytest.mark.asyncio
async def test_touch_user_missing_is_noop(async_session: AsyncSession) -> None:
    @asynccontextmanager
    async def _mock_get_db():
        yield async_session

    mw = UserActivityMiddleware()
    tg = TgUser(id=999, is_bot=False, first_name="Ghost")

    with patch("src.middlewares.activity.get_db", side_effect=_mock_get_db):
        await mw._touch_user(tg)

    result = await async_session.execute(select(User))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_middleware_calls_handler_even_if_touch_fails() -> None:
    mw = UserActivityMiddleware()
    handler = AsyncMock(return_value="ok")
    event = MagicMock()
    event.from_user = TgUser(id=1, is_bot=False, first_name="X")

    with patch.object(mw, "_touch_user", side_effect=RuntimeError("db down")):
        result = await mw(handler, event, {})

    assert result == "ok"
    handler.assert_awaited_once()
