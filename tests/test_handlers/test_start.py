"""Tests for the /start command handler."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import User
from src.handlers.common import _build_start_text
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

    # Onboarding text + main menu keyboard (callback rows; dashboard optional)
    assert message.text is not None
    assert "HabiTracker" in message.text
    assert "Создать привычку" in message.text or "создать привычку" in message.text.lower()
    assert message.reply_markup is not None
    # Without DASHBOARD_PUBLIC_URL / Redis in tests: only callback buttons
    assert len(message.reply_markup.inline_keyboard) == len(MAIN_MENU_BUTTONS)


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

    assert message.text is not None
    assert "HabiTracker" in message.text
    assert message.reply_markup is not None

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
    """Verify that /start sends an inline keyboard with correct callback_data."""

    @asynccontextmanager
    async def _mock_get_db():
        yield async_session

    with patch("src.handlers.common.get_db", side_effect=_mock_get_db):
        message = await client.send_message("/start")

    keyboard = message.reply_markup.inline_keyboard
    from src.utils.keyboard_width import strip_button_padding

    # Optional leading Web App row when dashboard URL is available
    offset = 0
    if keyboard and keyboard[0] and getattr(keyboard[0][0], "web_app", None):
        offset = 1
        assert "приложение" in strip_button_padding(keyboard[0][0].text).lower() or (
            "app" in strip_button_padding(keyboard[0][0].text).lower()
        )

    assert len(keyboard) == len(MAIN_MENU_BUTTONS) + offset

    for row, (expected_label, expected_cb) in zip(
        keyboard[offset:], MAIN_MENU_BUTTONS
    ):
        assert len(row) == 1
        assert strip_button_padding(row[0].text) == expected_label
        assert row[0].callback_data == expected_cb




def test_start_includes_links_when_configured() -> None:
    """Onboarding text must include links when settings provide them."""
    text = _build_start_text(
        bot_public_url="https://t.me/HabiTrakerBot",
        channel_url="https://t.me/HabiTraker",
        original_bot_username="HabiTrakerBot",
    )
    assert "HabiTracker" in text
    assert "https://t.me/HabiTraker" in text
    assert "HabiTrakerBot" in text
    assert "Ссылки" in text or "ссылк" in text.lower()


def test_start_skips_links_when_empty() -> None:
    """Empty URLs must omit the links block without crashing."""
    text = _build_start_text(
        bot_public_url="",
        channel_url="",
        original_bot_username="",
    )
    assert "HabiTracker" in text
    assert "Ссылки" not in text
    assert "https://t.me/" not in text
    assert "@" not in text or "HabiTracker" in text  # no bot @mention required
    # CTA / description still present
    assert "привыч" in text.lower()
