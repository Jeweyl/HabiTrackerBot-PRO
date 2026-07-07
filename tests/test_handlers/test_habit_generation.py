"""Tests for automatic task generation from habits."""

import importlib
from contextlib import asynccontextmanager
from datetime import date, time, timedelta
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, Message, Update, User as TgUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Habit, Task, User
from src.services.habit_generator import (
    generate_tasks_for_habit,
    lazy_generate_for_range,
)
from tests.conftest import MockTelegramSession

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXED_TODAY = date(2026, 7, 1)  # Wednesday


@pytest_asyncio.fixture(scope="function")
async def habits_dispatcher() -> Dispatcher:
    """Return a fresh Dispatcher with a fresh copy of the habits handler router."""
    import src.handlers.habits  # noqa: F811

    importlib.reload(src.handlers.habits)
    from src.handlers.habits import router as habits_router  # noqa: F811

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(habits_router)
    return dp


@pytest_asyncio.fixture(scope="function")
async def test_bot():
    """Return a Bot instance backed by MockTelegramSession."""
    session = MockTelegramSession()
    bot = Bot(token="123456:ABC-DEF1234ghik", session=session)
    return bot


class HabitTestClient:
    """Lightweight test client for habits handlers."""

    def __init__(self, bot, dp):
        self.bot = bot
        self.dp = dp

    async def send_callback(
        self,
        callback_data: str,
        user_id: int = 123456,
        message_text: str = "menu",
    ) -> Message:
        """Emulate a user tapping an inline button."""
        update = Update(
            update_id=2,
            callback_query=CallbackQuery(
                id="cb_1",
                from_user=TgUser(id=user_id, is_bot=False, first_name="Test"),
                chat_instance=str(user_id),
                data=callback_data,
                message=Message(
                    message_id=1,
                    date=0,
                    chat=Chat(id=user_id, type="private"),
                    text=message_text,
                ),
            ),
        )
        return await self._feed_and_get_answer(update, user_id)

    async def send_message(self, text: str, user_id: int = 123456) -> Message:
        """Emulate a user sending a text message."""
        update = Update(
            update_id=1,
            message=Message(
                message_id=1,
                date=0,
                chat=Chat(id=user_id, type="private"),
                from_user=TgUser(id=user_id, is_bot=False, first_name="Test"),
                text=text,
            ),
        )
        return await self._feed_and_get_answer(update, user_id)

    async def _feed_and_get_answer(self, update, user_id):
        session = self.bot.session
        session.captured.clear()
        await self.dp.feed_update(self.bot, update)
        if not session.captured:
            raise RuntimeError("No message was sent by the handler")
        return session.captured[-1]


