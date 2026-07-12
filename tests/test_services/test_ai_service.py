"""Unit tests for the OpenRouter AI service (src/services/ai_service.py)."""

import asyncio
import json
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.ai_schema import ProposePlan
from src.services.ai_service import (
    build_prompt,
    build_prompt_v2,
    send_to_ai,
    send_to_ai_parsed,
)




# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

_SAMPLE_AI_RESPONSE: dict[str, Any] = {
    "refined_habit": "Morning run",
    "metric_name": "distance",
    "metric_unit": "km",
    "target_per_day": 5,
    "period": "daily",
    "comment": "Start slowly, increase distance over time.",
}


def _build_mock_response(status: int, json_data: Any) -> AsyncMock:
    """Create an AsyncMock that behaves like an aiohttp response context manager.

    Args:
        status: HTTP status code to return.
        json_data: Value to return from ``.json()`` (or ``.text()`` if status != 200).

    Returns:
        An AsyncMock configured as a context manager wrapping a mock response.
    """
    mock_response = AsyncMock()
    mock_response.status = status
    mock_response.__aenter__.return_value = mock_response

    if status == 200:
        mock_response.json.return_value = json_data
    else:
        mock_response.text.return_value = "Internal Server Error"

    return mock_response


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_to_ai_success(caplog: pytest.LogCaptureFixture) -> None:
    """send_to_ai should parse valid JSON from the AI response."""
    content = json.dumps(_SAMPLE_AI_RESPONSE)
    mock_api_response = {"choices": [{"message": {"content": content}}]}
    mock_response = _build_mock_response(200, mock_api_response)

    with patch("aiohttp.ClientSession.post", return_value=mock_response):
        result = await send_to_ai("Test prompt")

    assert result == _SAMPLE_AI_RESPONSE
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_send_to_ai_invalid_json(caplog: pytest.LogCaptureFixture) -> None:
    """send_to_ai should return None when the content is not valid JSON."""
    plain_text = "This is just plain text, not JSON."
    mock_api_response = {"choices": [{"message": {"content": plain_text}}]}
    mock_response = _build_mock_response(200, mock_api_response)

    with caplog.at_level(logging.WARNING):
        with patch("aiohttp.ClientSession.post", return_value=mock_response):
            result = await send_to_ai("Test prompt")

    assert result is None
    assert any("non-JSON content" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_send_to_ai_error_status(caplog: pytest.LogCaptureFixture) -> None:
    """send_to_ai should return None when the API returns a non-200 status."""
    mock_response = _build_mock_response(500, {})

    with caplog.at_level(logging.ERROR):
        with patch("aiohttp.ClientSession.post", return_value=mock_response):
            result = await send_to_ai("Test prompt")

    assert result is None
    assert any("status 500" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_send_to_ai_timeout_returns_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """send_to_ai must return None on timeout and must not raise."""
    with caplog.at_level(logging.ERROR):
        with patch(
            "aiohttp.ClientSession.post",
            side_effect=asyncio.TimeoutError(),
        ):
            result = await send_to_ai("Test prompt")

    assert result is None


@pytest.mark.asyncio
async def test_send_to_ai_uses_settings_ai_timeout() -> None:
    """OpenRouter ClientTimeout.total must come from settings.AI_TIMEOUT."""
    content = json.dumps(_SAMPLE_AI_RESPONSE)
    mock_api_response = {"choices": [{"message": {"content": content}}]}
    mock_response = _build_mock_response(200, mock_api_response)

    with (
        patch("src.services.ai_service.settings") as mock_settings,
        patch("aiohttp.ClientSession") as mock_session_cls,
        patch("aiohttp.ClientTimeout") as mock_timeout_cls,
    ):
        mock_settings.AI_TIMEOUT = 42
        mock_settings.AI_MODEL = "test-model"
        mock_settings.AI_FALLBACK_MODEL = "test-fallback"
        mock_settings.ROUTER_API_KEY = "test-key"

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session_cls.return_value = mock_session

        result = await send_to_ai("Test prompt")

    mock_timeout_cls.assert_called_with(total=42)
    assert result == _SAMPLE_AI_RESPONSE


def test_build_prompt() -> None:

    """build_prompt should include habit title and adaptive answers, handle
    missing keys and skipped values."""
    # All values present
    habit_title = "Morning run"
    answers = {
        "q1": "Beginner",
        "q2": "30 minutes",
    }
    prompt = build_prompt(habit_title, answers)

    assert "Morning run" in prompt
    assert "q1" in prompt
    assert "Beginner" in prompt
    assert "q2" in prompt
    assert "30 minutes" in prompt
    assert "SMART goal" in prompt
    assert "refined_habit" in prompt

    # Some values skipped / None
    answers_partial = {
        "q1": "Утром",
        "q2": "Пропущено",
    }
    prompt_partial = build_prompt("чистить зубы", answers_partial)

    assert "чистить зубы" in prompt_partial
    assert "q1" in prompt_partial
    assert "Утром" in prompt_partial
    # q2 is skipped, should not appear in the answers text
    assert "Пропущено" not in prompt_partial

    # All skipped or empty
    answers_empty: dict = {}
    prompt_empty = build_prompt("читать книги", answers_empty)

    assert "читать книги" in prompt_empty
    assert "No additional details provided" in prompt_empty


def test_build_prompt_v2() -> None:
    """build_prompt_v2 must request the strict AIResponse contract."""
    habit_title = "Morning run"
    answers = {
        "q1": "Beginner",
        "q2": "30 minutes",
    }
    prompt = build_prompt_v2(habit_title, answers)

    assert "Morning run" in prompt
    assert "Beginner" in prompt
    assert "30 minutes" in prompt
    assert "propose_plan" in prompt
    assert "ask_questions" in prompt
    assert "start_time" in prompt
    assert "duration_minutes" in prompt
    assert ":00" in prompt or "00,15,30,45" in prompt or "{00,15,30,45}" in prompt
    # Legacy SMART keys must not be required by v2
    assert "refined_habit" not in prompt
    assert "target_per_day" not in prompt

    # Skipped answers omitted; empty answers safe
    prompt_partial = build_prompt_v2(
        "чистить зубы",
        {"q1": "Утром", "q2": "Пропущено"},
    )
    assert "чистить зубы" in prompt_partial
    assert "Утром" in prompt_partial
    assert "Пропущено" not in prompt_partial

    prompt_empty = build_prompt_v2("читать книги", {})
    assert "читать книги" in prompt_empty
    assert "No additional details provided" in prompt_empty


@pytest.mark.asyncio
async def test_send_to_ai_parsed_valid_propose_plan() -> None:
    """send_to_ai_parsed returns ProposePlan for a schema-valid payload."""
    payload = {
        "type": "propose_plan",
        "title": "Morning run",
        "start_time": "08:00",
        "end_time": "08:30",
        "frequency": "daily",
        "duration_minutes": 30,
        "comment": "Start slowly.",
    }
    content = json.dumps(payload)
    mock_api_response = {"choices": [{"message": {"content": content}}]}
    mock_response = _build_mock_response(200, mock_api_response)

    with patch("aiohttp.ClientSession.post", return_value=mock_response):
        result = await send_to_ai_parsed("Test prompt v2")

    assert isinstance(result, ProposePlan)
    assert result.title == "Morning run"
    assert result.start_time == "08:00"
    assert result.duration_minutes == 30


@pytest.mark.asyncio
async def test_send_to_ai_parsed_rejects_invalid_schema(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """send_to_ai_parsed returns None when JSON is valid but schema is not."""
    # Legacy SMART shape — not the B1 contract
    content = json.dumps(_SAMPLE_AI_RESPONSE)
    mock_api_response = {"choices": [{"message": {"content": content}}]}
    mock_response = _build_mock_response(200, mock_api_response)

    with caplog.at_level(logging.WARNING):
        with patch("aiohttp.ClientSession.post", return_value=mock_response):
            result = await send_to_ai_parsed("Test prompt v2")

    assert result is None


@pytest.mark.asyncio
async def test_send_to_ai_parsed_none_on_timeout() -> None:
    """send_to_ai_parsed must return None on timeout and must not raise."""
    with patch(
        "aiohttp.ClientSession.post",
        side_effect=asyncio.TimeoutError(),
    ):
        result = await send_to_ai_parsed("Test prompt v2")

    assert result is None


