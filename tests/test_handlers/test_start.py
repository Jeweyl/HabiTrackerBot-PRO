"""Tests for the /start command handler."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import User
from src.keyboards.inline import MAIN_MENU_BUTTONS

if TYPE_CHECKING:
    from tests.conftest import TestClient


@pytest.mark.asyncio
async def test_start_creates_user(
    client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that /start creates a new user record in the database."""

    @asynccontextmanager
    async def _mock_get_db():
        yield async_session

    with patch("src.handlers.common.get_db", side_effect=_mock_get_db):
        message = await client.send_message("/start")

    # Check the response
    assert message.text == "🏠 Главное меню бота\nВыберите действие:"
    assert message.reply_markup is not None
    assert len(message.reply_markup.inline_keyboard) == 9

    # Check that the user was persisted
    stmt = select(User).where(User.telegram_id == 123456)
    result = await async_session.execute(stmt)
    user = result.scalar_one()
    assert user.language == "ru"
    assert user.timezone == "UTC"


@pytest.mark.asyncio
async def test_start_existing_user_not_duplicated(
    client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that /start does not create a duplicate when the user already exists."""

    # Pre-create the user
    existing = User(telegram_id=123456, language="en", timezone="Europe/Moscow")
    async_session.add(existing)
    await async_session.commit()

    @asynccontextmanager
    async def _mock_get_db():
        yield async_session

    with patch("src.handlers.common.get_db", side_effect=_mock_get_db):
        message = await client.send_message("/start")

    assert message.text == "🏠 Главное меню бота\nВыберите действие:"

    # Ensure only one record exists
    stmt = select(User).where(User.telegram_id == 123456)
    result = await async_session.execute(stmt)
    users = result.scalars().all()
    assert len(users) == 1
    # Existing values should be preserved
    assert users[0].language == "en"
    assert users[0].timezone == "Europe/Moscow"


@pytest.mark.asyncio
async def test_start_sends_correct_keyboard(
    client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that /start sends an inline keyboard with 8 buttons and correct callback_data."""

    @asynccontextmanager
    async def _mock_get_db():
        yield async_session

    with patch("src.handlers.common.get_db", side_effect=_mock_get_db):
        message = await client.send_message("/start")

    keyboard = message.reply_markup.inline_keyboard
    assert len(keyboard) == len(MAIN_MENU_BUTTONS)

    for row, (expected_label, expected_cb) in zip(keyboard, MAIN_MENU_BUTTONS):
        assert len(row) == 1
        assert row[0].text == expected_label
        assert row[0].callback_data == expected_cb
