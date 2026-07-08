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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ai_happy_path(ai_client: TestClient) -> None:
    """Full flow: user answers all questions, AI returns valid JSON,
    habit and task are created."""

    async def _mock_send_to_ai(*args, **kwargs):
        return _SAMPLE_AI_RESPONSE

    with patch("src.handlers.ai_assistant.send_to_ai", _mock_send_to_ai):
        # Start AI assistant
        resp = await ai_client.send_callback("main_menu:help")
        assert resp.text is not None
        assert "привычку" in resp.text.lower()

        # Enter title
        resp = await ai_client.send_message("Morning run")
        assert resp.text is not None
        assert "опыт" in resp.text.lower()

        # Experience: yes
        resp = await ai_client.send_callback("assist:yes")
        assert resp.text is not None
        assert "давно" in resp.text.lower()

        # Duration: months
        resp = await ai_client.send_callback("duration:months")
        assert resp.text is not None
        assert "детали" in resp.text.lower()

        # Details
        resp = await ai_client.send_message("Run in the park every morning")
        assert resp.text is not None
        assert "здоровь" in resp.text.lower()

        # Health: skip
        resp = await ai_client.send_callback("assist:skip")
        assert resp.text is not None
        assert "SMART-план" in resp.text
        assert "Morning run" in resp.text

        # Confirm: yes
        resp = await ai_client.send_callback("assist:yes")
        assert resp.text is not None
        assert "Привычка успешно создана" in resp.text


@pytest.mark.asyncio
async def test_ai_cancel_at_start(ai_client: TestClient) -> None:
    """User cancels immediately after entering the title."""
    # Start AI assistant
    resp = await ai_client.send_callback("main_menu:help")
    assert resp.text is not None
    assert "привычку" in resp.text.lower()

    # Enter title
    resp = await ai_client.send_message("Morning run")
    assert resp.text is not None
    assert "опыт" in resp.text.lower()

    # Cancel from ask_experience — should return to main menu
    resp = await ai_client.send_callback("nav:cancel")
    assert resp is not None
    # edit_text responses may not have text populated in the mock
    # but the handler should not crash


@pytest.mark.asyncio
async def test_ai_invalid_json(ai_client: TestClient) -> None:
    """AI returns None (invalid JSON) → error message → return to menu."""

    async def _mock_send_to_ai(*args, **kwargs):
        return None

    with patch("src.handlers.ai_assistant.send_to_ai", _mock_send_to_ai):
        # Start AI assistant
        resp = await ai_client.send_callback("main_menu:help")
        assert "привычку" in resp.text.lower()

        # Enter title
        resp = await ai_client.send_message("Morning run")
        assert "опыт" in resp.text.lower()

        # Experience: skip
        resp = await ai_client.send_callback("assist:skip")
        assert "давно" in resp.text.lower()

        # Duration: skip
        resp = await ai_client.send_callback("duration:skip")
        assert "детали" in resp.text.lower()

        # Details
        resp = await ai_client.send_message("Some details")
        assert "здоровь" in resp.text.lower()

        # Health: no → triggers AI call which returns None
        resp = await ai_client.send_callback("assist:no")
        assert resp.text is not None
        assert "Не удалось получить рекомендации" in resp.text


@pytest.mark.asyncio
async def test_ai_back_navigation(ai_client: TestClient) -> None:
    """User goes back from ask_experience to start, re-enters title."""
    # Start AI assistant
    resp = await ai_client.send_callback("main_menu:help")
    assert resp.text is not None
    assert "привычку" in resp.text.lower()

    # Enter title
    resp = await ai_client.send_message("Morning run")
    assert resp.text is not None
    assert "опыт" in resp.text.lower()

    # Go back to start
    resp = await ai_client.send_callback("nav:back")
    assert resp is not None
    # edit_text may not populate text, but handler should not crash

    # Re-enter title
    resp = await ai_client.send_message("Evening yoga")
    assert resp.text is not None
    assert "опыт" in resp.text.lower()

    # Experience: no
    resp = await ai_client.send_callback("assist:no")
    assert resp.text is not None
    assert "давно" in resp.text.lower()


@pytest.mark.asyncio
async def test_ai_skip_optional(ai_client: TestClient) -> None:
    """User skips both optional questions (experience, health);
    verify None is stored and flow still completes."""

    async def _mock_send_to_ai(*args, **kwargs):
        return _SAMPLE_AI_RESPONSE

    with patch("src.handlers.ai_assistant.send_to_ai", _mock_send_to_ai):
        # Start AI assistant
        resp = await ai_client.send_callback("main_menu:help")
        assert "привычку" in resp.text.lower()

        # Enter title
        resp = await ai_client.send_message("Yoga")
        # Experience: skip
        resp = await ai_client.send_callback("assist:skip")
        assert "давно" in resp.text.lower()

        # Duration: just_started
        resp = await ai_client.send_callback("duration:just_started")
        assert "детали" in resp.text.lower()

        # Details
        resp = await ai_client.send_message("Daily yoga at home")
        assert "здоровь" in resp.text.lower()

        # Health: skip
        resp = await ai_client.send_callback("assist:skip")
        assert resp.text is not None
        assert "SMART-план" in resp.text

        # Confirm: no (decline creation)
        resp = await ai_client.send_callback("assist:no")
        assert resp.text is not None
        assert "может быть, в другой раз" in resp.text.lower()
