"""Asynchronous service for communicating with the OpenRouter API."""

import json
import logging

import aiohttp

from src.config import settings

logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
"""OpenRouter chat completions endpoint."""


async def _call_openrouter(
    prompt: str,
    model: str,
) -> dict | None:
    """Make a single OpenRouter API call and return the parsed JSON dict.

    Args:
        prompt: The user prompt to send.
        model: The model identifier to use.

    Returns:
        Parsed JSON dict on success, or ``None`` on any failure.
    """
    headers = {
        "Authorization": f"Bearer {settings.ROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
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

    # Guard against None / empty content
    if not content or (isinstance(content, str) and not content.strip()):
        logger.warning(
            "OpenRouter model '%s' returned empty content (None or blank).",
            model,
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


async def send_to_ai(
    prompt: str,
    model: str | None = None,
) -> dict | None:
    """Send a prompt to the OpenRouter API and return the parsed JSON response.

    Tries the primary model first.  If it returns an empty response (content
    is ``None``), retries once with the fallback model defined in
    ``settings.AI_FALLBACK_MODEL``.

    Args:
        prompt: The user prompt to send to the AI model.
        model: Optional model identifier override.  Defaults to
            ``settings.AI_MODEL`` ("google/gemini-1.5-flash") when ``None``.

    Returns:
        A dictionary parsed from the AI's JSON response, or ``None`` if all
        attempts failed.
    """
    primary_model = model or settings.AI_MODEL
    fallback_model = settings.AI_FALLBACK_MODEL

    result = await _call_openrouter(prompt, primary_model)
    if result is not None:
        return result

    if fallback_model and fallback_model != primary_model:
        logger.info(
            "Primary model '%s' returned empty; retrying with fallback '%s'.",
            primary_model,
            fallback_model,
        )
        result = await _call_openrouter(prompt, fallback_model)
        if result is not None:
            return result

    return None


def build_prompt(habit_title: str, answers: dict) -> str:
    """Construct a structured AI prompt from the habit title and adaptive answers.

    Formats the collected answers into a clear instruction for the AI model
    to generate a SMART goal plan.  Missing or ``None`` values are replaced
    with ``"Not provided"``.

    Args:
        habit_title: The habit title entered by the user.
        answers: Dictionary with adaptive question answers.  Keys vary
            depending on the keyword-matched question flow.  Any value may
            be ``None`` or absent.

    Returns:
        A formatted prompt string ready to be sent to ``send_to_ai``.
    """
    # Build a natural-language summary of the answers
    answers_parts: list[str] = []
    for key, value in answers.items():
        if value and value != "Пропущено":
            answers_parts.append(f"{key}: {value}")

    answers_text = (
        "; ".join(answers_parts) if answers_parts else "No additional details provided"
    )

    prompt = (
        "You are a habit coach. The user wants to develop the habit: "
        f"'{habit_title}'. "
        f"They mentioned: {answers_text}. "
        "Based on this, please convert this into a SMART goal and return "
        "ONLY a valid JSON with the following keys: "
        "refined_habit, metric_name, metric_unit, "
        "target_per_day (integer), period ('daily'/'weekly'), comment (string)."
    )

    return prompt
