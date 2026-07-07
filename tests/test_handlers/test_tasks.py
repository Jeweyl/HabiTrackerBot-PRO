"""Tests for task creation, calendar navigation, and schedule viewing."""

import importlib
from contextlib import asynccontextmanager
from datetime import date, time
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, Message, Update, User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Task, User
from tests.conftest import MockTelegramSession


# ---------------------------------------------------------------------------
# Fixtures — isolated dispatcher with tasks_router only
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def tasks_dispatcher() -> Dispatcher:
    """Return a fresh Dispatcher with a fresh copy of the tasks handler router."""
    import src.handlers.tasks  # noqa: F811

    importlib.reload(src.handlers.tasks)
    from src.handlers.tasks import router as tasks_router  # noqa: F811

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(tasks_router)
    return dp


@pytest_asyncio.fixture(scope="function")
async def test_bot():
    """Return a Bot instance backed by MockTelegramSession."""
    session = MockTelegramSession()
    from aiogram import Bot

    bot = Bot(token="123456:ABC-DEF1234ghik", session=session)
    return bot


class TasksTestClient:
    """Lightweight test client for tasks handlers."""

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
        session = self.bot.session  # MockTelegramSession
        session.captured.clear()
        await self.dp.feed_update(self.bot, update)
        if not session.captured:
            raise RuntimeError("No message was sent by the handler")
        return session.captured[-1]


@pytest_asyncio.fixture(scope="function")
async def client(
    test_bot,
    tasks_dispatcher,
    async_session: AsyncSession,
    monkeypatch,
):
    """Provide a TasksTestClient with test DB session patched into handlers.

    Patches ``src.handlers.tasks.get_db`` so that all handler code uses
    the in-memory SQLite session instead of the real PostgreSQL connection.
    A test user is pre-created in the test database.
    """
    # Patch get_db in the tasks module to yield the test session
    @asynccontextmanager
    async def _fake_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield async_session

    import src.handlers.tasks as tasks_module

    monkeypatch.setattr(tasks_module, "get_db", _fake_get_db)

    # Create a test user
    user = User(telegram_id=123456, language="ru", timezone="UTC")
    async_session.add(user)
    await async_session.commit()
    return TasksTestClient(bot=test_bot, dp=tasks_dispatcher)


# ---------------------------------------------------------------------------
# Helper — create a user for a different telegram_id
# ---------------------------------------------------------------------------


async def _ensure_user(session, telegram_id: int) -> int:
    """Return the internal user.id, creating the user if needed."""
    from sqlalchemy import select

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
    task = Task(
        user_id=user_id,
        habit_id=None,
        title=title,
        date=date_val,
        start_time=start,
        end_time=end,
    )
    session.add(task)
    await session.commit()
    return task


# ===========================================================================
# Test: calendar month navigation
# ===========================================================================


@pytest.mark.asyncio
async def test_calendar_month_navigation(client) -> None:
    """Switching months updates the calendar message."""
    # Start task creation → calendar appears
    msg = await client.send_callback("main_menu:new_task")
    assert "Выберите дату" in msg.text
    assert msg.reply_markup is not None

    # Navigate to next month
    msg = await client.send_callback("calendar:month:2026:8", message_text="calendar")
    assert msg.reply_markup is not None

    # Navigate to previous month
    msg = await client.send_callback("calendar:month:2026:6", message_text="calendar")
    assert msg.reply_markup is not None


# ===========================================================================
# Test: calendar day selection
# ===========================================================================


@pytest.mark.asyncio
async def test_calendar_day_selection(client) -> None:
    """Selecting a day shows the day keyboard."""
    # Start task creation
    await client.send_callback("main_menu:new_task")

    # Select a day
    msg = await client.send_callback("calendar:day:2026-07-15", message_text="calendar")
    assert "Выбран день" in msg.text
    assert "2026-07-15" in msg.text
    assert msg.reply_markup is not None
    # Check buttons exist (keyboard is not just text)
    assert any(
        btn.text == "📅 Добавить задачу"
        for row in msg.reply_markup.inline_keyboard
        for btn in row
    )


