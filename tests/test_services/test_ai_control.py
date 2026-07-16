"""Unit tests for free-form AI control schema, resolve, and matching."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from types import SimpleNamespace

import pytest

from src.services.ai_control_apply import (
    filter_tasks_by_query,
    resolve_create_task_fields,
    score_task_match,
)
from src.services.ai_control_service import (
    build_control_prompt,
    resolve_relative_start,
)
from src.services.ai_schema import (
    AskQuestions,
    ControlCompleteTask,
    ControlCreateTask,
    ControlDeleteTask,
    ControlListTasks,
    ControlMessage,
    ControlOpenMenu,
    parse_control_response,
)



# ---------------------------------------------------------------------------
# parse_control_response
# ---------------------------------------------------------------------------


def test_parse_create_task_absolute() -> None:
    raw = {
        "type": "create_task",
        "title": "Прыжки на батуте",
        "date": "2026-07-16",
        "start_time": "15:00",
        "end_time": None,
        "relative_minutes": None,
    }
    m = parse_control_response(raw)
    assert isinstance(m, ControlCreateTask)
    assert m.title == "Прыжки на батуте"
    assert m.start_time == "15:00"
    assert m.end_time is None


def test_parse_create_task_relative() -> None:
    m = parse_control_response(
        {
            "type": "create_task",
            "title": "Покурить",
            "relative_minutes": 20,
        }
    )
    assert isinstance(m, ControlCreateTask)
    assert m.relative_minutes == 20
    assert m.start_time is None


def test_parse_create_task_untimed() -> None:
    m = parse_control_response(
        {"type": "create_task", "title": "Купить молоко", "start_time": None}
    )
    assert isinstance(m, ControlCreateTask)
    assert m.start_time is None


def test_parse_delete_and_complete() -> None:
    d = parse_control_response(
        {"type": "delete_task", "query": "прыжки", "date": "2026-07-16"}
    )
    assert isinstance(d, ControlDeleteTask)
    assert d.query == "прыжки"

    c = parse_control_response(
        {"type": "complete_task", "task_id": 42}
    )
    assert isinstance(c, ControlCompleteTask)
    assert c.task_id == 42


def test_parse_open_menu_and_message() -> None:
    o = parse_control_response(
        {"type": "open_menu", "target": "new_habit_choice"}
    )
    assert isinstance(o, ControlOpenMenu)
    assert o.target == "new_habit_choice"

    o2 = parse_control_response(
        {"type": "open_menu", "target": "tomorrow"}
    )
    assert isinstance(o2, ControlOpenMenu)
    assert o2.target == "tomorrow"

    msg = parse_control_response(
        {"type": "message", "text": "Не понял запрос"}
    )
    assert isinstance(msg, ControlMessage)


def test_parse_list_tasks() -> None:
    m = parse_control_response({"type": "list_tasks", "date": None})
    assert isinstance(m, ControlListTasks)
    assert m.date is None

    m2 = parse_control_response(
        {"type": "list_tasks", "date": "2026-07-17"}
    )
    assert isinstance(m2, ControlListTasks)
    assert m2.date == "2026-07-17"



def test_parse_ask_questions() -> None:
    m = parse_control_response(
        {
            "type": "ask_questions",
            "questions": [
                {
                    "text": "Какую задачу удалить?",
                    "kind": "choice",
                    "options": ["A", "B"],
                }
            ],
        }
    )
    assert isinstance(m, AskQuestions)


def test_parse_rejects_unknown() -> None:
    assert parse_control_response({"type": "explode"}) is None
    assert parse_control_response(None) is None
    assert parse_control_response("not json") is None


def test_parse_rejects_bad_relative() -> None:
    assert (
        parse_control_response(
            {"type": "create_task", "title": "x", "relative_minutes": -5}
        )
        is None
    )


# ---------------------------------------------------------------------------
# relative + resolve create
# ---------------------------------------------------------------------------


def test_resolve_relative_start_snaps() -> None:
    # 10:07 + 20m = 10:27 → snap to 10:30
    now = datetime(2026, 7, 16, 10, 7, tzinfo=timezone.utc)
    d, t = resolve_relative_start(now, 20)
    assert d == date(2026, 7, 16)
    assert t == time(10, 30)


def test_resolve_create_relative_fields() -> None:
    now = datetime(2026, 7, 16, 14, 0, tzinfo=timezone.utc)
    intent = ControlCreateTask(title="Покурить", relative_minutes=20)
    resolved = resolve_create_task_fields(intent, local_now_dt=now)
    assert resolved is not None
    assert resolved.title == "Покурить"
    assert resolved.start_time == time(14, 15) or resolved.start_time == time(14, 30)
    # 14:00 + 20 = 14:20 → snap 14:15 or 14:30 depending on rem policy (rem 5 → down 14:15)
    assert resolved.start_time == time(14, 15)
    assert resolved.end_time is None


def test_resolve_create_absolute_open_ended() -> None:
    now = datetime(2026, 7, 16, 9, 0)
    intent = ControlCreateTask(
        title="Прыжки на батуте",
        date="2026-07-16",
        start_time="15:00",
        end_time=None,
    )
    resolved = resolve_create_task_fields(intent, local_now_dt=now)
    assert resolved is not None
    assert resolved.task_date == date(2026, 7, 16)
    assert resolved.start_time == time(15, 0)
    assert resolved.end_time is None


def test_resolve_create_untimed() -> None:
    now = datetime(2026, 7, 16, 9, 0)
    intent = ControlCreateTask(title="Купить молоко")
    resolved = resolve_create_task_fields(intent, local_now_dt=now)
    assert resolved is not None
    assert resolved.start_time is None
    assert resolved.task_date == date(2026, 7, 16)


# ---------------------------------------------------------------------------
# matcher
# ---------------------------------------------------------------------------


def _task(tid: int, title: str) -> SimpleNamespace:
    return SimpleNamespace(id=tid, title=title)


def test_score_and_filter() -> None:
    tasks = [
        _task(1, "Прыжки на батуте"),
        _task(2, "Созвон с командой"),
        _task(3, "Прыжки"),
    ]
    assert score_task_match("Прыжки на батуте", "прыжки") >= 70
    matched = filter_tasks_by_query(tasks, "прыжки")  # type: ignore[arg-type]
    assert [t.id for t in matched] == [3, 1] or [t.id for t in matched] == [1, 3]
    assert all("прыж" in t.title.lower() for t in matched)


def test_filter_no_match() -> None:
    tasks = [_task(1, "Созвон")]
    assert filter_tasks_by_query(tasks, "батут") == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# prompt
# ---------------------------------------------------------------------------


def test_prompt_contains_local_clock_and_user_text() -> None:
    now = datetime(2026, 7, 16, 15, 30)
    prompt = build_control_prompt(
        user_text="Удали задачу прыжки на сегодня",
        language="ru",
        timezone="+3",
        local_now_dt=now,
        context_block="tasks_today:\n  id=1 [open] 15:00 Прыжки",
    )
    assert "2026-07-16" in prompt
    assert "15:30" in prompt
    assert "Удали задачу прыжки" in prompt
    assert "create_task" in prompt
    assert "delete_task" in prompt
    assert "list_tasks" in prompt
    assert "NEVER ask what day/time" in prompt


