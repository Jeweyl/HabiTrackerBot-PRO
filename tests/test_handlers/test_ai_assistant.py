"""Unit tests for the AI assistant handler (src/handlers/ai_assistant.py)."""

import importlib
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
import pytest_asyncio
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from tests.conftest import TestClient


# ---------------------------------------------------------------------------
# Sample AI response used in tests
# ---------------------------------------------------------------------------

_SAMPLE_AI_RESPONSE = {
    "refined_habit": "Morning run",
    "metric_name": "distance",
    "metric_unit": "km",
    "target_per_day": 5,
    "period": "daily",
    "comment": "Start slowly.",
}


# ---------------------------------------------------------------------------
# Fixture: dispatcher with ai_assistant router and patched dependencies
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def ai_client(
    test_bot,
    async_session,
    monkeypatch,
) -> TestClient:
    """Return a TestClient with the ai_assistant router and mocked dependencies.

    Patches ``get_db`` to use the in-memory SQLite session.
    """
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
    """Return a TestClient with both ai_assistant and habits routers.

    Needed for tests that verify the fallback from AI to manual creation.
    """
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ai_happy_path_sport_keywords(ai_client: TestClient) -> None:
    """Full flow with sport keywords: user enters title with 'бег',
    gets sport-specific adaptive questions, AI returns valid JSON,
    habit and task are created."""

    async def _mock_send_to_ai(*args, **kwargs):
        return _SAMPLE_AI_RESPONSE

    with patch("src.handlers.ai_assistant.send_to_ai", _mock_send_to_ai):
        # Start AI assistant via new_habit:ai
        resp = await ai_client.send_callback("new_habit:ai")
        assert resp.text is not None
        assert "привычку" in resp.text.lower()

        # Enter title with sport keyword
        resp = await ai_client.send_message("бег по утрам")
        assert resp.text is not None
        assert "подготовки" in resp.text.lower()

        # Adaptive Q1 (sport_intensity): select "Средний"
        resp = await ai_client.send_callback("assist:intensity:intermediate")
        assert resp.text is not None
        assert "минут" in resp.text.lower()

        # Adaptive Q2 (sport_duration): select "30 мин"
        resp = await ai_client.send_callback("assist:duration:30")
        assert resp.text is not None
        assert "SMART-план" in resp.text
        assert "Morning run" in resp.text

        # Confirm: yes
        resp = await ai_client.send_callback("assist:yes")
        assert resp.text is not None
        assert "Привычка успешно создана" in resp.text


@pytest.mark.asyncio
async def test_ai_happy_path_hygiene_keywords(ai_client: TestClient) -> None:
    """Full flow with hygiene keywords: title 'чистить зубы',
    gets hygiene-specific adaptive questions."""

    async def _mock_send_to_ai(*args, **kwargs):
        return _SAMPLE_AI_RESPONSE

    with patch("src.handlers.ai_assistant.send_to_ai", _mock_send_to_ai):
        resp = await ai_client.send_callback("new_habit:ai")
        assert "привычку" in resp.text.lower()

        resp = await ai_client.send_message("чистить зубы")
        assert "время дня" in resp.text.lower()

        # Adaptive Q1 (hygiene_time): select "Утром"
        resp = await ai_client.send_callback("assist:time:morning")
        assert "помешать" in resp.text.lower()

        # Adaptive Q2 (hygiene_obstacles): send text
        resp = await ai_client.send_message("Иногда забываю вечером")
        assert resp.text is not None
        assert "SMART-план" in resp.text

        resp = await ai_client.send_callback("assist:yes")
        assert "Привычка успешно создана" in resp.text


@pytest.mark.asyncio
async def test_ai_happy_path_generic_keywords(ai_client: TestClient) -> None:
    """Full flow with generic (no keyword match): title 'читать книги',
    gets generic frequency + obstacles questions."""

    async def _mock_send_to_ai(*args, **kwargs):
        return _SAMPLE_AI_RESPONSE

    with patch("src.handlers.ai_assistant.send_to_ai", _mock_send_to_ai):
        resp = await ai_client.send_callback("new_habit:ai")
        assert "привычку" in resp.text.lower()

        resp = await ai_client.send_message("читать книги")
        assert "часто" in resp.text.lower()

        # Adaptive Q1 (generic_frequency): select "Каждый день"
        resp = await ai_client.send_callback("assist:freq:daily")
        assert "препятствия" in resp.text.lower()

        # Adaptive Q2 (generic_obstacles): send text
        resp = await ai_client.send_message("Нет времени")
        assert resp.text is not None
        assert "SMART-план" in resp.text

        resp = await ai_client.send_callback("assist:yes")
        assert "Привычка успешно создана" in resp.text


@pytest.mark.asyncio
async def test_ai_skip_all_adaptive_questions(ai_client: TestClient) -> None:
    """User skips both adaptive questions via assist:skip callback."""

    async def _mock_send_to_ai(*args, **kwargs):
        return _SAMPLE_AI_RESPONSE

    with patch("src.handlers.ai_assistant.send_to_ai", _mock_send_to_ai):
        resp = await ai_client.send_callback("new_habit:ai")
        resp = await ai_client.send_message("бег")

        # Skip Q1
        resp = await ai_client.send_callback("assist:skip")
        assert "минут" in resp.text.lower()

        # Skip Q2
        resp = await ai_client.send_callback("assist:skip")
        assert "SMART-план" in resp.text

        resp = await ai_client.send_callback("assist:yes")
        assert "Привычка успешно создана" in resp.text


