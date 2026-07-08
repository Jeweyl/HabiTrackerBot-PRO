"""Asynchronous service for communicating with the OpenRouter API."""

import json
import logging

import aiohttp

from src.config import settings

logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
"""OpenRouter chat completions endpoint."""


async def send_to_ai(
    prompt: str,
    model: str | None = None,
) -> dict | None:
    """Send a prompt to the OpenRouter API and return the parsed JSON response.

    Performs an asynchronous POST request to the OpenRouter chat completions
    endpoint.  On success, extracts the text content from the first choice,
    attempts to parse it as JSON, and returns the resulting dictionary.

    Args:
        prompt: The user prompt to send to the AI model.
        model: Optional model identifier override.  Defaults to
            ``settings.AI_MODEL`` ("google/gemini-1.5-flash") when ``None``.

    Returns:
        A dictionary parsed from the AI's JSON response, or ``None`` if the
        request failed, the response was not valid JSON, or the status code
        was not 200.
    """
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model or settings.AI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 500,
    }

    timeout = aiohttp.ClientTimeout(total=15)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                OPENROUTER_API_URL,
                headers=headers,
                json=payload,
            ) as response:
                if response.status != 200:
                    response_text = await response.text()
                    logger.error(
                        "OpenRouter API returned status %d: %s",
                        response.status,
                        response_text[:500],
                    )
                    return None

                data = await response.json()
    except aiohttp.ClientError as exc:
        logger.error("Network error calling OpenRouter API: %s", exc)
        return None
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("Failed to parse OpenRouter response JSON: %s", exc)
        return None
    except Exception as exc:
        logger.error("Unexpected error calling OpenRouter API: %s", exc)
        return None

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        logger.error(
            "Unexpected OpenRouter response structure: %s",
            exc,
        )
        return None

    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        logger.warning(
            "OpenRouter returned non-JSON content; raw: %s...",
            str(content)[:200],
        )
        return None

    if not isinstance(parsed, dict):
        logger.warning(
            "OpenRouter returned JSON that is not a dict: %s",
            type(parsed).__name__,
        )
        return None

    return parsed


def build_prompt(user_answers: dict) -> str:
    """Construct a structured AI prompt from the user's FSM-collected answers.

    Formats the collected answers into a clear instruction for the AI model
    to generate a SMART goal plan.  Missing or ``None`` values are replaced
    with ``"Not provided"``.

    Args:
        user_answers: Dictionary with keys ``title``, ``experience``,
            ``duration``, ``details``, and ``health``.  Any key may be
            absent or have a ``None`` value.

    Returns:
        A formatted prompt string ready to be sent to ``send_to_ai``.
    """
    title = user_answers.get("title") or "Not provided"
    experience = user_answers.get("experience") or "Not provided"
    duration = user_answers.get("duration") or "Not provided"
    details = user_answers.get("details") or "Not provided"
    health = user_answers.get("health") or "Not provided"

    prompt = (
        "You are a habit coach. The user wants to develop the habit: "
        f"'{title}'. "
        f"Experience: {experience}. "
        f"Duration: {duration}. "
        f"Details: {details}. "
        f"Health concerns: {health}. "
        "Please convert this into a SMART goal and return ONLY a valid JSON "
        "with the following keys: refined_habit, metric_name, metric_unit, "
        "target_per_day (integer), period ('daily'/'weekly'), comment (string)."
    )

    return prompt
