"""Isolated unit tests for the AI one-off task assistant (B4)."""

from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from datetime import date
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import func, select

from src.db.models import Habit, Task, User
from src.services.ai_schema import AskQuestions, ProposeTaskPlan
from tests.conftest import TestClient


_SAMPLE_TASK = ProposeTaskPlan(
    type="propose_task",
    title="Team standup",
    date="2026-07-12",
    start_time="10:00",
    end_time="10:30",
    duration_minutes=30,
    comment="Daily sync",
)

_SAMPLE_ASK = AskQuestions(
    type="ask_questions",
    questions=["How long should it take?"],
    context=None,
)


@pytest_asyncio.fixture
async def task_ai_client(
    test_bot,
    async_session,
    monkeypatch,
) -> TestClient:
    """TestClient with ai_task_assistant router only."""
    import src.handlers.ai_task_assistant  # noqa: F811

    importlib.reload(src.handlers.ai_task_assistant)
    from src.handlers.ai_task_assistant import (  # noqa: F811
        router as ai_task_router,
    )

    @asynccontextmanager
    async def _fake_get_db():
        yield async_session

    import src.handlers.ai_task_assistant as mod

    monkeypatch.setattr(mod, "get_db", _fake_get_db)

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(ai_task_router)
    return TestClient(bot=test_bot, dp=dp)


@pytest_asyncio.fixture
async def task_ai_with_tasks_client(
    test_bot,
    async_session,
    monkeypatch,
) -> TestClient:
    """ai_task + tasks routers (manual fallback / force_add SkipHandler)."""
    import src.handlers.ai_task_assistant  # noqa: F811
    import src.handlers.tasks  # noqa: F811

    importlib.reload(src.handlers.ai_task_assistant)
    importlib.reload(src.handlers.tasks)
    from src.handlers.ai_task_assistant import (  # noqa: F811
        router as ai_task_router,
    )
    from src.handlers.tasks import router as tasks_router  # noqa: F811

    @asynccontextmanager
    async def _fake_get_db():
        yield async_session

    import src.handlers.ai_task_assistant as ai_mod
    import src.handlers.tasks as tasks_mod

    monkeypatch.setattr(ai_mod, "get_db", _fake_get_db)
    monkeypatch.setattr(tasks_mod, "get_db", _fake_get_db)

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(tasks_router)
    dp.include_router(ai_task_router)
    return TestClient(bot=test_bot, dp=dp)


def _sequence_mock(responses: list[Any]):
    queue = list(responses)

    async def _mock(*args, **kwargs):
        if not queue:
            return None
        return queue.pop(0)

    return _mock


@pytest.mark.asyncio
async def test_task_ai_direct_propose_creates_task_no_habit(
    task_ai_client: TestClient,
    async_session,
) -> None:
    """propose_task → confirm → one Task, habit_id=None, no Habit rows."""
    mock = _sequence_mock([_SAMPLE_TASK])

    with patch("src.handlers.ai_task_assistant.send_to_ai_parsed", mock):
        resp = await task_ai_client.send_callback("new_task:ai")
        assert resp.text is not None
        assert "задач" in resp.text.lower() or "task" in resp.text.lower()

        resp = await task_ai_client.send_message("созвон с командой")
        assert resp.text is not None
        assert "Team standup" in resp.text or "черновик" in resp.text.lower()

        resp = await task_ai_client.send_callback("assist_task:yes")
        assert resp.text is not None
        assert "успешно" in resp.text.lower() or "created" in resp.text.lower()

    tasks = (await async_session.execute(select(Task))).scalars().all()
    assert len(tasks) == 1
    assert tasks[0].habit_id is None
    assert tasks[0].title == "Team standup"
    assert tasks[0].start_time.hour == 10
    assert tasks[0].end_time.minute == 30

    habit_count = await async_session.scalar(select(func.count()).select_from(Habit))
    assert int(habit_count or 0) == 0


