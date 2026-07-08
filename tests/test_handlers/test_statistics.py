"""Tests for the statistics handler."""

from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from datetime import date, timedelta
from datetime import time as dtime
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
import pytest_asyncio
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Habit, Task, User

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import Message

    from tests.conftest import TestClient


# ---------------------------------------------------------------------------
# Fixture: a dispatcher with statistics and common routers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def full_dispatcher() -> Dispatcher:
    """Return a fresh Dispatcher with statistics and common routers."""
    import src.handlers.common
    import src.handlers.statistics

    importlib.reload(src.handlers.statistics)
    importlib.reload(src.handlers.common)
    from src.handlers.common import router as common_router
    from src.handlers.statistics import router as statistics_router

    dp = Dispatcher(storage=MemoryStorage())
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
# Helpers: create test data
# ---------------------------------------------------------------------------


async def _create_user(async_session: AsyncSession, telegram_id: int = 123456) -> User:
    """Create and return a test User."""
    user = User(telegram_id=telegram_id, language="ru", timezone="UTC")
    async_session.add(user)
    await async_session.commit()
    return user


async def _create_task(
    async_session: AsyncSession,
    user: User,
    title: str,
    task_date: date,
    start_hour: int = 9,
    is_completed: bool = False,
    habit_id: int | None = None,
) -> Task:
    """Create and return a test Task."""
    task = Task(
        user_id=user.id,
        habit_id=habit_id,
        title=title,
        date=task_date,
        start_time=dtime(start_hour, 0),
        end_time=dtime(start_hour + 1, 0),
        is_completed=is_completed,
    )
    async_session.add(task)
    await async_session.commit()
    return task


async def _create_habit(
    async_session: AsyncSession,
    user: User,
    title: str = "Тестовая привычка",
) -> Habit:
    """Create and return a test Habit."""
    habit = Habit(
        user_id=user.id,
        title=title,
        start_time=dtime(9, 0),
        end_time=dtime(10, 0),
        frequency="daily",
    )
    async_session.add(habit)
    await async_session.commit()
    return habit


# ---------------------------------------------------------------------------
# Tests: statistics with data
# ---------------------------------------------------------------------------


class TestStatisticsWithData:
    """Tests where the user has tasks and habits."""

    @pytest.mark.asyncio
    async def test_statistics_with_completed_tasks(
        self,
        full_client: "TestClient",
        async_session: AsyncSession,
    ) -> None:
        """Statistics shows completed/total tasks and percentage correctly."""
        user = await _create_user(async_session)
        today = date.today()
        yesterday = today - timedelta(days=1)

        # 2 completed, 1 not completed
        await _create_task(async_session, user, "Task 1", today, is_completed=True)
        await _create_task(async_session, user, "Task 2", today, is_completed=True)
        await _create_task(async_session, user, "Task 3", yesterday, is_completed=False)
        await _create_habit(async_session, user)

        with patch(
            "src.handlers.statistics.get_db",
            _mock_get_db_context(async_session),
        ):
            resp: Message = await full_client.send_callback(
                "main_menu:statistics",
                user_id=123456,
                message_text="🏠 Главное меню бота\nВыберите действие:",
            )

        text = resp.text
        assert "2 из 3" in text
        assert "67%" in text
        assert "1 задач" in text
        assert "Всего привычек: 1" in text

    @pytest.mark.asyncio
    async def test_statistics_shows_streak(
        self,
        full_client: "TestClient",
        async_session: AsyncSession,
    ) -> None:
        """Statistics shows the current streak of consecutive fully-completed days."""
        user = await _create_user(async_session)
        today = date.today()

        # Today: all completed → day counts toward streak
        await _create_task(async_session, user, "Task A", today, is_completed=True)
        await _create_task(async_session, user, "Task B", today, is_completed=True)

        with patch(
            "src.handlers.statistics.get_db",
            _mock_get_db_context(async_session),
        ):
            resp: Message = await full_client.send_callback(
                "main_menu:statistics",
                user_id=123456,
                message_text="🏠 Главное меню бота\nВыберите действие:",
            )

        text = resp.text
        assert "Текущая серия: 1 дн." in text

    @pytest.mark.asyncio
    async def test_statistics_streak_zero_when_broken(
        self,
        full_client: "TestClient",
        async_session: AsyncSession,
    ) -> None:
        """Streak is 0 when today has an incomplete task."""
        user = await _create_user(async_session)
        today = date.today()

        await _create_task(async_session, user, "Task A", today, is_completed=True)
        await _create_task(async_session, user, "Task B", today, is_completed=False)

        with patch(
            "src.handlers.statistics.get_db",
            _mock_get_db_context(async_session),
        ):
            resp: Message = await full_client.send_callback(
                "main_menu:statistics",
                user_id=123456,
                message_text="🏠 Главное меню бота\nВыберите действие:",
            )

        text = resp.text
        assert "Текущая серия: 0 дн." in text

    @pytest.mark.asyncio
    async def test_statistics_with_multiple_habits(
        self,
        full_client: "TestClient",
        async_session: AsyncSession,
    ) -> None:
        """Habit count is shown correctly."""
        user = await _create_user(async_session)
        await _create_habit(async_session, user, "Habit 1")
        await _create_habit(async_session, user, "Habit 2")
        await _create_habit(async_session, user, "Habit 3")

        with patch(
            "src.handlers.statistics.get_db",
            _mock_get_db_context(async_session),
        ):
            resp: Message = await full_client.send_callback(
                "main_menu:statistics",
                user_id=123456,
                message_text="🏠 Главное меню бота\nВыберите действие:",
            )

        text = resp.text
        assert "Всего привычек: 3" in text


