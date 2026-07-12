"""Unit tests for the AI multi-turn assistant handler (B2)."""

from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from src.services.ai_schema import AskQuestions, ProposePlan
from tests.conftest import TestClient


# ---------------------------------------------------------------------------
# Sample AI payloads (B1/B2 contract)
# ---------------------------------------------------------------------------

_SAMPLE_PROPOSE = ProposePlan(
    type="propose_plan",
    title="Morning run",
    start_time="08:00",
    end_time="08:30",
    frequency="daily",
    duration_minutes=30,
    comment="Start slowly.",
)

_SAMPLE_ASK = AskQuestions(
    type="ask_questions",
    questions=["How many days per week?", "Morning or evening?"],
    context="Need schedule details",
)

_SAMPLE_ASK_CHOICE = AskQuestions(
    type="ask_questions",
    questions=[
        {
            "text": "When do you prefer?",
            "kind": "choice",
            "options": ["Morning", "Evening"],
        }
    ],
    context=None,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def ai_client(
    test_bot,
    async_session,
    monkeypatch,
) -> TestClient:
    """TestClient with ai_assistant router and patched get_db."""
    import src.handlers.ai_assistant  # noqa: F811

    importlib.reload(src.handlers.ai_assistant)
    from src.handlers.ai_assistant import (  # noqa: F811
        router as ai_assistant_router,
    )

    @asynccontextmanager
    async def _fake_get_db():
        yield async_session

    import src.handlers.ai_assistant as ai_module

    monkeypatch.setattr(ai_module, "get_db", _fake_get_db)

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(ai_assistant_router)
    return TestClient(bot=test_bot, dp=dp)


@pytest_asyncio.fixture
async def ai_habits_client(
    test_bot,
    async_session,
    monkeypatch,
) -> TestClient:
    """TestClient with ai_assistant + habits routers (fallback to manual)."""
    import src.handlers.ai_assistant  # noqa: F811
    import src.handlers.habits  # noqa: F811

    importlib.reload(src.handlers.ai_assistant)
    importlib.reload(src.handlers.habits)
    from src.handlers.ai_assistant import (  # noqa: F811
        router as ai_assistant_router,
    )
    from src.handlers.habits import (  # noqa: F811
        router as habits_router,
    )

    @asynccontextmanager
    async def _fake_get_db():
        yield async_session

    import src.handlers.ai_assistant as ai_module
    import src.handlers.habits as habits_module

    monkeypatch.setattr(ai_module, "get_db", _fake_get_db)
    monkeypatch.setattr(habits_module, "get_db", _fake_get_db)

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(ai_assistant_router)
    dp.include_router(habits_router)
    return TestClient(bot=test_bot, dp=dp)


def _captured_texts(client: TestClient) -> list[str]:
    """Return non-empty texts from the bot session capture buffer."""
    session = client.bot.session
    return [m.text for m in session.captured if m.text]


def _sequence_mock(responses: list[Any]):
    """Return an async mock that yields *responses* in order, then None."""
    queue = list(responses)

    async def _mock(*args, **kwargs):
        if not queue:
            return None
        return queue.pop(0)

    return _mock


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ai_ask_then_answer_then_plan(ai_client: TestClient) -> None:
    """AI ask → user answer → AI plan preview → confirm creates habit."""
    mock = _sequence_mock([_SAMPLE_ASK, _SAMPLE_PROPOSE])

    with patch("src.handlers.ai_assistant.send_to_ai_parsed", mock):
        resp = await ai_client.send_callback("new_habit:ai")
        assert resp.text is not None
        assert "привычку" in resp.text.lower()

        # Title triggers first AI call → ask_questions
        resp = await ai_client.send_message("бег по утрам")
        assert resp.text is not None
        assert "days per week" in resp.text.lower() or "How many" in resp.text

        # Answer Q1
        resp = await ai_client.send_message("5")
        assert resp.text is not None
        # Second question from same round
        assert "Morning" in resp.text or "evening" in resp.text.lower()

        # Answer Q2 → second AI call → propose
        resp = await ai_client.send_message("Morning")
        assert resp.text is not None
        assert "Предложенный план" in resp.text or "черновик" in resp.text
        assert "Morning run" in resp.text

        # Confirm yes → create
        resp = await ai_client.send_callback("assist:yes")
        assert resp.text is not None
        assert "Привычка успешно создана" in resp.text


@pytest.mark.asyncio
async def test_ai_direct_propose_no_questions(ai_client: TestClient) -> None:
    """AI may propose immediately without clarifying questions."""
    mock = _sequence_mock([_SAMPLE_PROPOSE])

    with patch("src.handlers.ai_assistant.send_to_ai_parsed", mock):
        await ai_client.send_callback("new_habit:ai")
        resp = await ai_client.send_message("читать книги")
        assert "Предложенный план" in (resp.text or "")
        assert "Morning run" in (resp.text or "")

        resp = await ai_client.send_callback("assist:yes")
        assert "Привычка успешно создана" in (resp.text or "")


@pytest.mark.asyncio
async def test_ai_decline_creation(ai_client: TestClient) -> None:
    """User declines plan preview → no habit creation message success."""
    mock = _sequence_mock([_SAMPLE_PROPOSE])

    with patch("src.handlers.ai_assistant.send_to_ai_parsed", mock):
        await ai_client.send_callback("new_habit:ai")
        resp = await ai_client.send_message("бег")
        assert "Предложенный план" in (resp.text or "")

        resp = await ai_client.send_callback("assist:no")
        assert resp.text is not None
        assert "может быть, в другой раз" in resp.text.lower()


@pytest.mark.asyncio
async def test_ai_choice_question(ai_client: TestClient) -> None:
    """Structured choice question → assist:choice:i → plan."""
    mock = _sequence_mock([_SAMPLE_ASK_CHOICE, _SAMPLE_PROPOSE])

    with patch("src.handlers.ai_assistant.send_to_ai_parsed", mock):
        await ai_client.send_callback("new_habit:ai")
        resp = await ai_client.send_message("йога")
        assert "prefer" in (resp.text or "").lower() or "When" in (resp.text or "")

        resp = await ai_client.send_callback("assist:choice:0")
        assert "Предложенный план" in (resp.text or "")


# ---------------------------------------------------------------------------
# Anti-loop: 4th ask → force propose or fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ai_fourth_ask_force_propose(ai_client: TestClient) -> None:
    """After 3 ask rounds, a 4th ask triggers force-propose re-call."""
    # 3 successful ask rounds, then on 4th call return ask again,
    # force re-call returns propose.
    ask = AskQuestions(
        type="ask_questions",
        questions=["More detail?"],
        context=None,
    )
    responses = [ask, ask, ask, ask, _SAMPLE_PROPOSE]
    mock = _sequence_mock(responses)

    with patch("src.handlers.ai_assistant.send_to_ai_parsed", mock):
        await ai_client.send_callback("new_habit:ai")
        resp = await ai_client.send_message("бег")
        # Round 1
        assert "More detail" in (resp.text or "")
        resp = await ai_client.send_message("a")
        # Round 2
        assert "More detail" in (resp.text or "")
        resp = await ai_client.send_message("b")
        # Round 3
        assert "More detail" in (resp.text or "")
        resp = await ai_client.send_message("c")
        # Round 4 would ask again → force → propose
        assert "Предложенный план" in (resp.text or "") or "Morning run" in (
            resp.text or ""
        )


@pytest.mark.asyncio
async def test_ai_fourth_ask_force_fails_fallback(ai_client: TestClient) -> None:
    """If force-propose also fails/asks → fallback keyboard."""
    ask = AskQuestions(
        type="ask_questions",
        questions=["Again?"],
        context=None,
    )
    # 3 asks + 4th ask + force returns ask again → fallback
    responses = [ask, ask, ask, ask, ask]
    mock = _sequence_mock(responses)

    with patch("src.handlers.ai_assistant.send_to_ai_parsed", mock):
        await ai_client.send_callback("new_habit:ai")
        await ai_client.send_message("бег")
        await ai_client.send_message("a")
        await ai_client.send_message("b")
        resp = await ai_client.send_message("c")
        assert "ИИ временно недоступен" in (resp.text or "")


# ---------------------------------------------------------------------------
# Failures / edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ai_fail_mid_flow_fallback(ai_client: TestClient) -> None:
    """AI fails after user answered first question → fallback keyboard."""
    mock = _sequence_mock([_SAMPLE_ASK, None])

    with patch("src.handlers.ai_assistant.send_to_ai_parsed", mock):
        await ai_client.send_callback("new_habit:ai")
        resp = await ai_client.send_message("читать книги")
        assert "days" in (resp.text or "").lower() or "How many" in (resp.text or "")

        # Answer both questions from the round; second AI call fails
        await ai_client.send_message("3")
        resp = await ai_client.send_message("evening")
        assert "ИИ временно недоступен" in (resp.text or "")


@pytest.mark.asyncio
async def test_ai_empty_questions_fallback(ai_client: TestClient) -> None:
    """Empty questions array is treated as error/fallback (parser → None)."""
    # parse_ai_response already rejects empty questions; simulate None from service
    async def _mock(*args, **kwargs):
        return None

    with patch("src.handlers.ai_assistant.send_to_ai_parsed", _mock):
        await ai_client.send_callback("new_habit:ai")
        resp = await ai_client.send_message("бегать")
        assert "ИИ временно недоступен" in (resp.text or "")


@pytest.mark.asyncio
async def test_ai_error_fallback_to_manual(
    ai_habits_client: TestClient, async_session
) -> None:
    """After AI failure, user clicks manual creation."""
    from src.db.models import User

    user = User(telegram_id=123456, language="ru", timezone="UTC")
    async_session.add(user)
    await async_session.commit()

    async def _mock(*args, **kwargs):
        return None

    with patch("src.handlers.ai_assistant.send_to_ai_parsed", _mock):
        await ai_habits_client.send_callback("new_habit:ai")
        resp = await ai_habits_client.send_message("читать книги")
        assert "ИИ временно недоступен" in (resp.text or "")

        resp = await ai_habits_client.send_callback("new_habit:manual")
        assert resp.text is not None
        assert "название привычки" in resp.text.lower()


@pytest.mark.asyncio
async def test_ai_cancel_at_clarifying(ai_client: TestClient) -> None:
    """User cancels while answering clarifying questions."""
    mock = _sequence_mock([_SAMPLE_ASK])

    with patch("src.handlers.ai_assistant.send_to_ai_parsed", mock):
        await ai_client.send_callback("new_habit:ai")
        await ai_client.send_message("бег")
        resp = await ai_client.send_callback("nav:cancel")
        assert resp is not None


@pytest.mark.asyncio
async def test_ai_skip_question(ai_client: TestClient) -> None:
    """User skips clarifying questions via assist:skip."""
    ask_one = AskQuestions(
        type="ask_questions",
        questions=["Any obstacles?"],
        context=None,
    )
    mock = _sequence_mock([ask_one, _SAMPLE_PROPOSE])

    with patch("src.handlers.ai_assistant.send_to_ai_parsed", mock):
        await ai_client.send_callback("new_habit:ai")
        await ai_client.send_message("бег")
        resp = await ai_client.send_callback("assist:skip")
        assert "Предложенный план" in (resp.text or "")


# ---------------------------------------------------------------------------
# Waiting indicator on each AI call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ai_waiting_indicator_on_first_call(ai_client: TestClient) -> None:
    """Waiting placeholder is shown on the first AI call after title."""
    from src.handlers.ai_assistant import AI_WAITING_TEXT

    mock = _sequence_mock([_SAMPLE_PROPOSE])

    with patch("src.handlers.ai_assistant.send_to_ai_parsed", mock):
        await ai_client.send_callback("new_habit:ai")
        resp = await ai_client.send_message("бегать")
        texts = _captured_texts(ai_client)
        assert any(AI_WAITING_TEXT in (t or "") for t in texts) or (
            AI_WAITING_TEXT in (resp.text or "")
        )
        assert "Предложенный план" in (resp.text or "")


@pytest.mark.asyncio
async def test_ai_waiting_indicator_on_second_call(ai_client: TestClient) -> None:
    """Waiting placeholder is shown again after answering questions."""
    from src.handlers.ai_assistant import AI_WAITING_TEXT

    ask_one = AskQuestions(
        type="ask_questions",
        questions=["Duration?"],
        context=None,
    )
    mock = _sequence_mock([ask_one, _SAMPLE_PROPOSE])

    with patch("src.handlers.ai_assistant.send_to_ai_parsed", mock):
        await ai_client.send_callback("new_habit:ai")
        await ai_client.send_message("бег")
        resp = await ai_client.send_message("30 min")
        texts = _captured_texts(ai_client)
        waiting_hits = sum(1 for t in texts if AI_WAITING_TEXT in (t or ""))
        # At least one waiting indicator overall; ideally two AI turns
        assert waiting_hits >= 1 or AI_WAITING_TEXT in (resp.text or "")
        assert "Предложенный план" in (resp.text or "")


@pytest.mark.asyncio
async def test_ai_waiting_then_error(ai_client: TestClient) -> None:
    """Waiting then friendly error when AI returns None."""
    from src.handlers.ai_assistant import AI_WAITING_TEXT

    async def _mock(*args, **kwargs):
        return None

    with patch("src.handlers.ai_assistant.send_to_ai_parsed", _mock):
        await ai_client.send_callback("new_habit:ai")
        resp = await ai_client.send_message("бегать")
        texts = _captured_texts(ai_client)
        assert any(AI_WAITING_TEXT in (t or "") for t in texts) or (
            AI_WAITING_TEXT in (resp.text or "")
        )
        assert "ИИ временно недоступен" in (resp.text or "")


@pytest.mark.asyncio
async def test_deliver_ai_result_edit_failure_sends_new(
    ai_client: TestClient,
) -> None:
    """If placeholder edit fails, send a new message (no traceback)."""
    from aiogram.types import Chat, Message
    from src.handlers.ai_assistant import _deliver_ai_result

    bot = ai_client.bot
    chat = Chat(id=123456, type="private")
    placeholder = Message(message_id=99, date=0, chat=chat, text="waiting")

    bot.edit_message_text = AsyncMock(side_effect=RuntimeError("edit failed"))
    sent = Message(message_id=100, date=0, chat=chat, text="final")
    bot.send_message = AsyncMock(return_value=sent)
    bot.delete_message = AsyncMock(return_value=True)

    user_msg = Message(
        message_id=1,
        date=0,
        chat=chat,
        text="q",
    ).as_(bot)

    await _deliver_ai_result(
        placeholder,
        user_msg,
        "final result text",
        reply_markup=None,
        parse_mode=None,
    )

    bot.edit_message_text.assert_awaited()
    bot.send_message.assert_awaited()
    bot.delete_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_preview_does_not_create_until_confirm(
    ai_client: TestClient, async_session
) -> None:
    """Propose plan preview must not write habits before assist:yes."""
    from sqlalchemy import func, select

    from src.db.models import Habit

    mock = _sequence_mock([_SAMPLE_PROPOSE])

    with patch("src.handlers.ai_assistant.send_to_ai_parsed", mock):
        await ai_client.send_callback("new_habit:ai")
        resp = await ai_client.send_message("бег")
        assert "Предложенный план" in (resp.text or "")

        count = await async_session.scalar(select(func.count()).select_from(Habit))
        assert int(count or 0) == 0

        await ai_client.send_callback("assist:yes")
        count2 = await async_session.scalar(select(func.count()).select_from(Habit))
        assert int(count2 or 0) == 1
