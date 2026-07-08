"""Tests for the settings menu handlers."""

from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from datetime import time
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
import pytest_asyncio
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import User

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import Message

    from tests.conftest import TestClient


# ---------------------------------------------------------------------------
# Fixture: a dispatcher with settings, statistics, and common routers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def full_dispatcher() -> Dispatcher:
    """Return a fresh Dispatcher with settings, statistics, and common routers."""
    import src.handlers.common
    import src.handlers.settings
    import src.handlers.statistics

    importlib.reload(src.handlers.settings)
    importlib.reload(src.handlers.statistics)
    importlib.reload(src.handlers.common)
    from src.handlers.common import router as common_router
    from src.handlers.settings import router as settings_router
    from src.handlers.statistics import router as statistics_router

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(settings_router)
    dp.include_router(statistics_router)
    dp.include_router(common_router)
    return dp


@pytest_asyncio.fixture(scope="function")
async def full_client(
    test_bot: Bot,
    full_dispatcher: Dispatcher,
) -> "TestClient":
    """Provide a TestClient wired to the full dispatcher."""
    from tests.conftest import TestClient

    return TestClient(bot=test_bot, dp=full_dispatcher)


# ---------------------------------------------------------------------------
# Helper: mock get_db with the test async_session
# ---------------------------------------------------------------------------


def _mock_get_db_context(async_session: AsyncSession):
    """Return a context manager factory that yields the test session."""

    @asynccontextmanager
    async def _mock_get_db():
        yield async_session

    return _mock_get_db


# ---------------------------------------------------------------------------
# Helper: create a user in the test database
# ---------------------------------------------------------------------------


async def _create_user(async_session: AsyncSession, telegram_id: int = 123456) -> User:
    """Create and return a test User."""
    user = User(telegram_id=telegram_id, language="ru", timezone="UTC")
    async_session.add(user)
    await async_session.commit()
    return user


# ---------------------------------------------------------------------------
# Tests: open settings menu
# ---------------------------------------------------------------------------


class TestSettingsMenuOpen:
    """Tests for opening the settings menu from the main menu."""

    @pytest.mark.asyncio
    async def test_open_settings_menu(
        self,
        full_client: "TestClient",
        async_session: AsyncSession,
    ) -> None:
        """Clicking 'Settings' in main menu shows the settings keyboard."""
        await _create_user(async_session)

        with patch(
            "src.handlers.settings.get_db",
            _mock_get_db_context(async_session),
        ):
            resp: Message = await full_client.send_callback(
                "main_menu:settings",
                user_id=123456,
                message_text="🏠 Главное меню бота\nВыберите действие:",
            )

        assert "Настройки" in resp.text
        rmk = str(resp.reply_markup)
        assert "settings:language" in rmk
        assert "settings:timezone" in rmk
        assert "settings:reminder_time" in rmk
        assert "settings:check_interval" in rmk


# ---------------------------------------------------------------------------
# Tests: change language
# ---------------------------------------------------------------------------


class TestChangeLanguage:
    """Tests for the language selection flow."""

    @pytest.mark.asyncio
    async def test_navigate_to_language(
        self,
        full_client: "TestClient",
        async_session: AsyncSession,
    ) -> None:
        """Clicking 'Language' shows the language keyboard."""
        await _create_user(async_session)

        with patch(
            "src.handlers.settings.get_db",
            _mock_get_db_context(async_session),
        ):
            resp: Message = await full_client.send_callback(
                "settings:language",
                user_id=123456,
                message_text="⚙️ Настройки\nВыберите параметр для изменения:",
            )

        assert "Выберите язык" in resp.text
        assert "settings:set_language:ru" in str(resp.reply_markup)

    @pytest.mark.asyncio
    async def test_set_language_en(
        self,
        full_client: "TestClient",
        async_session: AsyncSession,
    ) -> None:
        """Selecting 'EN' saves 'en' to the user record."""
        await _create_user(async_session)

        with patch(
            "src.handlers.settings.get_db",
            _mock_get_db_context(async_session),
        ):
            resp: Message = await full_client.send_callback(
                "settings:set_language:en",
                user_id=123456,
                message_text="🌐 Выберите язык:",
            )

        stmt = select(User).where(User.telegram_id == 123456)
        result = await async_session.execute(stmt)
        user = result.scalar_one_or_none()
        assert user.language == "en"
        assert "EN" in resp.text

    @pytest.mark.asyncio
    async def test_set_language_fr(
        self,
        full_client: "TestClient",
        async_session: AsyncSession,
    ) -> None:
        """Selecting 'FR' saves 'fr' to the user record."""
        await _create_user(async_session)

        with patch(
            "src.handlers.settings.get_db",
            _mock_get_db_context(async_session),
        ):
            await full_client.send_callback(
                "settings:set_language:fr",
                user_id=123456,
                message_text="🌐 Выберите язык:",
            )

        stmt = select(User).where(User.telegram_id == 123456)
        result = await async_session.execute(stmt)
        user = result.scalar_one_or_none()
        assert user.language == "fr"

    @pytest.mark.asyncio
    async def test_set_language_es(
        self,
        full_client: "TestClient",
        async_session: AsyncSession,
    ) -> None:
        """Selecting 'ES' saves 'es' to the user record."""
        await _create_user(async_session)

        with patch(
            "src.handlers.settings.get_db",
            _mock_get_db_context(async_session),
        ):
            await full_client.send_callback(
                "settings:set_language:es",
                user_id=123456,
                message_text="🌐 Выберите язык:",
            )

        stmt = select(User).where(User.telegram_id == 123456)
        result = await async_session.execute(stmt)
        user = result.scalar_one_or_none()
        assert user.language == "es"

    @pytest.mark.asyncio
    async def test_set_language_jp(
        self,
        full_client: "TestClient",
        async_session: AsyncSession,
    ) -> None:
        """Selecting 'JP' saves 'jp' to the user record."""
        await _create_user(async_session)

        with patch(
            "src.handlers.settings.get_db",
            _mock_get_db_context(async_session),
        ):
            await full_client.send_callback(
                "settings:set_language:jp",
                user_id=123456,
                message_text="🌐 Выберите язык:",
            )

        stmt = select(User).where(User.telegram_id == 123456)
        result = await async_session.execute(stmt)
        user = result.scalar_one_or_none()
        assert user.language == "jp"


