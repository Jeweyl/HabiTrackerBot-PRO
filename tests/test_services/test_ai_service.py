"""Unit tests for the OpenRouter AI service (src/services/ai_service.py)."""

import json
import logging
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.services.ai_service import build_prompt, send_to_ai


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
