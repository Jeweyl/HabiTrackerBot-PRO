"""Tests for the "New Habit" creation wizard handlers."""

from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
import pytest_asyncio
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Habit, User

if TYPE_CHECKING:
    from aiogram import Bot

    from tests.conftest import TestClient


# ---------------------------------------------------------------------------
# Fixture: a dispatcher with both habits and common routers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def full_dispatcher() -> Dispatcher:
    """Return a fresh Dispatcher with both habits and common routers.

    Both modules are reloaded before each test so their singleton routers
    can be attached to a new Dispatcher without "Router is already attached".
    """
    import src.handlers.common  # noqa: F811
    import src.handlers.habits  # noqa: F811

    importlib.reload(src.handlers.habits)
    importlib.reload(src.handlers.common)
    from src.handlers.common import router as common_router  # noqa: F811
    from src.handlers.habits import router as habits_router  # noqa: F811

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(habits_router)
    dp.include_router(common_router)
    return dp


@pytest_asyncio.fixture(scope="function")
async def full_client(
    test_bot: Bot,
    full_dispatcher: Dispatcher,
) -> "TestClient":
    """Provide a TestClient wired to the full dispatcher (habits + common)."""
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
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_habit_start(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that clicking "➕ Новая привычка" starts the wizard.

    The bot should prompt for a habit title and set the FSM state to
    ``NewHabitFSM.title``.
    """
    # Pre-create a user so the wizard can proceed
    user = User(telegram_id=123456, language="ru", timezone="UTC")
    async_session.add(user)
    await async_session.commit()

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        message = await full_client.send_callback("main_menu:new_habit")

    assert "Введите название привычки" in message.text


@pytest.mark.asyncio
async def test_full_wizard_flow(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify the complete happy path of the habit creation wizard.

    Steps: title → start_time → end_time → frequency → habit saved to DB.
    """
    # Pre-create a user
    user = User(telegram_id=123456, language="ru", timezone="UTC")
    async_session.add(user)
    await async_session.commit()

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        # Step 0: Click "➕ Новая привычка"
        msg = await full_client.send_callback("main_menu:new_habit")
        assert "Введите название привычки" in msg.text

        # Step 1: Enter title
        msg = await full_client.send_message("Утренняя пробежка")
        assert "Выберите время начала" in msg.text

        # Step 2: Select start time (07:00)
        msg = await full_client.send_callback("time:07:00")
        assert "Выберите время окончания" in msg.text

        # Step 3: Select end time (08:00) — strictly after start_time
        msg = await full_client.send_callback("time:08:00")
        assert "Выберите периодичность" in msg.text

        # Step 4: Select frequency (daily)
        msg = await full_client.send_callback("freq:daily")
        assert "Привычка успешно создана" in msg.text
        assert "Утренняя пробежка" in msg.text
        assert "07:00" in msg.text
        assert "08:00" in msg.text
        assert "Ежедневно" in msg.text

    # Verify the habit was persisted
    stmt = select(Habit).where(Habit.title == "Утренняя пробежка")
    result = await async_session.execute(stmt)
    habit = result.scalar_one()
    assert habit.user_id == user.id
    assert habit.start_time.strftime("%H:%M") == "07:00"
    assert habit.end_time.strftime("%H:%M") == "08:00"
    assert habit.frequency == "daily"


@pytest.mark.asyncio
async def test_cancel_during_wizard(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that cancelling the wizard clears state and shows the main menu.

    No habit should be persisted in the database.
    """
    # Pre-create a user
    user = User(telegram_id=123456, language="ru", timezone="UTC")
    async_session.add(user)
    await async_session.commit()

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        # Start the wizard
        await full_client.send_callback("main_menu:new_habit")

        # Enter a title
        await full_client.send_message("Тестовая привычка")

        # Cancel
        msg = await full_client.send_callback("nav:cancel")
        assert "Создание привычки отменено" in msg.text
        assert msg.reply_markup is not None

    # Verify no habit was created
    stmt = select(Habit).where(Habit.title == "Тестовая привычка")
    result = await async_session.execute(stmt)
    habits = result.scalars().all()
    assert len(habits) == 0


@pytest.mark.asyncio
async def test_empty_title_rejected(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that an empty or whitespace-only title is rejected.

    The bot should ask the user to try again without advancing the wizard.
    """
    # Pre-create a user
    user = User(telegram_id=123456, language="ru", timezone="UTC")
    async_session.add(user)
    await async_session.commit()

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        # Start the wizard
        await full_client.send_callback("main_menu:new_habit")

        # Send an empty title
        msg = await full_client.send_message("   ")
        assert "от 1 до 200 символов" in msg.text
        assert "Попробуйте ещё раз" in msg.text


# ---------------------------------------------------------------------------
# New tests for optional end_time and keyboard filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_time_keyboard_filters_by_start_time(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that after choosing start_time, the end_time keyboard hides
    times ≤ start_time but shows later times and the ``time:null`` option.
    """
    user = User(telegram_id=123456, language="ru", timezone="UTC")
    async_session.add(user)
    await async_session.commit()

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        # Start wizard and enter title
        await full_client.send_callback("main_menu:new_habit")
        await full_client.send_message("Чтение")

        # Choose start_time = 12:00
        msg = await full_client.send_callback("time:12:00")
        assert "Выберите время окончания" in msg.text

        # Inspect the keyboard
        keyboard = msg.reply_markup.inline_keyboard
        all_cb = {btn.callback_data for row in keyboard for btn in row}

        # Times ≤ 12:00 must NOT appear
        assert "time:11:00" not in all_cb
        assert "time:12:00" not in all_cb
        assert "time:00:00" not in all_cb

        # Times > 12:00 MUST appear
        assert "time:13:00" in all_cb
        assert "time:23:00" in all_cb

        # Special buttons must be present
        assert "time:null" in all_cb
        assert "nav:back" in all_cb
        assert "nav:cancel" in all_cb


@pytest.mark.asyncio
async def test_habit_with_null_end_time(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that selecting ``time:null`` creates a habit with end_time=None.

    The confirmation message should display "без ограничения по времени".
    """
    user = User(telegram_id=123456, language="ru", timezone="UTC")
    async_session.add(user)
    await async_session.commit()

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        # Start wizard
        await full_client.send_callback("main_menu:new_habit")
        await full_client.send_message("Медитация")

        # Select start_time = 09:00
        await full_client.send_callback("time:09:00")

        # Choose "Без времени"
        msg = await full_client.send_callback("time:null")
        assert "Выберите периодичность" in msg.text

        # Choose frequency = weekdays
        msg = await full_client.send_callback("freq:weekdays")
        assert "Привычка успешно создана" in msg.text
        assert "Медитация" in msg.text
        assert "без ограничения по времени" in msg.text
        assert "По будням" in msg.text

    # Verify habit was persisted with end_time = None
    stmt = select(Habit).where(Habit.title == "Медитация")
    result = await async_session.execute(stmt)
    habit = result.scalar_one()
    assert habit.end_time is None
    assert habit.frequency == "weekdays"


@pytest.mark.asyncio
async def test_end_time_not_greater_than_start_time_rejected(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that an end_time ≤ start_time is rejected with an error message.

    The bot should keep the user on the end_time step.
    """
    user = User(telegram_id=123456, language="ru", timezone="UTC")
    async_session.add(user)
    await async_session.commit()

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        # Start wizard
        await full_client.send_callback("main_menu:new_habit")
        await full_client.send_message("Йога")

        # Choose start_time = 12:00
        await full_client.send_callback("time:12:00")

        # Try to choose end_time = 10:00 (before start_time)
        msg = await full_client.send_callback("time:10:00")
        assert "должно быть позже" in msg.text

    # Verify no habit was persisted
    stmt = select(Habit).where(Habit.title == "Йога")
    result = await async_session.execute(stmt)
    habits = result.scalars().all()
    assert len(habits) == 0


@pytest.mark.asyncio
async def test_start_time_keyboard_has_no_null_option(
    full_client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Verify that the start_time keyboard does NOT include ``time:null``.

    The ``⏳ Без времени`` button is only shown for end-time selection.
    """
    user = User(telegram_id=123456, language="ru", timezone="UTC")
    async_session.add(user)
    await async_session.commit()

    with patch(
        "src.handlers.habits.get_db",
        side_effect=_mock_get_db_context(async_session),
    ):
        # Start wizard and enter title
        await full_client.send_callback("main_menu:new_habit")
        msg = await full_client.send_message("Бег")

        # Inspect the start_time keyboard
        keyboard = msg.reply_markup.inline_keyboard
        all_cb = {btn.callback_data for row in keyboard for btn in row}

        # time:null must NOT appear on the start-time selection screen
        assert "time:null" not in all_cb

        # Navigation buttons must be present
        assert "nav:back" in all_cb
        assert "nav:cancel" in all_cb
