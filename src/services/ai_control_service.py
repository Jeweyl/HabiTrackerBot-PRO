"""Free-form AI control: prompt building and OpenRouter parse for intents."""

from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import Any

from src.services.ai_schema import (
    AskQuestions,
    ControlCompleteTask,
    ControlCreateTask,
    ControlDeleteTask,
    ControlMessage,
    ControlOpenMenu,
    parse_control_response,
)
from src.services.ai_service import send_to_ai

logger = logging.getLogger(__name__)

MAX_CONTROL_CLARIFY_ROUNDS = 2
"""Maximum ask_questions rounds for free-form control before force-best-effort."""


def format_task_line(task: Any) -> str:
    """One-line schedule summary for control context."""
    tid = getattr(task, "id", "?")
    title = (getattr(task, "title", None) or "").strip() or "—"
    start = getattr(task, "start_time", None)
    end = getattr(task, "end_time", None)
    done = bool(getattr(task, "is_completed", False))
    if start is None:
        time_s = "untimed"
    else:
        time_s = start.strftime("%H:%M") if hasattr(start, "strftime") else str(start)
        if end is not None:
            end_s = end.strftime("%H:%M") if hasattr(end, "strftime") else str(end)
            time_s = f"{time_s}-{end_s}"
    flag = "done" if done else "open"
    return f"id={tid} [{flag}] {time_s} {title}"


def build_control_context(
    *,
    language: str,
    timezone: str,
    local_now_dt: datetime,
    tasks_today: list[Any] | None = None,
    tasks_nearby: list[Any] | None = None,
) -> str:
    """Build a compact schedule context block for the control prompt."""
    local_date = local_now_dt.date().isoformat()
    local_time = local_now_dt.strftime("%H:%M")
    lines = [
        f"language={language or 'ru'}",
        f"timezone={timezone or 'UTC'}",
        f"local_now_date={local_date}",
        f"local_now_time={local_time}",
        "tasks_today:",
    ]
    today_list = list(tasks_today or [])
    if not today_list:
        lines.append("  (none)")
    else:
        for task in today_list[:30]:
            lines.append(f"  {format_task_line(task)}")

    nearby = list(tasks_nearby or [])
    if nearby:
        lines.append("tasks_nearby:")
        for task in nearby[:20]:
            d = getattr(task, "date", None)
            d_s = d.isoformat() if hasattr(d, "isoformat") else str(d)
            lines.append(f"  {d_s} {format_task_line(task)}")
    return "\n".join(lines)


