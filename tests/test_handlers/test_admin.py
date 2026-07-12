"""Tests for admin user listing helpers and /admin command."""

from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
import pytest_asyncio
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import User
from src.handlers.admin import (
    _display_name,
    _format_last_seen,
    _format_user_line,
    _is_admin,
)
from tests.conftest import TestClient

if TYPE_CHECKING:
    from aiogram import Bot


def test_display_name_full() -> None:
    user = User(
        telegram_id=1,
        first_name="Иван",
        last_name="Петров",
    )
    assert _display_name(user) == "Иван Петров"


def test_display_name_first_only() -> None:
    user = User(telegram_id=1, first_name="Мария")
    assert _display_name(user) == "Мария"


def test_display_name_empty() -> None:
    user = User(telegram_id=1)
    assert _display_name(user) == "—"


def test_format_last_seen() -> None:
    user = User(
        telegram_id=1,
        updated_at=datetime(2026, 7, 12, 15, 30, tzinfo=timezone.utc),
    )
    assert _format_last_seen(user) == "2026-07-12 15:30 UTC"


def test_format_user_line_with_username_and_name() -> None:
    user = User(
        telegram_id=123456789,
        username="ivan_petrov",
        first_name="Иван",
        last_name="Петров",
        updated_at=datetime(2026, 7, 12, 10, 0, tzinfo=timezone.utc),
    )
    line = _format_user_line(user)
    assert "123456789" in line
    assert "@ivan_petrov" in line
    assert "Иван Петров" in line
    assert "2026-07-12 10:00 UTC" in line
    assert 'href="tg://user?id=123456789"' in line
    assert "открыть" in line


def test_format_user_line_without_username() -> None:
    user = User(
        telegram_id=987654321,
        username=None,
        first_name="Мария",
        last_name=None,
    )
    line = _format_user_line(user)
    assert "987654321" in line
    assert "—" in line
    assert "Мария" in line
    assert 'href="tg://user?id=987654321"' in line


def test_format_user_line_escapes_html() -> None:
    import html as html_mod

    raw_username = "a" + chr(60) + "b" + chr(62)  # a<b>
    raw_name = "X&Y"
    user = User(
        telegram_id=1,
        username=raw_username,
        first_name=raw_name,
        last_name=None,
    )
    line = _format_user_line(user)
    assert html_mod.escape("@" + raw_username) in line
    assert html_mod.escape(raw_name) in line
    assert raw_username not in line


def test_is_admin_matches_settings() -> None:
    with patch("src.handlers.admin.settings") as mock_settings:
        mock_settings.ADMIN_ID = 42
        assert _is_admin(42) is True
        assert _is_admin(1) is False


@pytest_asyncio.fixture
async def admin_client(test_bot: "Bot", async_session: AsyncSession) -> TestClient:
    """TestClient with admin router and in-memory DB."""
    import src.handlers.admin as admin_module

    importlib.reload(admin_module)

    @asynccontextmanager
    async def _fake_get_db():
        yield async_session

    admin_module.get_db = _fake_get_db  # type: ignore[assignment]

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin_module.router)
    return TestClient(bot=test_bot, dp=dp)


@pytest.mark.asyncio
async def test_admin_command_lists_users(
    admin_client: TestClient,
    async_session: AsyncSession,
) -> None:
    """Admin sees user list with names and last activity."""
    async_session.add(
        User(
            telegram_id=111,
            username="alice",
            first_name="Alice",
            last_name="A",
            updated_at=datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc),
        )
    )
    await async_session.commit()

    with patch("src.handlers.admin.settings") as mock_settings:
        mock_settings.ADMIN_ID = 123456
        message = await admin_client.send_message("/admin", user_id=123456)

    assert message.text is not None
    assert "Админ-панель" in message.text
    assert "111" in message.text
    assert "@alice" in message.text
    assert "Alice A" in message.text
    assert "2026-07-11 12:00 UTC" in message.text


@pytest.mark.asyncio
async def test_admin_command_forbidden_for_non_admin(
    admin_client: TestClient,
) -> None:
    with patch("src.handlers.admin.settings") as mock_settings:
        mock_settings.ADMIN_ID = 999999
        message = await admin_client.send_message("/admin", user_id=123456)

    assert message.text is not None
    assert "только администратору" in message.text