@pytest.mark.asyncio
async def test_ai_cancel_at_adaptive_q1(ai_client: TestClient) -> None:
    """User cancels at the first adaptive question."""
    resp = await ai_client.send_callback("new_habit:ai")
    assert "привычку" in resp.text.lower()

    resp = await ai_client.send_message("бег")
    assert "подготовки" in resp.text.lower()

    # Cancel from ask_adaptive_q1
    resp = await ai_client.send_callback("nav:cancel")
    assert resp is not None


@pytest.mark.asyncio
async def test_ai_invalid_json_error_handling(ai_client: TestClient) -> None:
    """AI returns None (invalid JSON) → friendly error + fallback keyboard."""

    async def _mock_send_to_ai(*args, **kwargs):
        return None

    with patch("src.handlers.ai_assistant.send_to_ai", _mock_send_to_ai):
        resp = await ai_client.send_callback("new_habit:ai")
        assert "привычку" in resp.text.lower()

        # Enter title
        resp = await ai_client.send_message("читать книги")
        assert "часто" in resp.text.lower()

        # Q1: select frequency
        resp = await ai_client.send_callback("assist:freq:daily")
        assert "препятствия" in resp.text.lower()

        # Q2: send text → triggers AI call which returns None
        resp = await ai_client.send_message("Нет времени")
        assert resp.text is not None
        assert "ИИ временно недоступен" in resp.text


@pytest.mark.asyncio
async def test_ai_error_fallback_to_manual(
    ai_habits_client: TestClient, async_session
) -> None:
    """After AI failure, user clicks 'Создать вручную' → starts manual creation."""

    # Create a user so the manual creation handler can find it
    from src.db.models import User

    user = User(telegram_id=123456, language="ru", timezone="UTC")
    async_session.add(user)
    await async_session.commit()

    async def _mock_send_to_ai(*args, **kwargs):
        return None

    with patch("src.handlers.ai_assistant.send_to_ai", _mock_send_to_ai):
        resp = await ai_habits_client.send_callback("new_habit:ai")
        resp = await ai_habits_client.send_message("читать книги")

        # Q1: skip
        resp = await ai_habits_client.send_callback("assist:skip")
        # Q2: skip (triggers AI → fails)
        resp = await ai_habits_client.send_callback("assist:skip")
        assert "ИИ временно недоступен" in resp.text

        # Click "Создать вручную" (new_habit:manual)
        resp = await ai_habits_client.send_callback("new_habit:manual")
        assert resp.text is not None
        assert "название привычки" in resp.text.lower()
        assert "от 1 до 200" in resp.text.lower()


@pytest.mark.asyncio
async def test_ai_back_navigation(ai_client: TestClient) -> None:
    """User goes back from adaptive Q1 to start, re-enters title."""
    resp = await ai_client.send_callback("new_habit:ai")
    assert "привычку" in resp.text.lower()

    resp = await ai_client.send_message("бег")
    assert "подготовки" in resp.text.lower()

    # Go back to start
    resp = await ai_client.send_callback("nav:back")
    assert resp is not None
    # Should show title prompt again
    assert "привычку" in resp.text.lower()

    # Re-enter different title
    resp = await ai_client.send_message("йога")
    assert "подготовки" in resp.text.lower()

    # Answer Q1 and go back to Q1 from Q2
    resp = await ai_client.send_callback("assist:intensity:beginner")
    assert "минут" in resp.text.lower()

    # Go back to Q1
    resp = await ai_client.send_callback("nav:back")
    assert "подготовки" in resp.text.lower()


@pytest.mark.asyncio
async def test_ai_decline_creation(ai_client: TestClient) -> None:
    """User completes flow but declines habit creation at confirmation."""

    async def _mock_send_to_ai(*args, **kwargs):
        return _SAMPLE_AI_RESPONSE

    with patch("src.handlers.ai_assistant.send_to_ai", _mock_send_to_ai):
        resp = await ai_client.send_callback("new_habit:ai")
        resp = await ai_client.send_message("бег")

        resp = await ai_client.send_callback("assist:skip")  # Q1
        resp = await ai_client.send_callback("assist:skip")  # Q2
        assert "SMART-план" in resp.text

        # Decline creation
        resp = await ai_client.send_callback("assist:no")
        assert resp.text is not None
        assert "может быть, в другой раз" in resp.text.lower()