def build_control_prompt(
    *,
    user_text: str,
    language: str = "ru",
    timezone: str = "UTC",
    local_now_dt: datetime | None = None,
    context_block: str = "",
    answers: dict[str, str] | None = None,
    clarifying_round: int = 0,
    force_action: bool = False,
) -> str:
    """Build the free-form control system+user prompt (single user message).

    The model must return **only** one JSON object matching the control schema.
    """
    now = local_now_dt or datetime.now()
    local_date = now.date().isoformat()
    local_time = now.strftime("%H:%M")
    answers = answers or {}
    answers_parts = [
        f"{k}: {v}" for k, v in answers.items() if v and v != "Пропущено"
    ]
    answers_text = (
        "; ".join(answers_parts) if answers_parts else "(none)"
    )
    rounds_left = max(0, MAX_CONTROL_CLARIFY_ROUNDS - int(clarifying_round or 0))

    force_line = (
        "CRITICAL: You MUST return an action now (create_task, delete_task, "
        "complete_task, open_menu, or message). Do NOT return ask_questions. "
        "Use reasonable defaults for missing details.\n"
        if force_action
        else (
            f"You may ask clarifying questions in at most {rounds_left} more "
            f"round(s) (max {MAX_CONTROL_CLARIFY_ROUNDS} total). "
            "Prefer executing when slots are complete. "
            "When asking, prefer kind=choice with 2–6 short options so the "
            "user can tap buttons instead of typing.\n"
        )
    )

    context = context_block.strip() or (
        f"language={language or 'ru'}\ntimezone={timezone or 'UTC'}\n"
        f"local_now_date={local_date}\nlocal_now_time={local_time}\n"
        "tasks_today:\n  (none)"
    )

    return (
        "You are HabiTracker's free-form control assistant. The user writes in "
        "natural language; you return ONE JSON intent to execute in the bot.\n"
        f"User language: {language or 'ru'}. User timezone: {timezone or 'UTC'}.\n"
        f"Authoritative local clock: date={local_date} time={local_time}. "
        "NEVER ask what day/time it is — use this clock.\n"
        f"Schedule context:\n{context}\n"
        f"User message: {user_text!r}\n"
        f"Answers so far: {answers_text}.\n"
        f"Clarifying rounds already used: {int(clarifying_round or 0)}/"
        f"{MAX_CONTROL_CLARIFY_ROUNDS}.\n"
        f"{force_line}"
        "Respond with ONLY a single valid JSON object (no markdown fences, "
        "no commentary) matching exactly one of these shapes:\n"
        "1) Clarify:\n"
        '{"type":"ask_questions","questions":['
        '{"text":"...","kind":"text"|"choice"|"time","options":["a","b"]|null}'
        '],"context":"optional"}\n'
        "2) Create one-off task:\n"
        '{"type":"create_task","title":"...","date":"YYYY-MM-DD"|null,'
        '"start_time":"HH:MM"|null,"end_time":"HH:MM"|null,'
        '"relative_minutes":integer|null,"auto_rollover":false,"comment":""}\n'
        "3) Delete task:\n"
        '{"type":"delete_task","query":"title fragment"|null,'
        '"date":"YYYY-MM-DD"|null,"task_id":integer|null}\n'
        "4) Complete task:\n"
        '{"type":"complete_task","query":"title fragment"|null,'
        '"date":"YYYY-MM-DD"|null,"task_id":integer|null}\n'
        "5) Open existing menu (no DB write):\n"
        '{"type":"open_menu","target":"new_habit_choice"|"new_habit_manual"|'
        '"new_habit_ai"|"new_task"|"new_task_ai"|"today"|"schedule"|'
        '"habits"|"settings"|"stats"|"help"}\n'
        "6) Plain reply (no side effects):\n"
        '{"type":"message","text":"..."}\n'
        "Rules:\n"
        "- Synonyms: add/put/schedule/remind ≈ create_task; "
        "delete/remove/cancel ≈ delete_task; done/complete/finish ≈ complete_task; "
        "create habit / new habit ≈ open_menu new_habit_choice "
        "(do NOT invent habit fields).\n"
        "- «Напомни / remind me in N minutes» → create_task with "
        "relative_minutes=N (task triggers check-in at that time).\n"
        "- relative_minutes: minutes from local_now; do not invent absolute "
        "clock time when user said «through N minutes».\n"
        "- If user gives only start time (e.g. 15:00) without end → end_time=null.\n"
        "- If no time at all and not relative → start_time=null (untimed todo).\n"
        "- date null → local today. Times HH:MM minutes in {00,15,30,45} when set.\n"
        "- For delete/complete: set query from user wording; use task_id only if "
        "it appears in tasks_today context.\n"
        "- Prefer open_menu for navigation requests (today, settings, habits…).\n"
        "- Do not invent fields outside this schema. Do not claim already saved."
    )


async def send_control_to_ai(
    prompt: str,
    model: str | None = None,
) -> (
    AskQuestions
    | ControlCreateTask
    | ControlDeleteTask
    | ControlCompleteTask
    | ControlOpenMenu
    | ControlMessage
    | None
):
    """Call OpenRouter and parse a control intent. Returns ``None`` on failure."""
    raw = await send_to_ai(prompt, model=model)
    return parse_control_response(raw)


def resolve_relative_start(
    local_now_dt: datetime,
    relative_minutes: int,
) -> tuple[date, time]:
    """Return (date, snapped start_time) for local_now + relative_minutes.

    Snaps to the nearest 15-minute grid (same product policy as AI normalize).
    """
    from datetime import timedelta

    from src.services.ai_normalize import snap_time

    if relative_minutes <= 0:
        raise ValueError("relative_minutes must be positive")
    target = local_now_dt + timedelta(minutes=relative_minutes)
    snapped = snap_time(target.time().replace(second=0, microsecond=0))
    # If snap went backwards past "now", prefer next 15-min slot
    now_t = local_now_dt.time().replace(second=0, microsecond=0)
    if target.date() == local_now_dt.date() and snapped < now_t:
        total = snapped.hour * 60 + snapped.minute + 15
        if total >= 24 * 60:
            next_day = target.date() + timedelta(days=1)
            return next_day, time(0, 0)
        snapped = time(total // 60, total % 60)
    return target.date(), snapped