@pytest.mark.asyncio
async def test_task_ai_ask_then_propose(task_ai_client: TestClient) -> None:
    mock = _sequence_mock([_SAMPLE_ASK, _SAMPLE_TASK])

    with patch("src.handlers.ai_task_assistant.send_to_ai_parsed", mock):
        await task_ai_client.send_callback("new_task:ai")
        resp = await task_ai_client.send_message("встреча")
        assert "How long" in (resp.text or "") or "long" in (resp.text or "").lower()

        resp = await task_ai_client.send_message("30 минут")
        assert "Team standup" in (resp.text or "") or "черновик" in (
            resp.text or ""
        ).lower()


@pytest.mark.asyncio
async def test_task_ai_decline_no_write(
    task_ai_client: TestClient, async_session
) -> None:
    mock = _sequence_mock([_SAMPLE_TASK])

    with patch("src.handlers.ai_task_assistant.send_to_ai_parsed", mock):
        await task_ai_client.send_callback("new_task:ai")
        await task_ai_client.send_message("встреча")
        resp = await task_ai_client.send_callback("assist_task:no")
        assert resp.text is not None

    count = await async_session.scalar(select(func.count()).select_from(Task))
    assert int(count or 0) == 0


@pytest.mark.asyncio
async def test_task_ai_unavailable_fallback(task_ai_client: TestClient) -> None:
    async def _none(*args, **kwargs):
        return None

    with patch("src.handlers.ai_task_assistant.send_to_ai_parsed", _none):
        await task_ai_client.send_callback("new_task:ai")
        resp = await task_ai_client.send_message("что-то")
        assert "недоступен" in (resp.text or "").lower() or "unavailable" in (
            resp.text or ""
        ).lower()


@pytest.mark.asyncio
async def test_task_ai_fallback_to_manual(
    task_ai_with_tasks_client: TestClient, async_session
) -> None:
    user = User(telegram_id=123456, language="ru", timezone="UTC")
    async_session.add(user)
    await async_session.commit()

    async def _none(*args, **kwargs):
        return None

    with patch("src.handlers.ai_task_assistant.send_to_ai_parsed", _none):
        await task_ai_with_tasks_client.send_callback("new_task:ai")
        resp = await task_ai_with_tasks_client.send_message("задача")
        assert "недоступен" in (resp.text or "").lower()

        resp = await task_ai_with_tasks_client.send_callback("new_task:manual")
        assert resp.text is not None
        assert "дат" in resp.text.lower() or "calendar" in resp.text.lower() or "Выберите" in resp.text


@pytest.mark.asyncio
async def test_task_ai_dated_entry(task_ai_client: TestClient) -> None:
    mock = _sequence_mock([_SAMPLE_TASK])

    with patch("src.handlers.ai_task_assistant.send_to_ai_parsed", mock):
        resp = await task_ai_client.send_callback("task:ai:2026-08-01")
        assert resp.text is not None
        assert "2026-08-01" in resp.text


@pytest.mark.asyncio
async def test_task_ai_duration_integrity_in_db(
    task_ai_client: TestClient, async_session
) -> None:
    """Confirmed plan duration is reflected on the Task times."""
    plan = ProposeTaskPlan(
        type="propose_task",
        title="Focus block",
        date=date.today().isoformat(),
        start_time="09:00",
        end_time="09:45",
        duration_minutes=45,
        comment="",
    )
    mock = _sequence_mock([plan])

    with patch("src.handlers.ai_task_assistant.send_to_ai_parsed", mock):
        await task_ai_client.send_callback("new_task:ai")
        await task_ai_client.send_message("фокус")
        await task_ai_client.send_callback("assist_task:yes")

    task = (await async_session.execute(select(Task))).scalar_one()
    assert task.habit_id is None
    assert task.start_time.hour == 9
    assert task.end_time.hour == 9 and task.end_time.minute == 45
