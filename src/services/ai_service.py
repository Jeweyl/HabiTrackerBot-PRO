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
    ProposeTaskPlan,
    parse_ai_response,
)

logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
"""OpenRouter chat completions endpoint."""

MAX_CLARIFYING_ROUNDS = 3
"""Maximum number of AI ``ask_questions`` rounds before force-propose / fallback."""



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

    Thin wrapper around :func:`build_multiturn_prompt` without user context.

    Args:
        habit_title: The habit title entered by the user.
        answers: Adaptive question answers; missing/``None``/skipped values
            are omitted from the prompt text.

    Returns:
        A formatted prompt string ready for ``send_to_ai`` /
        ``send_to_ai_parsed``.
    """
    return build_multiturn_prompt(
        habit_title=habit_title,
        answers=answers,
        language="ru",
        timezone="UTC",
        habits_tasks_summary="",
        clarifying_round=0,
        force_propose=False,
    )


def build_user_context_summary(
    *,
    language: str = "ru",
    timezone: str = "UTC",
    habits: list[Any] | None = None,
    tasks: list[Any] | None = None,
) -> str:
    """Build a short natural-language summary of the user's schedule context.

    Never raises. Empty / missing collections produce a safe placeholder.

    Args:
        language: User language code (informational).
        timezone: User timezone string.
        habits: Optional list of habit-like objects with ``title``,
            ``start_time``, ``end_time``, ``frequency``.
        tasks: Optional list of task-like objects with ``title``, ``date``,
            ``start_time``.

    Returns:
        Multi-line summary string for inclusion in the AI prompt.
    """
    habits = habits or []
    tasks = tasks or []

    lines: list[str] = [
        f"language={language or 'ru'}",
        f"timezone={timezone or 'UTC'}",
    ]

    if not habits:
        lines.append("habits: (none)")
    else:
        habit_bits: list[str] = []
        for h in habits[:15]:
            try:
                title = getattr(h, "title", None) or (h.get("title") if isinstance(h, dict) else "?")
                start = getattr(h, "start_time", None)
                if start is None and isinstance(h, dict):
                    start = h.get("start_time")
                end = getattr(h, "end_time", None)
                if end is None and isinstance(h, dict):
                    end = h.get("end_time")
                freq = getattr(h, "frequency", None)
                if freq is None and isinstance(h, dict):
                    freq = h.get("frequency")
                start_s = start.strftime("%H:%M") if hasattr(start, "strftime") else (start or "?")
                end_s = (
                    end.strftime("%H:%M")
                    if hasattr(end, "strftime")
                    else (end if end is not None else "—")
                )
                habit_bits.append(f"{title} {start_s}-{end_s} ({freq or 'daily'})")
            except Exception:  # noqa: BLE001
                continue
        lines.append(
            "habits: " + ("; ".join(habit_bits) if habit_bits else "(none)")
        )

    if not tasks:
        lines.append("tasks: (none)")
    else:
        task_bits: list[str] = []
        for t in tasks[:15]:
            try:
                title = getattr(t, "title", None) or (t.get("title") if isinstance(t, dict) else "?")
                d = getattr(t, "date", None)
                if d is None and isinstance(t, dict):
                    d = t.get("date")
                start = getattr(t, "start_time", None)
                if start is None and isinstance(t, dict):
                    start = t.get("start_time")
                d_s = d.isoformat() if hasattr(d, "isoformat") else (str(d) if d else "?")
                start_s = start.strftime("%H:%M") if hasattr(start, "strftime") else (start or "?")
                task_bits.append(f"{d_s} {start_s} {title}")
            except Exception:  # noqa: BLE001
                continue
        lines.append(
            "tasks: " + ("; ".join(task_bits) if task_bits else "(none)")
        )

    return "\n".join(lines)


def build_multiturn_prompt(
    *,
    habit_title: str,
    answers: dict | None = None,
    language: str = "ru",
    timezone: str = "UTC",
    habits_tasks_summary: str = "",
    clarifying_round: int = 0,
    force_propose: bool = False,
) -> str:
    """Build a multi-turn habit-coach prompt with user context (B2).

    The model must return **only** one of two JSON objects (no markdown, no
    prose outside JSON):

    * ``{"type":"ask_questions","questions":[...],"context":...}``
    * ``{"type":"propose_plan","title":...,"start_time":"HH:MM",...}``

    When *force_propose* is True (after max clarifying rounds), the model is
    instructed to return ``propose_plan`` only.

    Args:
        habit_title: Habit title from the user.
        answers: Collected Q/A so far; skipped/empty values omitted.
        language: User language code.
        timezone: User timezone string.
        habits_tasks_summary: Pre-built summary from
            :func:`build_user_context_summary`.
        clarifying_round: Number of ``ask_questions`` rounds already used
            (0-based before the next call).
        force_propose: If True, forbid further ``ask_questions``.

    Returns:
        Prompt string for :func:`send_to_ai_parsed`.
    """
    answers = answers or {}
    answers_parts: list[str] = []
    for key, value in answers.items():
        if value and value != "Пропущено":
            answers_parts.append(f"{key}: {value}")

    answers_text = (
        "; ".join(answers_parts) if answers_parts else "No additional details provided"
    )

    context_block = habits_tasks_summary.strip() or (
        f"language={language or 'ru'}\ntimezone={timezone or 'UTC'}\n"
        "habits: (none)\ntasks: (none)"
    )

    rounds_left = max(0, MAX_CLARIFYING_ROUNDS - int(clarifying_round or 0))

    force_line = (
        "CRITICAL: You MUST return propose_plan now. Do NOT return ask_questions. "
        "Use reasonable defaults for any missing details.\n"
        if force_propose
        else (
            f"You may ask clarifying questions in at most {rounds_left} more "
            f"round(s) (max {MAX_CLARIFYING_ROUNDS} total). "
            "Prefer propose_plan when you have enough information.\n"
        )
    )

    prompt = (
        "You are a habit coach helping the user create ONE habit.\n"
        f"User language: {language or 'ru'}. User timezone: {timezone or 'UTC'}.\n"
        f"User schedule context:\n{context_block}\n"
        f"Desired habit: '{habit_title}'.\n"
        f"Answers so far: {answers_text}.\n"
        f"Clarifying rounds already used: {int(clarifying_round or 0)}/"
        f"{MAX_CLARIFYING_ROUNDS}.\n"
        f"{force_line}"
        "Respond with ONLY a single valid JSON object (no markdown fences, "
        "no commentary) matching exactly one of these shapes:\n"
        "1) Ask clarifying questions (1–3 questions per round):\n"
        '{"type":"ask_questions","questions":["..."]|'
        '[{"text":"...","kind":"text"|"choice"|"time","options":["a","b"]|null}],'
        '"context":"optional"}\n'
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
        "- Avoid scheduling over existing habits/tasks when possible.\n"
        "- Do not invent fields outside this schema.\n"
        "- Do not create or claim the habit is already saved; only propose."
    )

    return prompt


def build_multiturn_task_prompt(
    *,
    task_title: str,
    answers: dict | None = None,
    language: str = "ru",
    timezone: str = "UTC",
    habits_tasks_summary: str = "",
    default_date: str = "",
    clarifying_round: int = 0,
    force_propose: bool = False,
) -> str:
    """Build a multi-turn prompt for a one-off task (B4), not a habit.

    The model must return **only** one of two JSON objects:

    * ``{"type":"ask_questions","questions":[...],"context":...}``
    * ``{"type":"propose_task","title":...,"date":"YYYY-MM-DD",...}``

    Never propose a habit / frequency / recurring schedule.

    Args:
        task_title: Task description from the user.
        answers: Collected Q/A so far.
        language: User language code.
        timezone: User timezone string.
        habits_tasks_summary: Pre-built schedule context.
        default_date: ISO date the task should land on (YYYY-MM-DD).
        clarifying_round: Number of ask rounds already used.
        force_propose: If True, forbid further ask_questions.

    Returns:
        Prompt string for :func:`send_to_ai_parsed`.
    """
    answers = answers or {}
    answers_parts: list[str] = []
    for key, value in answers.items():
        if value and value != "Пропущено":
            answers_parts.append(f"{key}: {value}")

    answers_text = (
        "; ".join(answers_parts) if answers_parts else "No additional details provided"
    )

    context_block = habits_tasks_summary.strip() or (
        f"language={language or 'ru'}\ntimezone={timezone or 'UTC'}\n"
        "habits: (none)\ntasks: (none)"
    )

    rounds_left = max(0, MAX_CLARIFYING_ROUNDS - int(clarifying_round or 0))
    date_hint = default_date or "today (user local)"

    force_line = (
        "CRITICAL: You MUST return propose_task now. Do NOT return ask_questions. "
        "Use reasonable defaults for any missing details.\n"
        if force_propose
        else (
            f"You may ask clarifying questions in at most {rounds_left} more "
            f"round(s) (max {MAX_CLARIFYING_ROUNDS} total). "
            "Prefer propose_task when you have enough information.\n"
        )
    )

    prompt = (
        "You are a scheduling assistant helping the user create ONE one-off task "
        "(a single calendar item). Do NOT create a habit or recurring plan.\n"
        f"User language: {language or 'ru'}. User timezone: {timezone or 'UTC'}.\n"
        f"User schedule context:\n{context_block}\n"
        f"Desired task: '{task_title}'.\n"
        f"Preferred / default date: {date_hint}.\n"
        f"Answers so far: {answers_text}.\n"
        f"Clarifying rounds already used: {int(clarifying_round or 0)}/"
        f"{MAX_CLARIFYING_ROUNDS}.\n"
        f"{force_line}"
        "Respond with ONLY a single valid JSON object (no markdown fences, "
        "no commentary) matching exactly one of these shapes:\n"
        "1) Ask clarifying questions (1–3 questions per round):\n"
        '{"type":"ask_questions","questions":["..."]|'
        '[{"text":"...","kind":"text"|"choice"|"time","options":["a","b"]|null}],'
        '"context":"optional"}\n'
        "2) Propose a concrete one-off task:\n"
        '{"type":"propose_task","title":"...","date":"YYYY-MM-DD"|null,'
        '"start_time":"HH:MM","end_time":"HH:MM"|null,'
        '"duration_minutes":integer|null,"comment":"..."}\n'
        "Rules:\n"
        "- This is NOT a habit: no frequency, no recurring schedule.\n"
        "- Times must be zero-padded HH:MM with minutes in {00,15,30,45}.\n"
        "- If start_time, end_time and duration_minutes are all set, "
        "duration_minutes MUST equal (end_time - start_time) in minutes "
        "on the same calendar day (no overnight ranges).\n"
        "- duration_minutes, when set, must be a positive multiple of 15.\n"
        "- date must be YYYY-MM-DD when provided; prefer the default date.\n"
        "- Avoid scheduling over existing habits/tasks when possible.\n"
        "- Do not invent fields outside this schema.\n"
        "- Do not claim the task is already saved; only propose."
    )

    return prompt


async def send_to_ai_parsed(
    prompt: str,
    model: str | None = None,
) -> AskQuestions | ProposePlan | ProposeTaskPlan | None:
    """Call OpenRouter and validate the payload against the B1/B4 JSON schema.

    Combines :func:`send_to_ai` with :func:`parse_ai_response`. Returns
    ``None`` on network failure, empty content, or schema validation errors.
    Does not write to the database.

    Args:
        prompt: The user prompt to send to the AI model.
        model: Optional model identifier override.

    Returns:
        Validated ``AskQuestions``, ``ProposePlan``, or ``ProposeTaskPlan``,
        or ``None``.
    """
    raw: dict[str, Any] | None = await send_to_ai(prompt, model=model)
    return parse_ai_response(raw)


