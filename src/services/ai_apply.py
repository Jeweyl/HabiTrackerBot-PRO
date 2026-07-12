"""Apply AI ProposePlan to real Habit + generated Tasks (B3).

Confirm path only: no silent DB writes before the user accepts the plan.
Conflicts are never overwritten without an explicit force flag.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone

from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Habit, Task, User, UserAIState
from src.services.ai_normalize import normalize_plan_times
from src.services.ai_schema import (
    ProposePlan,
    ProposeTaskPlan,
    _minutes_between,
    _parse_hh_mm,
)
from src.services.habit_generator import generate_tasks_for_habit
from src.utils.conflict import check_habit_conflicts, is_time_slot_free
from src.utils.time_picker import MINUTES_15
from src.utils.timezone import local_now


logger = logging.getLogger(__name__)

DEFAULT_DAYS_AHEAD = 30
"""Default horizon for task generation after applying a plan."""

VALID_FREQUENCIES = frozenset({"daily", "weekdays", "weekends"})


@dataclass(frozen=True)
class ResolvedSchedule:
    """Concrete schedule fields ready to persist as a Habit."""

    title: str
    start_time: time
    end_time: time
    frequency: str
    duration_minutes: int


@dataclass
class ApplyResult:
    """Outcome of applying a ProposePlan.

    Attributes:
        status: ``ok`` | ``conflict`` | ``error``.
        habit: Created habit when ``status == "ok"``.
        tasks_created: Number of tasks generated on success.
        conflicting: Conflicting habits when ``status == "conflict"``.
        error: Human-readable error when ``status == "error"``.
        resolved: Resolved schedule (set on ok/conflict when parse succeeded).
    """

    status: Literal["ok", "conflict", "error"]
    habit: Habit | None = None
    tasks_created: int = 0
    conflicting: list[Habit] = field(default_factory=list)
    error: str | None = None
    resolved: ResolvedSchedule | None = None


def _add_minutes(start: time, minutes: int) -> time:
    """Return *start* plus *minutes* on the same calendar day.

    Raises:
        ValueError: If the result would cross midnight or minutes invalid.
    """
    if minutes <= 0:
        raise ValueError("duration must be positive")
    total = start.hour * 60 + start.minute + minutes
    if total >= 24 * 60:
        raise ValueError("end time would cross midnight")
    return time(total // 60, total % 60)


def _safe_parse_hh_mm(value: Any) -> time | None:
    """Parse HH:MM on the 15-minute grid; return None on failure."""
    if value is None or not isinstance(value, str):
        return None
    try:
        return _parse_hh_mm(value)
    except (ValueError, TypeError):
        return None


def resolve_plan_schedule(
    plan: ProposePlan | dict[str, Any] | None,
    *,
    fallback_title: str | None = None,
) -> ResolvedSchedule | None:
    """Resolve title/start/end/frequency from a ProposePlan-like payload.

    B5: runs :func:`normalize_plan_times` first (snap grid, duration wins,
    correct+warn). Then:

      1. Top-level (normalized) plan fields
      2. First ``schedule_ops`` entry of op ``set_schedule`` (fills gaps only)
      3. ``end_time`` derived from ``start_time + duration_minutes``

    Does **not** fall back to hardcoded 08:00–09:00. Returns ``None`` when
    start or end cannot be determined safely.

    Args:
        plan: ProposePlan instance, dict dump, or None.
        fallback_title: Title used when plan title is missing/empty.

    Returns:
        ResolvedSchedule or None.
    """
    if plan is None:
        return None

    if isinstance(plan, ProposePlan):
        raw = plan.model_dump()
    elif isinstance(plan, dict):
        raw = dict(plan)
    else:
        return None

    # Optional schedule_ops fill-in before normalize (first set_schedule only)
    ops = raw.get("schedule_ops") or []
    op0: dict[str, Any] = {}
    if isinstance(ops, list) and ops:
        first = ops[0]
        if isinstance(first, dict) and first.get("op") == "set_schedule":
            op0 = first
        elif hasattr(first, "model_dump"):
            dumped = first.model_dump()
            if dumped.get("op") == "set_schedule":
                op0 = dumped

    if not raw.get("start_time") and op0.get("start_time"):
        raw["start_time"] = op0.get("start_time")
    if not raw.get("end_time") and op0.get("end_time"):
        raw["end_time"] = op0.get("end_time")
    if raw.get("frequency") is None and op0.get("frequency"):
        raw["frequency"] = op0.get("frequency")

    title_raw = raw.get("title") or fallback_title or ""
    if not isinstance(title_raw, str):
        title_raw = str(title_raw) if title_raw else ""
    title = title_raw.strip()[:200]
    if not title:
        return None
    raw["title"] = title

    norm = normalize_plan_times(raw, kind="habit")
    if not norm.ok or not norm.plan:
        logger.warning(
            "resolve_plan_schedule: normalize failed: %s", norm.error
        )
        return None

    data = norm.plan
    start = _safe_parse_hh_mm(data.get("start_time"))
    end = _safe_parse_hh_mm(data.get("end_time"))
    duration = data.get("duration_minutes")

    if start is None or end is None or duration is None:
        logger.warning(
            "resolve_plan_schedule: incomplete after normalize "
            "start=%r end=%r duration=%r",
            data.get("start_time"),
            data.get("end_time"),
            duration,
        )
        return None

    if end.minute not in MINUTES_15 or start.minute not in MINUTES_15:
        logger.warning("resolve_plan_schedule: times not on 15-min grid")
        return None

    try:
        span = _minutes_between(start, end)
    except ValueError as exc:
        logger.warning("resolve_plan_schedule: invalid range: %s", exc)
        return None
    if int(duration) != span:
        # Should not happen after normalize; defensive
        logger.warning(
            "resolve_plan_schedule: post-normalize mismatch duration=%s span=%s",
            duration,
            span,
        )
        return None

    frequency = data.get("frequency") or "daily"
    if frequency not in VALID_FREQUENCIES:
        frequency = "daily"

    return ResolvedSchedule(
        title=title,
        start_time=start,
        end_time=end,
        frequency=str(frequency),
        duration_minutes=int(duration),
    )



async def apply_propose_plan(
    session: AsyncSession,
    user: User,
    plan: ProposePlan | dict[str, Any] | None,
    *,
    force: bool = False,
    days_ahead: int = DEFAULT_DAYS_AHEAD,
    fallback_title: str | None = None,
    now_local: datetime | None = None,
    today_override: date | None = None,
) -> ApplyResult:
    """Create Habit + tasks from a confirmed ProposePlan.

    Transactional within the caller's *session* (caller commits). Does not
    overwrite conflicting habits unless *force* is True.

    Args:
        session: Active async DB session (caller owns commit/rollback).
        user: Persisted User row.
        plan: ProposePlan or dict from FSM.
        force: If True, skip conflict blocking and create anyway.
        days_ahead: Task generation horizon.
        fallback_title: Title fallback when plan title empty.
        now_local: Optional fixed "now" in user local TZ (tests).
        today_override: Optional fixed local today (tests).

    Returns:
        ApplyResult with status ok / conflict / error.
    """
    try:
        resolved = resolve_plan_schedule(plan, fallback_title=fallback_title)
    except Exception:
        logger.error("resolve_plan_schedule raised", exc_info=True)
        resolved = None

    if resolved is None:
        return ApplyResult(
            status="error",
            error="Некорректный план: не удалось определить время привычки.",
        )

    try:
        if not force:
            conflicting = await check_habit_conflicts(
                session,
                user.id,
                resolved.start_time,
                resolved.end_time,
                resolved.frequency,
            )
            if conflicting:
                return ApplyResult(
                    status="conflict",
                    conflicting=list(conflicting),
                    resolved=resolved,
                )

        habit = Habit(
            user_id=user.id,
            title=resolved.title,
            start_time=resolved.start_time,
            end_time=resolved.end_time,
            frequency=resolved.frequency,
        )
        session.add(habit)
        await session.flush()

        # Persist AI plan summary (best-effort within same transaction)
        plan_dump: dict[str, Any]
        if isinstance(plan, ProposePlan):
            plan_dump = plan.model_dump()
        elif isinstance(plan, dict):
            plan_dump = dict(plan)
        else:
            plan_dump = {
                "title": resolved.title,
                "start_time": resolved.start_time.strftime("%H:%M"),
                "end_time": resolved.end_time.strftime("%H:%M"),
                "frequency": resolved.frequency,
                "duration_minutes": resolved.duration_minutes,
            }

        try:
            stmt_ai = select(UserAIState).where(UserAIState.user_id == user.id)
            result_ai = await session.execute(stmt_ai)
            ai_state = result_ai.scalar_one_or_none()
            if ai_state is None:
                session.add(UserAIState(user_id=user.id, summary=plan_dump))
            else:
                ai_state.summary = plan_dump
                ai_state.updated_at = datetime.now(timezone.utc)
        except Exception:
            logger.warning(
                "Failed to update UserAIState for user %s", user.id, exc_info=True
            )

        if now_local is None:
            try:
                now_local = local_now(user.timezone or "UTC")
            except Exception:
                now_local = datetime.now(timezone.utc)

        today = today_override if today_override is not None else now_local.date()
        now_time = now_local.time().replace(second=0, microsecond=0)

        tasks_created = await generate_tasks_for_habit(
            habit.id,
            days_ahead=days_ahead,
            today_override=today,
            session=session,
            now_time=now_time,
        )

        return ApplyResult(
            status="ok",
            habit=habit,
            tasks_created=tasks_created,
            resolved=resolved,
        )
    except Exception as exc:
        logger.error(
            "apply_propose_plan failed for user %s: %s",
            getattr(user, "id", None),
            exc,
            exc_info=True,
        )
        # Re-raise so the caller's get_db() rolls back partial habit/tasks.
        raise


# ---------------------------------------------------------------------------
# B4: one-off task apply (no Habit)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedTaskSchedule:
    """Concrete fields ready to persist as a single Task."""

    title: str
    task_date: date
    start_time: time
    end_time: time | None
    duration_minutes: int | None


@dataclass
class TaskApplyResult:
    """Outcome of applying a ProposeTaskPlan.

    Attributes:
        status: ``ok`` | ``conflict`` | ``error``.
        task: Created task when ``status == "ok"``.
        error: Human-readable error when ``status == "error"``.
        resolved: Resolved schedule when parse succeeded.
    """

    status: Literal["ok", "conflict", "error"]
    task: Task | None = None
    error: str | None = None
    resolved: ResolvedTaskSchedule | None = None


def resolve_task_plan(
    plan: ProposeTaskPlan | dict[str, Any] | None,
    *,
    fallback_title: str | None = None,
    default_date: date | None = None,
) -> ResolvedTaskSchedule | None:
    """Resolve title/date/start/end from a ProposeTaskPlan-like payload.

    B5: runs :func:`normalize_plan_times` (kind=task) first. Open-ended tasks
    (no end, no duration) remain allowed.

    Date: plan.date if valid, else *default_date*. Does not create habits.
    Returns ``None`` when start cannot be determined or normalize rejects.

    Args:
        plan: ProposeTaskPlan instance, dict dump, or None.
        fallback_title: Title used when plan title is missing/empty.
        default_date: Fallback date when plan omits date.

    Returns:
        ResolvedTaskSchedule or None.
    """
    if plan is None:
        return None

    if isinstance(plan, ProposeTaskPlan):
        raw = plan.model_dump()
    elif isinstance(plan, dict):
        raw = dict(plan)
    else:
        return None

    title_raw = raw.get("title") or fallback_title or ""
    if not isinstance(title_raw, str):
        title_raw = str(title_raw) if title_raw else ""
    title = title_raw.strip()[:200]
    if not title:
        return None
    raw["title"] = title

    norm = normalize_plan_times(raw, kind="task")
    if not norm.ok or not norm.plan:
        logger.warning("resolve_task_plan: normalize failed: %s", norm.error)
        return None

    data = norm.plan
    start = _safe_parse_hh_mm(data.get("start_time"))
    if start is None:
        logger.warning("resolve_task_plan: missing/invalid start_time")
        return None

    end = _safe_parse_hh_mm(data.get("end_time"))
    duration = data.get("duration_minutes")
    if duration is not None:
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            duration = None

    if end is not None:
        if end.minute not in MINUTES_15 or start.minute not in MINUTES_15:
            logger.warning("resolve_task_plan: times not on 15-min grid")
            return None
        try:
            span = _minutes_between(start, end)
        except ValueError as exc:
            logger.warning("resolve_task_plan: invalid range: %s", exc)
            return None
        if duration is not None and int(duration) != span:
            logger.warning(
                "resolve_task_plan: post-normalize mismatch duration=%s span=%s",
                duration,
                span,
            )
            return None
        duration = span

    task_date: date | None = None
    raw_date = data.get("date")
    if isinstance(raw_date, date) and not isinstance(raw_date, datetime):
        task_date = raw_date
    elif isinstance(raw_date, str) and raw_date.strip():
        try:
            task_date = date.fromisoformat(raw_date.strip())
        except ValueError:
            logger.warning("resolve_task_plan: invalid date %r", raw_date)
            task_date = None

    if task_date is None:
        task_date = default_date
    if task_date is None:
        logger.warning("resolve_task_plan: missing date and default_date")
        return None

    return ResolvedTaskSchedule(
        title=title,
        task_date=task_date,
        start_time=start,
        end_time=end,
        duration_minutes=int(duration) if duration is not None else None,
    )



async def apply_propose_task_plan(
    session: AsyncSession,
    user: User,
    plan: ProposeTaskPlan | dict[str, Any] | None,
    *,
    force: bool = False,
    fallback_title: str | None = None,
    default_date: date | None = None,
) -> TaskApplyResult:
    """Create a single Task from a confirmed ProposeTaskPlan (no Habit).

    Transactional within the caller's *session* (caller commits). Does not
    overwrite conflicting tasks unless *force* is True.

    Args:
        session: Active async DB session (caller owns commit/rollback).
        user: Persisted User row.
        plan: ProposeTaskPlan or dict from FSM.
        force: If True, skip conflict blocking and create anyway.
        fallback_title: Title fallback when plan title empty.
        default_date: Date fallback when plan omits date.

    Returns:
        TaskApplyResult with status ok / conflict / error.
    """
    try:
        resolved = resolve_task_plan(
            plan,
            fallback_title=fallback_title,
            default_date=default_date,
        )
    except Exception:
        logger.error("resolve_task_plan raised", exc_info=True)
        resolved = None

    if resolved is None:
        return TaskApplyResult(
            status="error",
            error="Некорректный план: не удалось определить время задачи.",
        )

    try:
        if not force:
            free = await is_time_slot_free(
                session,
                user.id,
                resolved.task_date,
                resolved.start_time,
                resolved.end_time,
            )
            if not free:
                return TaskApplyResult(
                    status="conflict",
                    resolved=resolved,
                )

        task = Task(
            user_id=user.id,
            habit_id=None,
            title=resolved.title,
            date=resolved.task_date,
            start_time=resolved.start_time,
            end_time=resolved.end_time,
            is_completed=False,
            is_placeholder=False,
        )
        session.add(task)
        await session.flush()

        return TaskApplyResult(
            status="ok",
            task=task,
            resolved=resolved,
        )
    except Exception as exc:
        logger.error(
            "apply_propose_task_plan failed for user %s: %s",
            getattr(user, "id", None),
            exc,
            exc_info=True,
        )
        raise
