"""Tests for statistics, settings, and help main menu buttons."""

from datetime import date, time

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import TestClient


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
    client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """The statistics button shows completed tasks count for the last 7 days."""
    user_id = await _ensure_user(async_session, 123456)
    today = date.today()

    # Create 2 completed tasks and 1 incomplete task in the last 7 days
    await _create_task(
        async_session, user_id=user_id, date_val=today,
        start=time(9, 0), end=time(10, 0), title="Done1",
    )
    await _create_task(
        async_session, user_id=user_id, date_val=today,
        start=time(10, 0), end=time(11, 0), title="Done2",
    )
    await _create_task(
        async_session, user_id=user_id, date_val=today,
        start=time(11, 0), end=time(12, 0), title="Pending",
    )

    # Mark first two as completed directly in DB
    from sqlalchemy import select, update

    from src.db.models import Task

    await async_session.execute(
        update(Task)
        .where(Task.title.in_(["Done1", "Done2"]))
        .values(is_completed=True)
    )
    await async_session.commit()

    msg = await client.send_callback("main_menu:statistics")
    assert "📊" in msg.text
    assert "Статистика" in msg.text
    assert "2" in msg.text  # completed count
    assert "3" in msg.text  # total count


@pytest.mark.asyncio
async def test_statistics_empty(
    client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """Statistics shows zero when there are no tasks."""
    await _ensure_user(async_session, 123456)

    msg = await client.send_callback("main_menu:statistics")
    assert "📊" in msg.text
    assert "0 из 0" in msg.text


# ===========================================================================
# Test: settings stub
# ===========================================================================


@pytest.mark.asyncio
async def test_settings_stub(
    client: "TestClient",
    async_session: AsyncSession,
) -> None:
    """The settings button shows a 'coming soon' message."""
    await _ensure_user(async_session, 123456)
    msg = await client.send_callback("main_menu:settings")
    assert "Настройки будут доступны" in msg.text
    assert "следующей версии" in msg.text
    assert msg.reply_markup is not None


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
