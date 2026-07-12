"""Tests for check-in callback handlers and keyboards."""

from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Task, User
from src.keyboards.inline import (
    get_checkin_keyboard,
    get_checkin_reschedule_keyboard,
    get_checkin_snooze_keyboard,
)

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import Message

    from tests.conftest import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def checkin_dispatcher() -> Dispatcher:
    """Dispatcher with checkin + common routers."""
    import src.handlers.checkin
    import src.handlers.common

    importlib.reload(src.handlers.checkin)
    importlib.reload(src.handlers.common)
    from src.handlers.checkin import router as checkin_router
    from src.handlers.common import router as common_router

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(checkin_router)
    dp.include_router(common_router)
    return dp


@pytest_asyncio.fixture(scope="function")
async def checkin_client(
    test_bot: "Bot",
    checkin_dispatcher: Dispatcher,
) -> "TestClient":
    from tests.conftest import TestClient

    return TestClient(bot=test_bot, dp=checkin_dispatcher)


def _mock_get_db(async_session: AsyncSession):
    @asynccontextmanager
    async def _cm():
        yield async_session

    return _cm


async def _create_user(
    session: AsyncSession,
    *,
    telegram_id: int = 123456,
    timezone_str: str = "UTC",
) -> User:
    user = User(
        telegram_id=telegram_id,
        timezone=timezone_str,
        check_interval=15,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _create_task(
    session: AsyncSession,
    user: User,
    *,
    title: str = "Check-in task",
    is_completed: bool = False,
    start: time = time(9, 0),
    end: time | None = None,
    task_date: date | None = None,
) -> Task:
    task = Task(
        user_id=user.id,
        title=title,
        date=task_date or date.today(),
        start_time=start,
        end_time=end,
        is_completed=is_completed,
        is_placeholder=False,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------


class TestCheckinKeyboard:
    """Unit tests for check-in keyboards."""

    def test_main_callback_data_format(self) -> None:
        kb = get_checkin_keyboard(42)
        raw = str(kb)
        assert "checkin:yes:42" in raw
        assert "checkin:mute:42" in raw
        assert "checkin:later:42" in raw
        assert "checkin:reschedule:42" in raw

    def test_four_buttons(self) -> None:
        kb = get_checkin_keyboard(7)
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        assert len(buttons) == 4

    def test_snooze_keyboard(self) -> None:
        kb = get_checkin_snooze_keyboard(5)
        raw = str(kb)
        assert "checkin:snooze:5:15" in raw
        assert "checkin:snooze:5:30" in raw
        assert "checkin:snooze:5:45" in raw
        assert "checkin:snooze:5:60" in raw
        assert "checkin:back:5" in raw

    def test_reschedule_keyboard(self) -> None:
        slots = [time(14, 0), time(14, 15), time(15, 0)]
        kb = get_checkin_reschedule_keyboard(9, slots)
        raw = str(kb)
        assert "checkin:move:9:14:00" in raw
        assert "checkin:move:9:14:15" in raw
        assert "checkin:move:9:15:00" in raw
        assert "checkin:back:9" in raw


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


class TestCheckinYes:
    """Tests for checkin:yes callback."""

    @pytest.mark.asyncio
    async def test_yes_marks_completed(
        self,
        checkin_client: "TestClient",
        async_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user = await _create_user(async_session)
        task = await _create_task(async_session, user, title="Yoga")

        import src.handlers.checkin as checkin_mod

        monkeypatch.setattr(checkin_mod, "get_db", _mock_get_db(async_session))

        resp: "Message" = await checkin_client.send_callback(
            f"checkin:yes:{task.id}",
            user_id=123456,
        )

        await async_session.refresh(task)
        assert task.is_completed is True
        assert "Yoga" in (resp.text or "")
        assert "выполнен" in (resp.text or "").lower()

    @pytest.mark.asyncio
    async def test_yes_unknown_task_safe(
        self,
        checkin_client: "TestClient",
        async_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await _create_user(async_session)

        import src.handlers.checkin as checkin_mod

        monkeypatch.setattr(checkin_mod, "get_db", _mock_get_db(async_session))

        try:
            await checkin_client.send_callback(
                "checkin:yes:99999",
                user_id=123456,
            )
        except RuntimeError:
            pass


class TestCheckinMute:
    """Tests for checkin:mute / legacy checkin:no."""

    @pytest.mark.asyncio
    async def test_mute_sets_snooze_until_eod(
        self,
        checkin_client: "TestClient",
        async_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user = await _create_user(async_session, timezone_str="+3")
        task = await _create_task(async_session, user, title="Reading")

        import src.handlers.checkin as checkin_mod

        monkeypatch.setattr(checkin_mod, "get_db", _mock_get_db(async_session))

        resp: "Message" = await checkin_client.send_callback(
            f"checkin:mute:{task.id}",
            user_id=123456,
        )

        await async_session.refresh(task)
        assert task.is_completed is False
        assert task.checkin_snooze_until is not None
        assert "Reading" in (resp.text or "")
        assert "не напомним" in (resp.text or "").lower()

    @pytest.mark.asyncio
    async def test_legacy_no_maps_to_mute(
        self,
        checkin_client: "TestClient",
        async_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user = await _create_user(async_session)
        task = await _create_task(async_session, user, title="Legacy")

        import src.handlers.checkin as checkin_mod

        monkeypatch.setattr(checkin_mod, "get_db", _mock_get_db(async_session))

        await checkin_client.send_callback(
            f"checkin:no:{task.id}",
            user_id=123456,
        )

        await async_session.refresh(task)
        assert task.checkin_snooze_until is not None
        assert task.is_completed is False

    @pytest.mark.asyncio
    async def test_mute_foreign_task_safe(
        self,
        checkin_client: "TestClient",
        async_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        owner = await _create_user(async_session, telegram_id=111)
        other = await _create_user(async_session, telegram_id=222)
        task = await _create_task(async_session, owner, title="Secret")

        import src.handlers.checkin as checkin_mod

        monkeypatch.setattr(checkin_mod, "get_db", _mock_get_db(async_session))

        try:
            await checkin_client.send_callback(
                f"checkin:mute:{task.id}",
                user_id=222,
            )
        except RuntimeError:
            pass

        await async_session.refresh(task)
        assert task.checkin_snooze_until is None
        assert other.id != owner.id


class TestCheckinSnooze:
    """Tests for later + snooze flow."""

    @pytest.mark.asyncio
    async def test_later_shows_snooze_menu(
        self,
        checkin_client: "TestClient",
        async_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user = await _create_user(async_session)
        task = await _create_task(async_session, user, title="Run")

        import src.handlers.checkin as checkin_mod

        monkeypatch.setattr(checkin_mod, "get_db", _mock_get_db(async_session))

        resp: "Message" = await checkin_client.send_callback(
            f"checkin:later:{task.id}",
            user_id=123456,
        )
        assert "Run" in (resp.text or "")
        markup = resp.reply_markup
        assert markup is not None
        raw = str(markup)
        assert f"checkin:snooze:{task.id}:15" in raw

    @pytest.mark.asyncio
    async def test_snooze_sets_until(
        self,
        checkin_client: "TestClient",
        async_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user = await _create_user(async_session)
        task = await _create_task(async_session, user, title="Meditate")
        before = datetime.now(timezone.utc)

        import src.handlers.checkin as checkin_mod

        monkeypatch.setattr(checkin_mod, "get_db", _mock_get_db(async_session))

        resp: "Message" = await checkin_client.send_callback(
            f"checkin:snooze:{task.id}:30",
            user_id=123456,
        )

        await async_session.refresh(task)
        assert task.checkin_snooze_until is not None
        snooze = task.checkin_snooze_until
        if snooze.tzinfo is None:
            snooze = snooze.replace(tzinfo=timezone.utc)
        assert snooze >= before + timedelta(minutes=29)
        assert snooze <= before + timedelta(minutes=31)
        assert "30" in (resp.text or "")
        assert "Meditate" in (resp.text or "")


class TestCheckinReschedule:
    """Tests for reschedule / move flow."""

    @pytest.mark.asyncio
    async def test_reschedule_shows_free_slots(
        self,
        checkin_client: "TestClient",
        async_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user = await _create_user(async_session, timezone_str="UTC")
        task = await _create_task(
            async_session,
            user,
            title="Call",
            start=time(9, 0),
            end=time(9, 30),
        )
        # Block mid-day so some slots are occupied
        await _create_task(
            async_session,
            user,
            title="Busy",
            start=time(12, 0),
            end=time(13, 0),
        )

        import src.handlers.checkin as checkin_mod

        monkeypatch.setattr(checkin_mod, "get_db", _mock_get_db(async_session))
        # Force "now" early so many future slots exist
        fixed_now = datetime(
            date.today().year,
            date.today().month,
            date.today().day,
            10,
            0,
            tzinfo=timezone.utc,
        )
        monkeypatch.setattr(
            checkin_mod,
            "local_now",
            lambda _tz: fixed_now,
        )

        resp: "Message" = await checkin_client.send_callback(
            f"checkin:reschedule:{task.id}",
            user_id=123456,
        )
        assert "Call" in (resp.text or "")
        markup = resp.reply_markup
        assert markup is not None
        raw = str(markup)
        assert f"checkin:move:{task.id}:" in raw
        # Occupied 12:00–13:00 should not offer 12:00 for a 30-min task
        assert f"checkin:move:{task.id}:12:00" not in raw

    @pytest.mark.asyncio
    async def test_move_updates_times(
        self,
        checkin_client: "TestClient",
        async_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user = await _create_user(async_session)
        task = await _create_task(
            async_session,
            user,
            title="Workout",
            start=time(9, 0),
            end=time(10, 0),
        )
        task.last_checkin_at = datetime.now(timezone.utc)
        task.checkin_snooze_until = datetime.now(timezone.utc) + timedelta(hours=1)
        await async_session.commit()

        import src.handlers.checkin as checkin_mod

        monkeypatch.setattr(checkin_mod, "get_db", _mock_get_db(async_session))

        resp: "Message" = await checkin_client.send_callback(
            f"checkin:move:{task.id}:15:00",
            user_id=123456,
        )

        await async_session.refresh(task)
        assert task.start_time == time(15, 0)
        assert task.end_time == time(16, 0)  # duration preserved
        assert task.last_checkin_at is None
        assert task.checkin_snooze_until is None
        assert "15:00" in (resp.text or "")
        assert "Workout" in (resp.text or "")

    @pytest.mark.asyncio
    async def test_move_open_ended_keeps_none_end(
        self,
        checkin_client: "TestClient",
        async_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user = await _create_user(async_session)
        task = await _create_task(
            async_session,
            user,
            title="Open",
            start=time(8, 0),
            end=None,
        )

        import src.handlers.checkin as checkin_mod

        monkeypatch.setattr(checkin_mod, "get_db", _mock_get_db(async_session))

        await checkin_client.send_callback(
            f"checkin:move:{task.id}:18:00",
            user_id=123456,
        )

        await async_session.refresh(task)
        assert task.start_time == time(18, 0)
        assert task.end_time is None


class TestCheckinBack:
    @pytest.mark.asyncio
    async def test_back_restores_prompt(
        self,
        checkin_client: "TestClient",
        async_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user = await _create_user(async_session)
        task = await _create_task(async_session, user, title="BackTask")

        import src.handlers.checkin as checkin_mod

        monkeypatch.setattr(checkin_mod, "get_db", _mock_get_db(async_session))

        resp: "Message" = await checkin_client.send_callback(
            f"checkin:back:{task.id}",
            user_id=123456,
        )
        assert "BackTask" in (resp.text or "")
        markup = resp.reply_markup
        assert markup is not None
        raw = str(markup)
        assert f"checkin:yes:{task.id}" in raw
        assert f"checkin:mute:{task.id}" in raw