# ===========================================================================
# Test: full task creation flow (happy path with end_time)
# ===========================================================================


@pytest.mark.asyncio
async def test_full_task_creation_with_end_time(
    client, async_session,
) -> None:
    """Create a task end-to-end: date → title → start → end → confirm → save."""
    # 1. Start wizard → calendar
    await client.send_callback("main_menu:new_task")

    # 2. Pick a day → day keyboard
    await client.send_callback("calendar:day:2026-07-15", message_text="calendar")

    # 3. Click "📅 Добавить задачу" → prompt for title
    await client.send_callback("task:add:2026-07-15", message_text="day view")

    # 4. Enter title
    msg = await client.send_message("Test Task")
    assert "Выберите время начала" in msg.text

    # 5. Choose start time 10:00
    msg = await client.send_callback("time:10:00", message_text="start time")
    assert "Выберите время окончания" in msg.text

    # 6. Choose end time 12:00
    msg = await client.send_callback("time:12:00", message_text="end time")
    assert "Подтвердите создание задачи" in msg.text
    assert "Test Task" in msg.text
    assert "10:00" in msg.text
    assert "12:00" in msg.text

    # 7. Confirm → save (sends 2 messages: success + schedule; we get the last one)
    msg = await client.send_callback("task:save", message_text="confirm")
    # The last message is the schedule showing the newly created task
    assert "Test Task" in msg.text
    assert "10:00" in msg.text

    # 8. Verify task in DB
    from sqlalchemy import select

    stmt = select(Task).where(Task.date == date(2026, 7, 15))
    result = await async_session.execute(stmt)
    tasks = result.scalars().all()
    assert len(tasks) == 1
    assert tasks[0].title == "Test Task"
    assert tasks[0].start_time == time(10, 0)
    assert tasks[0].end_time == time(12, 0)


# ===========================================================================
# Test: task without end_time (end_time=None)
# ===========================================================================


@pytest.mark.asyncio
async def test_task_without_end_time(client, async_session) -> None:
    """Create a task with end_time=None (open-ended)."""
    await client.send_callback("main_menu:new_task")
    await client.send_callback("calendar:day:2026-07-20", message_text="calendar")
    await client.send_callback("task:add:2026-07-20", message_text="day view")
    await client.send_message("Open-ended Task")
    await client.send_callback("time:14:00", message_text="start time")
    # Choose "Без времени" (null)
    msg = await client.send_callback("time:null", message_text="end time")
    assert "без окончания" in msg.text

    # Confirm (sends 2 messages: success + schedule)
    msg = await client.send_callback("task:save", message_text="confirm")
    # The last message is the schedule showing the newly created task
    assert "Open-ended Task" in msg.text
    assert "без окончания" in msg.text

    # Verify in DB
    from sqlalchemy import select

    stmt = select(Task).where(Task.date == date(2026, 7, 20))
    result = await async_session.execute(stmt)
    tasks = result.scalars().all()
    assert len(tasks) == 1
    assert tasks[0].end_time is None


# ===========================================================================
# Test: time conflict — concrete end_time
# ===========================================================================


@pytest.mark.asyncio
async def test_conflict_with_concrete_end_time(
    client, async_session,
) -> None:
    """Adding a task that overlaps an existing one should fail."""
    # Pre-create a task 09:00–11:00
    user_id = await _ensure_user(async_session, 123456)
    await _create_task(
        async_session,
        user_id=user_id,
        date_val=date(2026, 8, 1),
        start=time(9, 0),
        end=time(11, 0),
        title="Existing",
    )

    # Try to add 10:00–12:00 (overlaps)
    await client.send_callback("main_menu:new_task")
    await client.send_callback("calendar:day:2026-08-01", message_text="calendar")
    await client.send_callback("task:add:2026-08-01", message_text="day view")
    await client.send_message("Conflicting Task")
    await client.send_callback("time:10:00", message_text="start time")
    await client.send_callback("time:12:00", message_text="end time")
    # Confirm → should see conflict error
    msg = await client.send_callback("task:save", message_text="confirm")
    assert "Конфликт" in msg.text

    # Verify only 1 task remains
    from sqlalchemy import select

    stmt = select(Task).where(Task.date == date(2026, 8, 1))
    result = await async_session.execute(stmt)
    tasks = result.scalars().all()
    assert len(tasks) == 1


