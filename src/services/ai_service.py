"""Asynchronous service for communicating with the OpenRouter API."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

from src.config import settings
from src.services.ai_schema import (
    AskQuestions,
    ProposePlan,
    parse_ai_response,
)


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
        "max_tokens": 1000,
    }

    timeout = aiohttp.ClientTimeout(total=settings.AI_TIMEOUT)

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
    except (aiohttp.ClientError, asyncio.TimeoutError, TimeoutError) as exc:
        logger.error("Network/timeout error calling OpenRouter API: %s", exc)
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
            "OpenRouter model '%s' returned empty content (None or blank). "
            "Raw response: %s",
            model,
            str(data)[:500],
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
            ``settings.AI_MODEL`` ("deepseek/deepseek-v4-flash") when ``None``.

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


def build_prompt_v2(habit_title: str, answers: dict) -> str:
    """Build a v2 prompt that requests the strict AIResponse JSON contract.

    The model must return **only** one of two JSON objects (no markdown, no
    prose outside JSON):

    * ``{"type":"ask_questions","questions":[...],"context":...}``
    * ``{"type":"propose_plan","title":...,"start_time":"HH:MM",...}``

    Time rules (enforced by the server-side parser as well):
    * minutes only ``:00`` / ``:15`` / ``:30`` / ``:45``
    * if both ``start_time`` and ``end_time`` and ``duration_minutes`` are set,
      ``duration_minutes`` must equal ``end - start`` (same day)
    * ``frequency`` ∈ ``daily`` | ``weekdays`` | ``weekends``

    Args:
        habit_title: The habit title entered by the user.
        answers: Adaptive question answers; missing/``None``/skipped values
            are omitted from the prompt text.

    Returns:
        A formatted prompt string ready for ``send_to_ai`` /
        ``send_to_ai_parsed``.
    """
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
        "Respond with ONLY a single valid JSON object (no markdown fences, "
        "no commentary) matching exactly one of these shapes:\n"
        "1) Ask clarifying questions:\n"
        '{"type":"ask_questions","questions":["..."],"context":"optional"}\n'
        "2) Propose a concrete plan:\n"
        '{"type":"propose_plan","title":"...","start_time":"HH:MM",'
        '"end_time":"HH:MM"|null,"frequency":"daily"|"weekdays"|"weekends"|null,'
        '"duration_minutes":integer|null,"comment":"...",'
        '"schedule_ops":null|[{"op":"set_schedule","start_time":"HH:MM",'
        '"end_time":"HH:MM"|null,"frequency":"daily"|"weekdays"|"weekends"|null}]}\n'
        "Rules:\n"
        "- Times must be zero-padded HH:MM with minutes in {00,15,30,45}.\n"
        "- If start_time, end_time and duration_minutes are all set, "
        "duration_minutes MUST equal (end_time - start_time) in minutes "
        "on the same calendar day (no overnight ranges).\n"
        "- duration_minutes, when set, must be a positive multiple of 15.\n"
        "- frequency must be one of: daily, weekdays, weekends.\n"
        "- Prefer propose_plan when you have enough information; "
        "otherwise use ask_questions.\n"
        "- Do not invent metrics outside this schema."
    )

    return prompt


async def send_to_ai_parsed(
    prompt: str,
    model: str | None = None,
) -> AskQuestions | ProposePlan | None:
    """Call OpenRouter and validate the payload against the B1 JSON schema.

    Combines :func:`send_to_ai` with :func:`parse_ai_response`. Returns
    ``None`` on network failure, empty content, or schema validation errors.
    Does not write to the database.

    Args:
        prompt: The user prompt to send to the AI model.
        model: Optional model identifier override.

    Returns:
        Validated ``AskQuestions`` or ``ProposePlan``, or ``None``.
    """
    raw: dict[str, Any] | None = await send_to_ai(prompt, model=model)
    return parse_ai_response(raw)