# ---------------------------------------------------------------------------
# Tests: statistics with no data
# ---------------------------------------------------------------------------


class TestStatisticsNoData:
    """Tests where the user has no tasks or habits."""

    @pytest.mark.asyncio
    async def test_statistics_empty_user(
        self,
        full_client: "TestClient",
        async_session: AsyncSession,
    ) -> None:
        """New user with no data sees an appropriate message."""
        await _create_user(async_session)

        with patch(
            "src.handlers.statistics.get_db",
            _mock_get_db_context(async_session),
        ):
            resp: Message = await full_client.send_callback(
                "main_menu:statistics",
                user_id=123456,
                message_text="🏠 Главное меню бота\nВыберите действие:",
            )

        text = resp.text
        assert "нет задач и привычек" in text.lower()

    @pytest.mark.asyncio
    async def test_statistics_habits_only(
        self,
        full_client: "TestClient",
        async_session: AsyncSession,
    ) -> None:
        """User with habits but no tasks sees habit count."""
        user = await _create_user(async_session)
        await _create_habit(async_session, user, "Habit A")

        with patch(
            "src.handlers.statistics.get_db",
            _mock_get_db_context(async_session),
        ):
            resp: Message = await full_client.send_callback(
                "main_menu:statistics",
                user_id=123456,
                message_text="🏠 Главное меню бота\nВыберите действие:",
            )

        text = resp.text
        assert "0 из 0" in text
        assert "Всего привычек: 1" in text

    @pytest.mark.asyncio
    async def test_statistics_all_completed(
        self,
        full_client: "TestClient",
        async_session: AsyncSession,
    ) -> None:
        """When all tasks are completed, shows 100%."""
        user = await _create_user(async_session)
        today = date.today()

        await _create_task(async_session, user, "T1", today, is_completed=True)
        await _create_task(async_session, user, "T2", today, is_completed=True)
        await _create_task(async_session, user, "T3", today, is_completed=True)

        with patch(
            "src.handlers.statistics.get_db",
            _mock_get_db_context(async_session),
        ):
            resp: Message = await full_client.send_callback(
                "main_menu:statistics",
                user_id=123456,
                message_text="🏠 Главное меню бота\nВыберите действие:",
            )

        text = resp.text
        assert "3 из 3" in text
        assert "100%" in text
        assert "0 задач" in text