@pytest_asyncio.fixture(scope="function")
async def habit_client(
    test_bot,
    habits_dispatcher,
    async_session: AsyncSession,
    monkeypatch,
):
    """Provide a HabitTestClient with patched get_db."""

    @asynccontextmanager
    async def _fake_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield async_session

    import src.handlers.habits as habits_module
    import src.services.habit_generator as gen_module

    monkeypatch.setattr(habits_module, "get_db", _fake_get_db)
    monkeypatch.setattr(gen_module, "get_db", _fake_get_db)

    # Create a test user
    user = User(telegram_id=123456, language="ru", timezone="UTC")
    async_session.add(user)
    await async_session.commit()
    return HabitTestClient(bot=test_bot, dp=habits_dispatcher)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _ensure_user(session, telegram_id: int) -> int:
    """Return the internal user.id, creating the user if needed."""
    stmt = select(User).where(User.telegram_id == telegram_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        user = User(telegram_id=telegram_id, language="ru", timezone="UTC")
        session.add(user)
        await session.commit()
    return user.id


async def _create_habit(
    session,
    *,
    user_id,
    title="Test Habit",
    start_time=time(10, 0),
    end_time=time(12, 0),
    frequency="daily",
) -> Habit:
    """Create and persist a Habit, returning it."""
    habit = Habit(
        user_id=user_id,
        title=title,
        start_time=start_time,
        end_time=end_time,
        frequency=frequency,
    )
    session.add(habit)
    await session.commit()
    return habit


# ===========================================================================
# Direct unit tests for generate_tasks_for_habit
# ===========================================================================


@pytest.mark.asyncio
async def test_daily_generates_30_tasks(habit_client, async_session) -> None:
    """Daily habit generates exactly 30 tasks, one per day."""
    user_id = await _ensure_user(async_session, 123456)
    habit = await _create_habit(async_session, user_id=user_id, frequency="daily")

    await generate_tasks_for_habit(
        habit.id, days_ahead=30, today_override=FIXED_TODAY,
    )

    stmt = select(Task).where(Task.habit_id == habit.id).order_by(Task.date)
    result = await async_session.execute(stmt)
    tasks = result.scalars().all()
    assert len(tasks) == 30

    # Verify consecutive dates starting from FIXED_TODAY
    for i, task in enumerate(tasks):
        assert task.date == FIXED_TODAY + timedelta(days=i)
        assert task.title == "Test Habit"
        assert task.start_time == time(10, 0)
        assert task.end_time == time(12, 0)
        assert task.is_completed is False
        assert task.is_placeholder is False


@pytest.mark.asyncio
async def test_weekdays_only_mon_fri(habit_client, async_session) -> None:
    """Weekdays habit generates tasks only on Monday–Friday."""
    user_id = await _ensure_user(async_session, 123456)
    habit = await _create_habit(
        async_session, user_id=user_id, frequency="weekdays",
    )

    await generate_tasks_for_habit(
        habit.id, days_ahead=30, today_override=FIXED_TODAY,
    )

    stmt = select(Task).where(Task.habit_id == habit.id).order_by(Task.date)
    result = await async_session.execute(stmt)
    tasks = result.scalars().all()

    weekdays_count = sum(
        1
        for offset in range(30)
        if (FIXED_TODAY + timedelta(days=offset)).weekday() < 5
    )
    assert len(tasks) == weekdays_count

    for task in tasks:
        assert task.date.weekday() < 5  # Mon–Fri only
        assert task.title == "Test Habit"


@pytest.mark.asyncio
async def test_weekends_only_sat_sun(habit_client, async_session) -> None:
    """Weekends habit generates tasks only on Saturday–Sunday."""
    user_id = await _ensure_user(async_session, 123456)
    habit = await _create_habit(
        async_session, user_id=user_id, frequency="weekends",
    )

    await generate_tasks_for_habit(
        habit.id, days_ahead=30, today_override=FIXED_TODAY,
    )

    stmt = select(Task).where(Task.habit_id == habit.id).order_by(Task.date)
    result = await async_session.execute(stmt)
    tasks = result.scalars().all()

    weekends_count = sum(
        1
        for offset in range(30)
        if (FIXED_TODAY + timedelta(days=offset)).weekday() >= 5
    )
    assert len(tasks) == weekends_count

    for task in tasks:
        assert task.date.weekday() >= 5  # Sat–Sun only
        assert task.title == "Test Habit"


@pytest.mark.asyncio
async def test_no_duplicates(habit_client, async_session) -> None:
    """Calling generate_tasks_for_habit twice does not create duplicates."""
    user_id = await _ensure_user(async_session, 123456)
    habit = await _create_habit(async_session, user_id=user_id, frequency="daily")

    await generate_tasks_for_habit(
        habit.id, days_ahead=30, today_override=FIXED_TODAY,
    )
    await generate_tasks_for_habit(
        habit.id, days_ahead=30, today_override=FIXED_TODAY,
    )

    stmt = select(Task).where(Task.habit_id == habit.id)
    result = await async_session.execute(stmt)
    tasks = result.scalars().all()
    assert len(tasks) == 30  # Still 30, no duplicates


@pytest.mark.asyncio
async def test_null_end_time(habit_client, async_session) -> None:
    """Habit with end_time=None generates tasks with end_time=None."""
    user_id = await _ensure_user(async_session, 123456)
    habit = await _create_habit(
        async_session,
        user_id=user_id,
        start_time=time(9, 0),
        end_time=None,
        frequency="daily",
    )

    await generate_tasks_for_habit(
        habit.id, days_ahead=30, today_override=FIXED_TODAY,
    )

    stmt = select(Task).where(Task.habit_id == habit.id)
    result = await async_session.execute(stmt)
    tasks = result.scalars().all()
    assert len(tasks) == 30
    for task in tasks:
        assert task.end_time is None


# ===========================================================================
# Test: lazy generation on view schedule
# ===========================================================================


@pytest.mark.asyncio
async def test_lazy_generation_on_view(habit_client, async_session) -> None:
    """Viewing a schedule triggers lazy generation for that date."""
    user_id = await _ensure_user(async_session, 123456)
    await _create_habit(
        async_session, user_id=user_id, frequency="daily",
    )

    target_date = FIXED_TODAY + timedelta(days=5)

    # No tasks should exist yet for target_date
    stmt = select(Task).where(Task.date == target_date)
    result = await async_session.execute(stmt)
    assert result.scalars().first() is None

    # Trigger lazy generation
    await lazy_generate_for_range(user_id, target_date, days=1)

    # Now a task should exist on target_date
    result = await async_session.execute(stmt)
    task = result.scalars().first()
    assert task is not None
    assert task.date == target_date
    assert task.title == "Test Habit"


@pytest.mark.asyncio
async def test_lazy_generation_conflict(habit_client, async_session) -> None:
    """Lazy generation does NOT create task if slot is occupied."""
    user_id = await _ensure_user(async_session, 123456)
    habit = await _create_habit(
        async_session,
        user_id=user_id,
        start_time=time(10, 0),
        end_time=time(12, 0),
        frequency="daily",
    )

    target_date = FIXED_TODAY + timedelta(days=3)

    # Create a manual task in the same slot
    manual_task = Task(
        user_id=user_id,
        habit_id=None,
        title="Manual",
        date=target_date,
        start_time=time(10, 0),
        end_time=time(12, 0),
    )
    async_session.add(manual_task)
    await async_session.commit()

    # Trigger lazy generation — should skip due to conflict
    await lazy_generate_for_range(user_id, target_date, days=1)

    # Verify habit task was NOT created
    stmt = select(Task).where(
        Task.habit_id == habit.id, Task.date == target_date,
    )
    result = await async_session.execute(stmt)
    assert result.scalar_one_or_none() is None

    # Manual task still exists
    stmt2 = select(Task).where(Task.id == manual_task.id)
    result2 = await async_session.execute(stmt2)
    assert result2.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_lazy_generation_skips_existing(habit_client, async_session) -> None:
    """Lazy generation skips dates where a task already exists."""
    user_id = await _ensure_user(async_session, 123456)
    habit = await _create_habit(
        async_session, user_id=user_id, frequency="daily",
    )

    target_date = FIXED_TODAY + timedelta(days=7)

    # Pre-create a task for the habit on that date
    existing = Task(
        user_id=user_id,
        habit_id=habit.id,
        title="Already Exists",
        date=target_date,
        start_time=time(10, 0),
        end_time=time(12, 0),
    )
    async_session.add(existing)
    await async_session.commit()

    await lazy_generate_for_range(user_id, target_date, days=1)

    # Verify still exactly 1 task (the existing one)
    stmt = select(Task).where(
        Task.habit_id == habit.id, Task.date == target_date,
    )
    result = await async_session.execute(stmt)
    tasks = result.scalars().all()
    assert len(tasks) == 1
    assert tasks[0].title == "Already Exists"


# ===========================================================================
# Test: regeneration on frequency edit
# ===========================================================================


@pytest.mark.asyncio
async def test_edit_frequency_regenerates_tasks(
    habit_client, async_session,
) -> None:
    """After changing frequency, old tasks are deleted and new ones created."""
    from sqlalchemy import delete

    user_id = await _ensure_user(async_session, 123456)
    habit = await _create_habit(
        async_session, user_id=user_id, frequency="daily",
    )

    # Generate initial daily tasks
    await generate_tasks_for_habit(
        habit.id, days_ahead=30, today_override=FIXED_TODAY,
    )

    # Verify 30 daily tasks
    stmt = select(Task).where(Task.habit_id == habit.id)
    result = await async_session.execute(stmt)
    initial_tasks = result.scalars().all()
    assert len(initial_tasks) == 30

    # Simulate frequency edit: delete old + regenerate with weekdays
    await async_session.execute(delete(Task).where(Task.habit_id == habit.id))
    await async_session.commit()
    habit.frequency = "weekdays"
    await async_session.commit()
    await generate_tasks_for_habit(
        habit.id, days_ahead=30, today_override=FIXED_TODAY,
    )

    # Verify new count matches weekdays
    result = await async_session.execute(stmt)
    new_tasks = result.scalars().all()
    weekdays_count = sum(
        1
        for offset in range(30)
        if (FIXED_TODAY + timedelta(days=offset)).weekday() < 5
    )
    assert len(new_tasks) == weekdays_count
    for task in new_tasks:
        assert task.date.weekday() < 5