# ---------------------------------------------------------------------------
# Tests: change timezone
# ---------------------------------------------------------------------------


class TestChangeTimezone:
    """Tests for the timezone selection flow."""

    @pytest.mark.asyncio
    async def test_navigate_to_timezone(
        self,
        full_client: "TestClient",
        async_session: AsyncSession,
    ) -> None:
        """Clicking 'Timezone' shows the timezone keyboard."""
        await _create_user(async_session)

        with patch(
            "src.handlers.settings.get_db",
            _mock_get_db_context(async_session),
        ):
            resp: Message = await full_client.send_callback(
                "settings:timezone",
                user_id=123456,
                message_text="⚙️ Настройки\nВыберите параметр для изменения:",
            )

        assert "Выберите часовой пояс" in resp.text
        assert "settings:set_timezone:+3" in str(resp.reply_markup)

    @pytest.mark.asyncio
    async def test_set_timezone_plus3(
        self,
        full_client: "TestClient",
        async_session: AsyncSession,
    ) -> None:
        """Selecting UTC+3 saves '+3' to the user record."""
        await _create_user(async_session)

        with patch(
            "src.handlers.settings.get_db",
            _mock_get_db_context(async_session),
        ):
            resp: Message = await full_client.send_callback(
                "settings:set_timezone:+3",
                user_id=123456,
                message_text="🕐 Выберите часовой пояс:",
            )

        stmt = select(User).where(User.telegram_id == 123456)
        result = await async_session.execute(stmt)
        user = result.scalar_one_or_none()
        assert user.timezone == "+3"
        assert "UTC+3" in resp.text

    @pytest.mark.asyncio
    async def test_set_timezone_minus5(
        self,
        full_client: "TestClient",
        async_session: AsyncSession,
    ) -> None:
        """Selecting UTC-5 saves '-5' to the user record."""
        await _create_user(async_session)

        with patch(
            "src.handlers.settings.get_db",
            _mock_get_db_context(async_session),
        ):
            await full_client.send_callback(
                "settings:set_timezone:-5",
                user_id=123456,
                message_text="🕐 Выберите часовой пояс:",
            )

        stmt = select(User).where(User.telegram_id == 123456)
        result = await async_session.execute(stmt)
        user = result.scalar_one_or_none()
        assert user.timezone == "-5"


# ---------------------------------------------------------------------------
# Tests: change reminder time
# ---------------------------------------------------------------------------