# ===========================================================================
# Test: time conflict — open-ended existing task
# ===========================================================================


@pytest.mark.asyncio
async def test_conflict_with_open_ended_task(
    client, async_session,
) -> None:
    """Adding a task that overlaps an open-ended existing task should fail."""
    # Pre-create an open-ended task at 09:00
    user_id = await _ensure_user(async_session, 123456)
    await _create_task(
        async_session,
        user_id=user_id,
        date_val=date(2026, 8, 2),
        start=time(9, 0),
        end=None,
        title="Endless",
    )

    # Try to add 10:00–12:00 (overlaps with open-ended)
    await client.send_callback("main_menu:new_task")
    await client.send_callback("calendar:day:2026-08-02", message_text="calendar")
    await client.send_callback("task:add:2026-08-02", message_text="day view")
    await client.send_message("Should Conflict")
    await client.send_callback("time:10:00", message_text="start time")
    await client.send_callback("time:12:00", message_text="end time")
    msg = await client.send_callback("task:save", message_text="confirm")
    assert "Конфликт" in msg.text

    # Verify only 1 task
    from sqlalchemy import select

    stmt = select(Task).where(Task.date == date(2026, 8, 2))
    result = await async_session.execute(stmt)
    tasks = result.scalars().all()
    assert len(tasks) == 1


# ===========================================================================
# Test: non-overlapping task — no conflict
# ===========================================================================


@pytest.mark.asyncio
async def test_non_overlapping_no_conflict(client, async_session) -> None:
    """Adding a task that does NOT overlap should succeed."""
    # Pre-create a task 09:00–10:00
    user_id = await _ensure_user(async_session, 123456)
    await _create_task(
        async_session,
        user_id=user_id,
        date_val=date(2026, 8, 3),
        start=time(9, 0),
        end=time(10, 0),
        title="Morning",
    )

    # Add 10:00–11:00 (touching but not overlapping)
    await client.send_callback("main_menu:new_task")
    await client.send_callback("calendar:day:2026-08-03", message_text="calendar")
    await client.send_callback("task:add:2026-08-03", message_text="day view")
    await client.send_message("Afternoon")
    await client.send_callback("time:10:00", message_text="start time")
    await client.send_callback("time:11:00", message_text="end time")
    msg = await client.send_callback("task:save", message_text="confirm")
    # The last message is the schedule showing both tasks
    assert "Afternoon" in msg.text
    assert "Morning" in msg.text

    # Verify 2 tasks
    from sqlalchemy import select

    stmt = select(Task).where(Task.date == date(2026, 8, 3))
    result = await async_session.execute(stmt)
    tasks = result.scalars().all()
    assert len(tasks) == 2


# ===========================================================================
# Test: view empty schedule
# ===========================================================================


@pytest.mark.asyncio
async def test_view_empty_schedule(client) -> None:
    """Viewing a day with no tasks shows the empty message."""
    msg = await client.send_callback("task:view:2026-12-25", message_text="day view")
    assert "На этот день задач нет." in msg.text


# ===========================================================================
# Test: view schedule with tasks
# ===========================================================================


