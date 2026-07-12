"""Tests for check-in yes/no callback handlers and keyboard."""

from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from datetime import date, time
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Task, User
from src.keyboards.inline import get_checkin_keyboard

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
) -> User:
    user = User(telegram_id=telegram_id, timezone="UTC", check_interval=15)
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
) -> Task:
    task = Task(
        user_id=user.id,
        title=title,
        date=date.today(),
        start_time=time(9, 0),
        end_time=None,
        is_completed=is_completed,
        is_placeholder=False,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


# ---------------------------------------------------------------------------
# Keyboard
# ---------------------------------------------------------------------------


class TestCheckinKeyboard:
    """Unit tests for get_checkin_keyboard."""

    def test_callback_data_format(self) -> None:
        kb = get_checkin_keyboard(42)
        raw = str(kb)
        assert "checkin:yes:42" in raw
        assert "checkin:no:42" in raw

    def test_two_buttons(self) -> None:
        kb = get_checkin_keyboard(7)
        # Flatten inline keyboard rows
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        assert len(buttons) == 2
        texts = {b.text for b in buttons}
        assert "✅" in texts
        assert "❌" in texts


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

        # Should not raise; alert is answered via callback.answer
        # MockTelegramSession still returns a Message for answer_callback_query
        # which may have empty text — just ensure no crash.
        try:
            await checkin_client.send_callback(
                "checkin:yes:99999",
                user_id=123456,
            )
        except RuntimeError:
            # No outgoing message is fine for alert-only path
            pass


class TestCheckinNo:
    """Tests for checkin:no callback."""

    @pytest.mark.asyncio
    async def test_no_leaves_incomplete(
        self,
        checkin_client: "TestClient",
        async_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user = await _create_user(async_session)
        task = await _create_task(async_session, user, title="Reading")

        import src.handlers.checkin as checkin_mod

        monkeypatch.setattr(checkin_mod, "get_db", _mock_get_db(async_session))

        resp: "Message" = await checkin_client.send_callback(
            f"checkin:no:{task.id}",
            user_id=123456,
        )

        await async_session.refresh(task)
        assert task.is_completed is False
        assert "Reading" in (resp.text or "")

    @pytest.mark.asyncio
    async def test_no_foreign_task_safe(
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
                f"checkin:no:{task.id}",
                user_id=222,
            )
        except RuntimeError:
            pass

        await async_session.refresh(task)
        assert task.is_completed is False
        # other user exists but must not complete foreign task
        assert other.id != owner.id