@pytest.mark.asyncio
async def test_ai_back_from_confirm_to_q2(ai_client: TestClient) -> None:
    """User goes back from confirm_recommendations to Q2,
    re-answers Q2, and continues."""

    async def _mock_send_to_ai(*args, **kwargs):
        return _SAMPLE_AI_RESPONSE

    with patch("src.handlers.ai_assistant.send_to_ai", _mock_send_to_ai):
        resp = await ai_client.send_callback("new_habit:ai")
        resp = await ai_client.send_message("бег")

        resp = await ai_client.send_callback("assist:intensity:beginner")
        resp = await ai_client.send_callback("assist:duration:30")
        assert "SMART-план" in resp.text

        # Go back to Q2
        resp = await ai_client.send_callback("nav:back")
        assert "минут" in resp.text.lower()

        # Re-answer Q2
        resp = await ai_client.send_callback("assist:duration:60")
        assert "SMART-план" in resp.text

        resp = await ai_client.send_callback("assist:yes")
        assert "Привычка успешно создана" in resp.text


# ---------------------------------------------------------------------------
# A3: AI waiting indicator
# ---------------------------------------------------------------------------


def _captured_texts(client: TestClient) -> list[str]:
    """Return non-empty texts from the bot session capture buffer."""
    session = client.bot.session
    return [m.text for m in session.captured if m.text]


@pytest.mark.asyncio
async def test_ai_waiting_indicator_message_path_success(
    ai_client: TestClient,
) -> None:
    """Message Q2 path: waiting placeholder then SMART plan on success."""

    async def _mock_send_to_ai(*args, **kwargs):
        return _SAMPLE_AI_RESPONSE

    from src.handlers.ai_assistant import AI_WAITING_TEXT

    with patch("src.handlers.ai_assistant.send_to_ai", _mock_send_to_ai):
        await ai_client.send_callback("new_habit:ai")
        await ai_client.send_message("читать книги")
        await ai_client.send_callback("assist:freq:daily")

        # Q2 text answer triggers AI call
        resp = await ai_client.send_message("Нет времени")
        texts = _captured_texts(ai_client)

        assert any(AI_WAITING_TEXT in (t or "") for t in texts) or (
            AI_WAITING_TEXT in (resp.text or "")
        )
        assert "SMART-план" in (resp.text or "")
        assert "Morning run" in (resp.text or "")


@pytest.mark.asyncio
async def test_ai_waiting_indicator_callback_path_success(
    ai_client: TestClient,
) -> None:
    """Callback Q2 path: waiting placeholder then SMART plan on success."""

    async def _mock_send_to_ai(*args, **kwargs):
        return _SAMPLE_AI_RESPONSE

    from src.handlers.ai_assistant import AI_WAITING_TEXT

    with patch("src.handlers.ai_assistant.send_to_ai", _mock_send_to_ai):
        await ai_client.send_callback("new_habit:ai")
        await ai_client.send_message("бег")
        await ai_client.send_callback("assist:intensity:beginner")

        resp = await ai_client.send_callback("assist:duration:30")
        texts = _captured_texts(ai_client)

        assert any(AI_WAITING_TEXT in (t or "") for t in texts) or (
            AI_WAITING_TEXT in (resp.text or "")
        )
        assert "SMART-план" in (resp.text or "")


@pytest.mark.asyncio
async def test_ai_waiting_indicator_message_path_error(
    ai_client: TestClient,
) -> None:
    """Message Q2 path: waiting then friendly error when AI returns None."""

    async def _mock_send_to_ai(*args, **kwargs):
        return None

    from src.handlers.ai_assistant import AI_WAITING_TEXT

    with patch("src.handlers.ai_assistant.send_to_ai", _mock_send_to_ai):
        await ai_client.send_callback("new_habit:ai")
        await ai_client.send_message("читать книги")
        await ai_client.send_callback("assist:freq:daily")

        resp = await ai_client.send_message("Нет времени")
        texts = _captured_texts(ai_client)

        assert any(AI_WAITING_TEXT in (t or "") for t in texts) or (
            AI_WAITING_TEXT in (resp.text or "")
        )
        assert "ИИ временно недоступен" in (resp.text or "")


@pytest.mark.asyncio
async def test_ai_waiting_indicator_callback_path_error(
    ai_client: TestClient,
) -> None:
    """Callback Q2 path: waiting then friendly error when AI returns None."""

    async def _mock_send_to_ai(*args, **kwargs):
        return None

    from src.handlers.ai_assistant import AI_WAITING_TEXT

    with patch("src.handlers.ai_assistant.send_to_ai", _mock_send_to_ai):
        await ai_client.send_callback("new_habit:ai")
        await ai_client.send_message("бег")
        await ai_client.send_callback("assist:skip")

        resp = await ai_client.send_callback("assist:skip")
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
    from unittest.mock import AsyncMock

    from aiogram.types import Chat, Message
    from src.handlers.ai_assistant import _deliver_ai_result

    bot = ai_client.bot
    chat = Chat(id=123456, type="private")
    placeholder = Message(message_id=99, date=0, chat=chat, text="waiting")

    # Force edit to fail, send_message to succeed
    bot.edit_message_text = AsyncMock(side_effect=RuntimeError("edit failed"))
    sent = Message(message_id=100, date=0, chat=chat, text="final")
    bot.send_message = AsyncMock(return_value=sent)
    bot.delete_message = AsyncMock(return_value=True)

    user_msg = Message(
        message_id=1,
        date=0,
        chat=chat,
        text="q2",
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
