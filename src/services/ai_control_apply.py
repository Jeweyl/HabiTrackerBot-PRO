"""Apply free-form AI control intents (create / delete / complete / match)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Literal


from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Task, User
from src.services.ai_control_service import resolve_relative_start
from src.services.ai_normalize import snap_hh_mm
from src.services.ai_schema import (
    ControlCompleteTask,
    ControlCreateTask,
    ControlDeleteTask,
)
from src.utils.conflict import is_time_slot_free
from src.utils.timezone import local_now

logger = logging.getLogger(__name__)

_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class ResolvedControlTask:
    """Concrete fields ready to persist as a Task from control create."""

    title: str
    task_date: date
    start_time: time | None
    end_time: time | None
    auto_rollover: bool = False


@dataclass
class ControlCreateResult:
    """Outcome of applying create_task."""

    status: Literal["ok", "conflict", "error"]
    task: Task | None = None
    resolved: ResolvedControlTask | None = None
    error: str | None = None


@dataclass
class ControlMatchResult:
    """Outcome of resolving a task target for delete/complete."""

    status: Literal["found", "ambiguous", "not_found", "error"]
    tasks: list[Task] = field(default_factory=list)
    error: str | None = None


@dataclass
class ControlMutateResult:
    """Outcome of delete/complete after a concrete task_id is known."""

    status: Literal["ok", "not_found", "error"]
    task: Task | None = None
    error: str | None = None


def _normalize_query(text: str | None) -> str:
    if not text:
        return ""
    return _WS_RE.sub(" ", text.strip().lower())


def score_task_match(title: str, query: str) -> int:
    """Higher score = better match. 0 = no match."""
    t = _normalize_query(title)
    q = _normalize_query(query)
    if not q or not t:
        return 0
    if t == q:
        return 100
    if q in t:
        return 80
    if t in q:
        return 70
    # token overlap
    t_tokens = set(t.split())
    q_tokens = set(q.split())
    if not q_tokens:
        return 0
    overlap = t_tokens & q_tokens
    if not overlap:
        return 0
    return 40 + int(40 * len(overlap) / max(len(q_tokens), 1))


def filter_tasks_by_query(tasks: list[Task], query: str | None) -> list[Task]:
    """Rank and filter tasks by title similarity to *query*."""
    q = _normalize_query(query)
    if not q:
        return list(tasks)
    scored: list[tuple[int, Task]] = []
    for task in tasks:
        s = score_task_match(task.title or "", q)
        if s > 0:
            scored.append((s, task))
    scored.sort(key=lambda x: (-x[0], x[1].id))
    return [t for _, t in scored]


def resolve_create_task_fields(
    intent: ControlCreateTask | dict[str, Any],
    *,
    local_now_dt: datetime,
    default_date: date | None = None,
) -> ResolvedControlTask | None:
    """Resolve title/date/start/end from a create_task intent.

    Supports relative_minutes, untimed (start null), open-ended end.
    """
    if isinstance(intent, ControlCreateTask):
        data = intent.model_dump()
    elif isinstance(intent, dict):
        data = dict(intent)
    else:
        return None

    title_raw = data.get("title") or ""
    if not isinstance(title_raw, str):
        title_raw = str(title_raw)
    title = title_raw.strip()[:200]
    if not title:
        return None

    auto_rollover = bool(data.get("auto_rollover") or False)
    today = default_date or local_now_dt.date()

    relative = data.get("relative_minutes")
    start: time | None = None
    end: time | None = None
    task_date: date = today

    if relative is not None:
        try:
            rel_i = int(relative)
        except (TypeError, ValueError):
            return None
        if rel_i <= 0:
            return None
        task_date, start = resolve_relative_start(local_now_dt, rel_i)
    else:
        raw_date = data.get("date")
        if isinstance(raw_date, str) and raw_date.strip():
            try:
                task_date = date.fromisoformat(raw_date.strip())
            except ValueError:
                task_date = today
        elif isinstance(raw_date, date) and not isinstance(raw_date, datetime):
            task_date = raw_date

        raw_start = data.get("start_time")
        if raw_start is not None and str(raw_start).strip():
            start_s, _ = snap_hh_mm(str(raw_start).strip())
            if start_s is None:
                return None
            h, m = map(int, start_s.split(":"))
            start = time(h, m)

        raw_end = data.get("end_time")
        if raw_end is not None and str(raw_end).strip():
            end_s, _ = snap_hh_mm(str(raw_end).strip())
            if end_s is None:
                return None
            h, m = map(int, end_s.split(":"))
            end = time(h, m)
            if start is not None and end <= start:
                # drop invalid end rather than fail whole create
                end = None

    return ResolvedControlTask(
        title=title,
        task_date=task_date,
        start_time=start,
        end_time=end,
        auto_rollover=auto_rollover,
    )


async def apply_control_create_task(
    session: AsyncSession,
    user: User,
    intent: ControlCreateTask | dict[str, Any],
    *,
    force: bool = False,
    local_now_dt: datetime | None = None,
) -> ControlCreateResult:
    """Create a Task from a control create_task intent."""
    try:
        if local_now_dt is None:
            local_now_dt = local_now(user.timezone or "UTC")
    except Exception:
        local_now_dt = datetime.now()

    resolved = resolve_create_task_fields(intent, local_now_dt=local_now_dt)
    if resolved is None:
        return ControlCreateResult(
            status="error",
            error="invalid_create",
        )

    try:
        if resolved.start_time is not None and not force:
            free = await is_time_slot_free(
                session,
                user.id,
                resolved.task_date,
                resolved.start_time,
                resolved.end_time,
            )
            if not free:
                return ControlCreateResult(
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
            auto_rollover=resolved.auto_rollover,
        )
        session.add(task)
        await session.flush()
        return ControlCreateResult(status="ok", task=task, resolved=resolved)
    except Exception as exc:
        logger.error(
            "apply_control_create_task failed user=%s: %s",
            getattr(user, "id", None),
            exc,
            exc_info=True,
        )
        raise


async def load_tasks_for_match(
    session: AsyncSession,
    user_id: int,
    *,
    task_date: date,
    include_placeholders: bool = False,
) -> list[Task]:
    """Load tasks for a user on a date for matching."""
    stmt = select(Task).where(Task.user_id == user_id, Task.date == task_date)
    if not include_placeholders:
        stmt = stmt.where(Task.is_placeholder.is_(False))
    stmt = stmt.order_by(Task.start_time.nulls_last(), Task.id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def match_control_task(
    session: AsyncSession,
    user: User,
    intent: ControlDeleteTask | ControlCompleteTask | dict[str, Any],
    *,
    local_now_dt: datetime | None = None,
) -> ControlMatchResult:
    """Resolve which task(s) a delete/complete intent refers to."""
    try:
        if local_now_dt is None:
            local_now_dt = local_now(user.timezone or "UTC")
    except Exception:
        local_now_dt = datetime.now()

    if hasattr(intent, "model_dump"):
        data = intent.model_dump()  # type: ignore[union-attr]
    else:
        data = dict(intent)

    today = local_now_dt.date()
    task_date = today
    raw_date = data.get("date")
    if isinstance(raw_date, str) and raw_date.strip():
        try:
            task_date = date.fromisoformat(raw_date.strip())
        except ValueError:
            task_date = today

    task_id = data.get("task_id")
    query = data.get("query")

    try:
        if task_id is not None:
            try:
                tid = int(task_id)
            except (TypeError, ValueError):
                return ControlMatchResult(status="error", error="bad_task_id")
            result = await session.execute(
                select(Task).where(
                    Task.id == tid,
                    Task.user_id == user.id,
                    Task.is_placeholder.is_(False),
                )
            )
            task = result.scalar_one_or_none()
            if task is None:
                return ControlMatchResult(status="not_found")
            return ControlMatchResult(status="found", tasks=[task])

        candidates = await load_tasks_for_match(session, user.id, task_date=task_date)
        matched = filter_tasks_by_query(candidates, query)
        if not matched:
            # if query empty, treat as not_found (don't dump whole day)
            return ControlMatchResult(status="not_found")
        if len(matched) == 1:
            return ControlMatchResult(status="found", tasks=matched)
        return ControlMatchResult(status="ambiguous", tasks=matched[:8])
    except Exception as exc:
        logger.error("match_control_task failed: %s", exc, exc_info=True)
        return ControlMatchResult(status="error", error=str(exc))


async def apply_control_delete_task(
    session: AsyncSession,
    user: User,
    task_id: int,
) -> ControlMutateResult:
    """Delete a task owned by *user*."""
    try:
        result = await session.execute(
            select(Task).where(
                Task.id == task_id,
                Task.user_id == user.id,
            )
        )
        task = result.scalar_one_or_none()
        if task is None:
            return ControlMutateResult(status="not_found")
        title = task.title
        await session.delete(task)
        await session.flush()
        # keep title on a detached-like stub for messaging
        stub = Task(
            user_id=user.id,
            title=title,
            date=task.date,
            start_time=task.start_time,
            end_time=task.end_time,
        )
        stub.id = task_id  # type: ignore[assignment]
        return ControlMutateResult(status="ok", task=stub)
    except Exception as exc:
        logger.error("apply_control_delete_task failed: %s", exc, exc_info=True)
        raise


async def apply_control_complete_task(
    session: AsyncSession,
    user: User,
    task_id: int,
) -> ControlMutateResult:
    """Mark a task completed."""
    try:
        result = await session.execute(
            select(Task).where(
                Task.id == task_id,
                Task.user_id == user.id,
            )
        )
        task = result.scalar_one_or_none()
        if task is None:
            return ControlMutateResult(status="not_found")
        task.is_completed = True
        await session.flush()
        return ControlMutateResult(status="ok", task=task)
    except Exception as exc:
        logger.error("apply_control_complete_task failed: %s", exc, exc_info=True)
        raise


def format_task_label(task: Task, lang: str = "ru") -> str:
    """Short label for choice buttons / confirm text."""
    title = (task.title or "").strip() or "—"
    if task.start_time is None:
        time_s = "—" if lang == "en" else "без времени"
    else:
        time_s = task.start_time.strftime("%H:%M")
        if task.end_time is not None:
            time_s = f"{time_s}–{task.end_time.strftime('%H:%M')}"
    return f"{time_s} · {title}"[:64]