class TestChangeReminderTime:
    """Tests for the reminder time selection flow."""

    @pytest.mark.asyncio
    async def test_navigate_to_reminder_time(
        self,
        full_client: "TestClient",
        async_session: AsyncSession,
    ) -> None:
        """Clicking 'Reminder Time' shows the time selection keyboard."""
        await _create_user(async_session)

        with patch(
            "src.handlers.settings.get_db",
            _mock_get_db_context(async_session),
        ):
            resp: Message = await full_client.send_callback(
                "settings:reminder_time",
                user_id=123456,
                message_text="⚙️ Настройки\nВыберите параметр для изменения:",
            )

        assert "Выберите время" in resp.text
        assert "reminder:off" in str(resp.reply_markup)

    @pytest.mark.asyncio
    async def test_set_reminder_0900(
        self,
        full_client: "TestClient",
        async_session: AsyncSession,
    ) -> None:
        """Selecting 09:00 saves it to the user record."""
        await _create_user(async_session)

        with patch(
            "src.handlers.settings.get_db",
            _mock_get_db_context(async_session),
        ):
            resp: Message = await full_client.send_callback(
                "settings:set_reminder:09:00",
                user_id=123456,
                message_text="⏰ Выберите время ежедневного уведомления:",
            )

        stmt = select(User).where(User.telegram_id == 123456)
        result = await async_session.execute(stmt)
        user = result.scalar_one_or_none()
        assert user.reminder_time == time(9, 0)
        assert "09:00" in resp.text

    @pytest.mark.asyncio
    async def test_disable_reminder(
        self,
        full_client: "TestClient",
        async_session: AsyncSession,
    ) -> None:
        """Clicking 'Disable' sets reminder_time to None."""
        await _create_user(async_session)

        with patch(
            "src.handlers.settings.get_db",
            _mock_get_db_context(async_session),
        ):
            # First set a reminder
            await full_client.send_callback(
                "settings:set_reminder:09:00",
                user_id=123456,
                message_text="⏰ Выберите время ежедневного уведомления:",
            )
            # Then disable it
            resp: Message = await full_client.send_callback(
                "reminder:off",
                user_id=123456,
                message_text="⚙️ Настройки\nВыберите параметр для изменения:",
            )

        stmt = select(User).where(User.telegram_id == 123456)
        result = await async_session.execute(stmt)
        user = result.scalar_one_or_none()
        assert user.reminder_time is None
        assert "отключены" in resp.text.lower()


# ---------------------------------------------------------------------------
# Tests: change check interval
# ---------------------------------------------------------------------------


class TestChangeCheckInterval:
    """Tests for the check interval selection flow."""

    @pytest.mark.asyncio
    async def test_navigate_to_check_interval(
        self,
        full_client: "TestClient",
        async_session: AsyncSession,
    ) -> None:
        """Clicking 'Check Interval' shows the interval keyboard."""
        await _create_user(async_session)

        with patch(
            "src.handlers.settings.get_db",
            _mock_get_db_context(async_session),
        ):
            resp: Message = await full_client.send_callback(
                "settings:check_interval",
                user_id=123456,
                message_text="⚙️ Настройки\nВыберите параметр для изменения:",
            )

        assert "Выберите интервал" in resp.text
        assert "settings:set_interval:15" in str(resp.reply_markup)

    @pytest.mark.asyncio
    async def test_set_interval_10(
        self,
        full_client: "TestClient",
        async_session: AsyncSession,
    ) -> None:
        """Selecting 10 min saves it to the user record."""
        await _create_user(async_session)

        with patch(
            "src.handlers.settings.get_db",
            _mock_get_db_context(async_session),
        ):
            resp: Message = await full_client.send_callback(
                "settings:set_interval:10",
                user_id=123456,
                message_text="⏱ Выберите интервал проверки выполнения:",
            )

        stmt = select(User).where(User.telegram_id == 123456)
        result = await async_session.execute(stmt)
        user = result.scalar_one_or_none()
        assert user.check_interval == 10
        assert "10 мин" in resp.text

    @pytest.mark.asyncio
    async def test_set_interval_30(
        self,
        full_client: "TestClient",
        async_session: AsyncSession,
    ) -> None:
        """Selecting 30 min saves it to the user record."""
        await _create_user(async_session)

        with patch(
            "src.handlers.settings.get_db",
            _mock_get_db_context(async_session),
        ):
            await full_client.send_callback(
                "settings:set_interval:30",
                user_id=123456,
                message_text="⏱ Выберите интервал проверки выполнения:",
            )

        stmt = select(User).where(User.telegram_id == 123456)
        result = await async_session.execute(stmt)
        user = result.scalar_one_or_none()
        assert user.check_interval == 30


# ---------------------------------------------------------------------------
# Tests: navigation
# ---------------------------------------------------------------------------


class TestSettingsNavigation:
    """Tests for navigation buttons in settings."""

    @pytest.mark.asyncio
    async def test_back_from_submenu(
        self,
        full_client: "TestClient",
        async_session: AsyncSession,
    ) -> None:
        """Pressing 'Back' in a submenu returns to the settings menu."""
        await _create_user(async_session)

        with patch(
            "src.handlers.settings.get_db",
            _mock_get_db_context(async_session),
        ):
            resp: Message = await full_client.send_callback(
                "settings:back",
                user_id=123456,
                message_text="🌐 Выберите язык:",
            )

        assert "Настройки" in resp.text
        assert "settings:language" in str(resp.reply_markup)

    @pytest.mark.asyncio
    async def test_cancel_to_main_menu(
        self,
        full_client: "TestClient",
        async_session: AsyncSession,
    ) -> None:
        """Pressing 'Main Menu' in settings goes to the main menu."""
        await _create_user(async_session)

        with patch(
            "src.handlers.settings.get_db",
            _mock_get_db_context(async_session),
        ):
            resp: Message = await full_client.send_callback(
                "nav:cancel",
                user_id=123456,
                message_text="⚙️ Настройки\nВыберите параметр для изменения:",
            )

        assert "Главное меню" in resp.text
        assert "main_menu:" in str(resp.reply_markup)
