"""Tests for check-in eligibility logic and process_checkins service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Task, User
from src.services.checkin_service import is_checkin_due, process_checkins
from src.utils.timezone import local_now, parse_timezone_offset


# ---------------------------------------------------------------------------
# Helpers / fakes for pure eligibility tests
# ---------------------------------------------------------------------------


@dataclass
class FakeTask:
    """Lightweight stand-in for Task used by pure is_checkin_due tests."""

    date: date
    start_time: time
    is_completed: bool = False
    is_placeholder: bool = False
    last_checkin_at: Optional[datetime] = None
    checkin_snooze_until: Optional[datetime] = None



def _local_dt(
    day: date,
    hour: int,
    minute: int = 0,
    *,
    offset_hours: int = 0,
) -> datetime:
    """Build a timezone-aware local datetime."""
    tz = timezone(timedelta(hours=offset_hours))
    return datetime(
        day.year, day.month, day.day, hour, minute, tzinfo=tz
    )


# ---------------------------------------------------------------------------
# Pure: is_checkin_due
# ---------------------------------------------------------------------------


class TestIsCheckinDue:
    """Unit tests for pure check-in eligibility."""

    def test_due_first_checkin_after_start(self) -> None:
        """Incomplete task with start_time passed and no last_checkin → due."""
        day = date(2026, 7, 12)
        task = FakeTask(date=day, start_time=time(9, 0))
        local_dt = _local_dt(day, 10, 0)
        assert is_checkin_due(task, local_dt=local_dt, interval_minutes=15) is True

    def test_not_due_before_start_time(self) -> None:
        """Task whose start_time is still in the future is not due."""
        day = date(2026, 7, 12)
        task = FakeTask(date=day, start_time=time(14, 0))
        local_dt = _local_dt(day, 10, 0)
        assert is_checkin_due(task, local_dt=local_dt, interval_minutes=15) is False

    def test_not_due_when_completed(self) -> None:
        """Completed tasks never receive check-ins."""
        day = date(2026, 7, 12)
        task = FakeTask(date=day, start_time=time(9, 0), is_completed=True)
        local_dt = _local_dt(day, 10, 0)
        assert is_checkin_due(task, local_dt=local_dt, interval_minutes=15) is False

    def test_not_due_when_placeholder(self) -> None:
        """Placeholder (ЗАНЯТ) tasks are skipped."""
        day = date(2026, 7, 12)
        task = FakeTask(date=day, start_time=time(9, 0), is_placeholder=True)
        local_dt = _local_dt(day, 10, 0)
        assert is_checkin_due(task, local_dt=local_dt, interval_minutes=15) is False

    def test_not_due_wrong_date(self) -> None:
        """Tasks scheduled for another day are not due."""
        day = date(2026, 7, 12)
        task = FakeTask(date=date(2026, 7, 11), start_time=time(9, 0))
        local_dt = _local_dt(day, 10, 0)
        assert is_checkin_due(task, local_dt=local_dt, interval_minutes=15) is False

    def test_anti_spam_within_interval(self) -> None:
        """Recent last_checkin_at blocks re-send inside the interval."""
        day = date(2026, 7, 12)
        local_dt = _local_dt(day, 10, 0, offset_hours=3)
        last = local_dt - timedelta(minutes=5)
        task = FakeTask(
            date=day,
            start_time=time(9, 0),
            last_checkin_at=last.astimezone(timezone.utc),
        )
        assert is_checkin_due(task, local_dt=local_dt, interval_minutes=15) is False

    def test_anti_spam_after_interval(self) -> None:
        """last_checkin_at older than interval allows another check-in."""
        day = date(2026, 7, 12)
        local_dt = _local_dt(day, 10, 0, offset_hours=3)
        last = local_dt - timedelta(minutes=20)
        task = FakeTask(
            date=day,
            start_time=time(9, 0),
            last_checkin_at=last.astimezone(timezone.utc),
        )
        assert is_checkin_due(task, local_dt=local_dt, interval_minutes=15) is True

    def test_interval_zero_disables(self) -> None:
        """interval_minutes <= 0 disables check-ins entirely."""
        day = date(2026, 7, 12)
        task = FakeTask(date=day, start_time=time(9, 0))
        local_dt = _local_dt(day, 10, 0)
        assert is_checkin_due(task, local_dt=local_dt, interval_minutes=0) is False
        assert is_checkin_due(task, local_dt=local_dt, interval_minutes=-5) is False

    def test_due_exactly_at_start_time(self) -> None:
        """At exactly start_time the first check-in is due."""
        day = date(2026, 7, 12)
        task = FakeTask(date=day, start_time=time(10, 0))
        local_dt = _local_dt(day, 10, 0)
        assert is_checkin_due(task, local_dt=local_dt, interval_minutes=15) is True

    def test_timezone_offset_boundary(self) -> None:
        """Eligibility uses the provided local_dt (caller applies timezone)."""
        day = date(2026, 7, 12)
        # Local UTC+3 is 10:00 → task at 09:00 is due
        task = FakeTask(date=day, start_time=time(9, 0))
        local_dt = _local_dt(day, 10, 0, offset_hours=3)
        assert is_checkin_due(task, local_dt=local_dt, interval_minutes=15) is True

    def test_snooze_until_blocks(self) -> None:
        """Active checkin_snooze_until suppresses check-ins."""
        day = date(2026, 7, 12)
        local_dt = _local_dt(day, 10, 0, offset_hours=0)
        snooze = local_dt.astimezone(timezone.utc) + timedelta(minutes=20)
        task = FakeTask(
            date=day,
            start_time=time(9, 0),
            checkin_snooze_until=snooze,
        )
        assert is_checkin_due(task, local_dt=local_dt, interval_minutes=15) is False

    def test_snooze_until_expired_allows(self) -> None:
        """Expired checkin_snooze_until no longer blocks."""
        day = date(2026, 7, 12)
        local_dt = _local_dt(day, 10, 0, offset_hours=0)
        snooze = local_dt.astimezone(timezone.utc) - timedelta(minutes=1)
        task = FakeTask(
            date=day,
            start_time=time(9, 0),
            checkin_snooze_until=snooze,
        )
        assert is_checkin_due(task, local_dt=local_dt, interval_minutes=15) is True



# ---------------------------------------------------------------------------
# Timezone helpers
# ---------------------------------------------------------------------------


class TestTimezoneHelpers:
    """Tests for shared timezone parsing helpers."""

    def test_parse_utc(self) -> None:
        assert parse_timezone_offset("UTC") == timedelta(0)
        assert parse_timezone_offset("") == timedelta(0)
        assert parse_timezone_offset("+0") == timedelta(0)

    def test_parse_positive_offset(self) -> None:
        assert parse_timezone_offset("+3") == timedelta(hours=3)
        assert parse_timezone_offset("UTC+3") == timedelta(hours=3)

    def test_parse_negative_offset(self) -> None:
        assert parse_timezone_offset("-5") == timedelta(hours=-5)

    def test_parse_unknown_falls_back_to_utc(self) -> None:
        assert parse_timezone_offset("Europe/Moscow") == timedelta(0)

    def test_local_now_returns_aware(self) -> None:
        now = local_now("+3")
        assert now.tzinfo is not None
        assert now.utcoffset() == timedelta(hours=3)


# ---------------------------------------------------------------------------
# Integration: process_checkins
# ---------------------------------------------------------------------------


async def _create_user(
    session: AsyncSession,
    *,
    telegram_id: int = 111,
    timezone_str: str = "UTC",
    check_interval: int = 15,
) -> User:
    user = User(
        telegram_id=telegram_id,
        timezone=timezone_str,
        check_interval=check_interval,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _create_task(
    session: AsyncSession,
    user: User,
    *,
    title: str = "Test task",
    task_date: date | None = None,
    start: time = time(0, 0),
    is_completed: bool = False,
    is_placeholder: bool = False,
    last_checkin_at: datetime | None = None,
) -> Task:
    task = Task(
        user_id=user.id,
        title=title,
        date=task_date or date.today(),
        start_time=start,
        end_time=None,
        is_completed=is_completed,
        is_placeholder=is_placeholder,
        last_checkin_at=last_checkin_at,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


def _mock_get_db(session: AsyncSession):
    @asynccontextmanager
    async def _cm():
        yield session

    return _cm


class TestProcessCheckins:
    """Integration tests for process_checkins with mocked bot + DB."""

    @pytest.mark.asyncio
    async def test_empty_task_list_sends_nothing(
        self,
        async_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """User with no tasks → sent == 0."""
        await _create_user(async_session, telegram_id=1001)
        bot = AsyncMock()
        monkeypatch.setattr(
            "src.services.checkin_service.get_db",
            _mock_get_db(async_session),
        )
        sent = await process_checkins(bot)
        assert sent == 0
        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_due_task_sends_and_stamps_last_checkin(
        self,
        async_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Due incomplete task → message sent and last_checkin_at set."""
        user = await _create_user(async_session, telegram_id=1002)
        # start_time far in the past so always due for "today"
        task = await _create_task(
            async_session,
            user,
            title="Morning run",
            start=time(0, 0),
        )
        bot = AsyncMock()
        monkeypatch.setattr(
            "src.services.checkin_service.get_db",
            _mock_get_db(async_session),
        )

        sent = await process_checkins(bot)

        assert sent == 1
        bot.send_message.assert_awaited_once()
        call_kwargs = bot.send_message.await_args.kwargs
        assert call_kwargs["chat_id"] == 1002
        assert "Morning run" in call_kwargs["text"]
        assert call_kwargs["reply_markup"] is not None

        await async_session.refresh(task)
        assert task.last_checkin_at is not None

    @pytest.mark.asyncio
    async def test_completed_task_never_messaged(
        self,
        async_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Completed tasks are not messaged."""
        user = await _create_user(async_session, telegram_id=1003)
        await _create_task(
            async_session,
            user,
            start=time(0, 0),
            is_completed=True,
        )
        bot = AsyncMock()
        monkeypatch.setattr(
            "src.services.checkin_service.get_db",
            _mock_get_db(async_session),
        )
        sent = await process_checkins(bot)
        assert sent == 0
        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_anti_spam_skips_recent_checkin(
        self,
        async_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Task with recent last_checkin_at is not re-sent."""
        user = await _create_user(
            async_session, telegram_id=1004, check_interval=30
        )
        await _create_task(
            async_session,
            user,
            start=time(0, 0),
            last_checkin_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        bot = AsyncMock()
        monkeypatch.setattr(
            "src.services.checkin_service.get_db",
            _mock_get_db(async_session),
        )
        sent = await process_checkins(bot)
        assert sent == 0
        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_telegram_error_continues(
        self,
        async_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Blocked bot / chat not found → log warning, no crash, continue."""
        user_a = await _create_user(async_session, telegram_id=2001)
        user_b = await _create_user(async_session, telegram_id=2002)
        await _create_task(async_session, user_a, title="A", start=time(0, 0))
        await _create_task(async_session, user_b, title="B", start=time(0, 0))

        bot = AsyncMock()
        # First send fails, second succeeds
        bot.send_message = AsyncMock(
            side_effect=[Exception("Forbidden: bot was blocked"), MagicMock()]
        )
        monkeypatch.setattr(
            "src.services.checkin_service.get_db",
            _mock_get_db(async_session),
        )

        sent = await process_checkins(bot)
        assert sent == 1
        assert bot.send_message.await_count == 2

    @pytest.mark.asyncio
    async def test_interval_zero_user_skipped(
        self,
        async_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Users with check_interval <= 0 are not queried for check-ins."""
        user = await _create_user(
            async_session, telegram_id=1005, check_interval=0
        )
        await _create_task(async_session, user, start=time(0, 0))
        bot = AsyncMock()
        monkeypatch.setattr(
            "src.services.checkin_service.get_db",
            _mock_get_db(async_session),
        )
        sent = await process_checkins(bot)
        assert sent == 0
        bot.send_message.assert_not_called()