@pytest.mark.asyncio
async def test_view_schedule_with_tasks(client, async_session) -> None:
    """Viewing a day with tasks shows them in chronological order."""
    user_id = await _ensure_user(async_session, 123456)
    await _create_task(
        async_session,
        user_id=user_id,
        date_val=date(2026, 9, 1),
        start=time(10, 0),
        end=time(11, 0),
        title="Second",
    )
    await _create_task(
        async_session,
        user_id=user_id,
        date_val=date(2026, 9, 1),
        start=time(8, 0),
        end=time(9, 0),
        title="First",
    )

    msg = await client.send_callback("task:view:2026-09-01", message_text="day view")
    assert "First" in msg.text
    assert "Second" in msg.text
    # "First" should come before "Second" by start_time
    assert msg.text.index("First") < msg.text.index("Second")


# ===========================================================================
# Test: cancel during task creation
# ===========================================================================


@pytest.mark.asyncio
async def test_cancel_during_title_step(client) -> None:
    """Cancelling while entering the title returns to the main menu."""
    await client.send_callback("main_menu:new_task")
    await client.send_callback("calendar:day:2026-07-15", message_text="calendar")
    await client.send_callback("task:add:2026-07-15", message_text="day view")
    # We're in title step — cancel
    msg = await client.send_callback("nav:cancel", message_text="type title")
    assert "отменено" in msg.text.lower()


@pytest.mark.asyncio
async def test_cancel_during_start_time_step(client) -> None:
    """Cancelling while selecting start_time returns to the main menu."""
    await client.send_callback("main_menu:new_task")
    await client.send_callback("calendar:day:2026-07-15", message_text="calendar")
    await client.send_callback("task:add:2026-07-15", message_text="day view")
    await client.send_message("Test Task")
    # We're in start_time step — cancel
    msg = await client.send_callback("nav:cancel", message_text="start time")
    assert "отменено" in msg.text.lower()


# ===========================================================================
# Test: title validation
# ===========================================================================


@pytest.mark.asyncio
async def test_title_validation_empty(client) -> None:
    """Empty title should be rejected."""
    await client.send_callback("main_menu:new_task")
    await client.send_callback("calendar:day:2026-07-15", message_text="calendar")
    await client.send_callback("task:add:2026-07-15", message_text="day view")
    msg = await client.send_message("")
    assert "⚠️" in msg.text


@pytest.mark.asyncio
async def test_title_validation_too_long(client) -> None:
    """Title longer than 200 chars should be rejected."""
    await client.send_callback("main_menu:new_task")
    await client.send_callback("calendar:day:2026-07-15", message_text="calendar")
    await client.send_callback("task:add:2026-07-15", message_text="day view")
    msg = await client.send_message("A" * 201)
    assert "⚠️" in msg.text


# ===========================================================================
# Test: end_time <= start_time
# ===========================================================================


@pytest.mark.asyncio
async def test_end_time_before_start_time(client) -> None:
    """Selecting end_time <= start_time should show an error."""
    await client.send_callback("main_menu:new_task")
    await client.send_callback("calendar:day:2026-07-15", message_text="calendar")
    await client.send_callback("task:add:2026-07-15", message_text="day view")
    await client.send_message("Test")
    await client.send_callback("time:14:00", message_text="start time")
    # Choose end_time = 10:00 (before start)
    msg = await client.send_callback("time:10:00", message_text="end time")
    assert "позже" in msg.text.lower()


# ===========================================================================
# Test: back navigation from confirm to end_time
# ===========================================================================


@pytest.mark.asyncio
async def test_back_from_confirm_to_end_time(client) -> None:
    """Back button on confirm step returns to end_time selection."""
    await client.send_callback("main_menu:new_task")
    await client.send_callback("calendar:day:2026-07-15", message_text="calendar")
    await client.send_callback("task:add:2026-07-15", message_text="day view")
    await client.send_message("Test")
    await client.send_callback("time:10:00", message_text="start time")
    await client.send_callback("time:12:00", message_text="end time")
    # We're on confirm step — go back
    msg = await client.send_callback("nav:back", message_text="confirm")
    assert "Выберите время окончания" in msg.text