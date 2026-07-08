"""Tests for statistics, settings, and help main menu buttons."""

import importlib
from contextlib import asynccontextmanager
from datetime import date, time

import pytest
import pytest_asyncio
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import TestClient


# ---------------------------------------------------------------------------
# Fixtures for tests that need the statistics router
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def stats_dispatcher() -> Dispatcher:
    """Return a Dispatcher with statistics + common routers."""
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
async def stats_client(
    test_bot,
    stats_dispatcher: Dispatcher,
) -> TestClient:
    """Provide a TestClient wired to the statistics dispatcher."""
    from tests.conftest import TestClient

    return TestClient(bot=test_bot, dp=stats_dispatcher)


def _mock_get_db_context(async_session: AsyncSession):
    """Return a context manager factory that yields the test session."""

    @asynccontextmanager
    async def _mock_get_db():
        yield async_session

    return _mock_get_db


# ---------------------------------------------------------------------------
# Fixture for settings tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def settings_dispatcher() -> Dispatcher:
    """Return a Dispatcher with settings + common routers."""
    import src.handlers.common
    import src.handlers.settings

    importlib.reload(src.handlers.settings)
    importlib.reload(src.handlers.common)
    from src.handlers.common import router as common_router
    from src.handlers.settings import router as settings_router

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(settings_router)
    dp.include_router(common_router)
    return dp


@pytest_asyncio.fixture(scope="function")
async def settings_client(
    test_bot,
    settings_dispatcher: Dispatcher,
) -> TestClient:
    """Provide a TestClient wired to the settings dispatcher."""
    from tests.conftest import TestClient

    return TestClient(bot=test_bot, dp=settings_dispatcher)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _ensure_user(session, telegram_id: int) -> int:
    """Return the internal user.id, creating the user if needed."""
    from sqlalchemy import select

    from src.db.models import User

    stmt = select(User).where(User.telegram_id == telegram_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        user = User(telegram_id=telegram_id, language="ru", timezone="UTC")
        session.add(user)
        await session.commit()
    return user.id


async def _create_task(session, *, user_id, date_val, start, end, title="Test"):
    """Create and persist a Task, returning it."""
    from src.db.models import Task

    task = Task(
        user_id=user_id,
        habit_id=None,
        title=title,
        date=date_val,
        start_time=start,
        end_time=end,
        is_completed=False,
    )
    session.add(task)
    await session.commit()
    return task


# ===========================================================================
# Test: statistics
# ===========================================================================


@pytest.mark.asyncio
async def test_statistics_shows_counts(
    stats_client: TestClient,
    async_session: AsyncSession,
) -> None:
    """The statistics button shows completed tasks count for the last 7 days."""
    from unittest.mock import patch

    user_id = await _ensure_user(async_session, 123456)
    today = date.today()

    # Create 2 completed tasks and 1 incomplete task in the last 7 days
    await _create_task(
        async_session,
        user_id=user_id,
        date_val=today,
        start=time(9, 0),
        end=time(10, 0),
        title="Done1",
    )
    await _create_task(
        async_session,
        user_id=user_id,
        date_val=today,
        start=time(10, 0),
        end=time(11, 0),
        title="Done2",
    )
    await _create_task(
        async_session,
        user_id=user_id,
        date_val=today,
        start=time(11, 0),
        end=time(12, 0),
        title="Pending",
    )

    # Mark first two as completed directly in DB
    from sqlalchemy import update

    from src.db.models import Task

    await async_session.execute(
        update(Task).where(Task.title.in_(["Done1", "Done2"])).values(is_completed=True)
    )
    await async_session.commit()

    with patch(
        "src.handlers.statistics.get_db",
        _mock_get_db_context(async_session),
    ):
        msg = await stats_client.send_callback("main_menu:statistics")
    assert "статистика" in msg.text.lower()
    assert "2 из 3" in msg.text  # completed / total
    assert "67%" in msg.text
    assert "1 задач" in msg.text  # missed


@pytest.mark.asyncio
async def test_statistics_empty(
    stats_client: TestClient,
    async_session: AsyncSession,
) -> None:
    """Statistics shows a message when there are no tasks or habits."""
    from unittest.mock import patch

    await _ensure_user(async_session, 123456)

    with patch(
        "src.handlers.statistics.get_db",
        _mock_get_db_context(async_session),
    ):
        msg = await stats_client.send_callback("main_menu:statistics")
    assert "Статистика" in msg.text
    assert "нет задач и привычек" in msg.text.lower()


# ===========================================================================
# Test: settings
# ===========================================================================


@pytest.mark.asyncio
async def test_settings_stub(
    settings_client: TestClient,
    async_session: AsyncSession,
) -> None:
    """The settings button shows the real settings menu."""
    from unittest.mock import patch

    await _ensure_user(async_session, 123456)

    with patch(
        "src.handlers.settings.get_db",
        _mock_get_db_context(async_session),
    ):
        msg = await settings_client.send_callback("main_menu:settings")
    assert "Настройки" in msg.text
    assert msg.reply_markup is not None
    rmk = str(msg.reply_markup)
    assert "settings:language" in rmk
    assert "settings:timezone" in rmk
    assert "settings:reminder_time" in rmk
    assert "settings:check_interval" in rmk


# ===========================================================================
# Test: help
# ===========================================================================


@pytest.mark.asyncio
async def test_help_shows_instructions(
    client: "TestClient",
) -> None:
    """The help button is handled (either by AI assistant or fallback)."""
    msg = await client.send_callback("main_menu:help")
    assert msg.text is not None
