"""Unit tests for AI plan time normalization (B5)."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from src.services.ai_normalize import (
    NormalizeResult,
    normalize_plan_times,
    snap_hh_mm,
    snap_time,
    snap_total_minutes,
)
from src.services.ai_schema import ProposePlan, ProposeTaskPlan


# ---------------------------------------------------------------------------
# snap helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "total,expected",
    [
        (0, 0),
        (7, 0),
        (8, 15),
        (15, 15),
        (8 * 60 + 7, 8 * 60),  # 08:07 → 08:00
        (8 * 60 + 8, 8 * 60 + 15),  # 08:08 → 08:15
        (8 * 60 + 22, 8 * 60 + 15),  # 08:22 → 08:15
        (8 * 60 + 23, 8 * 60 + 30),  # 08:23 → 08:30
        (23 * 60 + 52, 23 * 60 + 45),  # clamp near end of day
        (-5, 0),
    ],
)
def test_snap_total_minutes(total: int, expected: int) -> None:
    assert snap_total_minutes(total) == expected


def test_snap_hh_mm_08_07() -> None:
    snapped, corrected = snap_hh_mm("08:07")
    assert snapped == "08:00"
    assert corrected is True


def test_snap_hh_mm_08_08() -> None:
    snapped, corrected = snap_hh_mm("08:08")
    assert snapped == "08:15"
    assert corrected is True


def test_snap_hh_mm_clean() -> None:
    snapped, corrected = snap_hh_mm("08:00")
    assert snapped == "08:00"
    assert corrected is False


def test_snap_hh_mm_invalid() -> None:
    assert snap_hh_mm(None) == (None, False)
    assert snap_hh_mm("") == (None, False)
    assert snap_hh_mm("8:00") == (None, False)
    assert snap_hh_mm("25:00") == (None, False)
    assert snap_hh_mm(123) == (None, False)


def test_snap_time_object() -> None:
    from datetime import time

    assert snap_time(time(8, 7)) == time(8, 0)
    assert snap_time(time(8, 8)) == time(8, 15)


# ---------------------------------------------------------------------------
# normalize_plan_times — acceptance matrix
# ---------------------------------------------------------------------------


def test_duration_overrides_mismatched_end() -> None:
    """AI returns 30 min + 08:00–08:10 → corrected to 08:00–08:30 + warning."""
    plan = {
        "type": "propose_plan",
        "title": "Run",
        "start_time": "08:00",
        "end_time": "08:10",
        "duration_minutes": 30,
        "frequency": "daily",
    }
    result = normalize_plan_times(plan, kind="habit")
    assert result.ok is True
    assert result.plan is not None
    assert result.plan["start_time"] == "08:00"
    assert result.plan["end_time"] == "08:30"
    assert result.plan["duration_minutes"] == 30
    assert result.warnings
    assert "duration_overrides_end" in result.corrections


def test_duration_overrides_logs(caplog: pytest.LogCaptureFixture) -> None:
    plan = {
        "title": "Run",
        "start_time": "08:00",
        "end_time": "08:10",
        "duration_minutes": 30,
    }
    with caplog.at_level(logging.WARNING):
        result = normalize_plan_times(plan, kind="habit")
    assert result.ok
    assert any("corrected" in r.message.lower() for r in caplog.records)


def test_grid_snap_start_08_07() -> None:
    """Grid snap 08:07 → 08:00 (nearest)."""
    plan = {
        "title": "X",
        "start_time": "08:07",
        "duration_minutes": 30,
    }
    result = normalize_plan_times(plan, kind="habit")
    assert result.ok
    assert result.plan is not None
    assert result.plan["start_time"] == "08:00"
    assert result.plan["end_time"] == "08:30"
    assert "snap_start" in result.corrections
    assert result.warnings


def test_grid_snap_start_08_08() -> None:
    """Grid snap 08:08 → 08:15 (nearest up)."""
    plan = {
        "title": "X",
        "start_time": "08:08",
        "duration_minutes": 15,
    }
    result = normalize_plan_times(plan, kind="habit")
    assert result.ok
    assert result.plan is not None
    assert result.plan["start_time"] == "08:15"
    assert result.plan["end_time"] == "08:30"


def test_end_only_computes_duration() -> None:
    plan = {
        "title": "X",
        "start_time": "08:00",
        "end_time": "08:45",
        "duration_minutes": None,
    }
    result = normalize_plan_times(plan, kind="habit")
    assert result.ok
    assert result.plan is not None
    assert result.plan["duration_minutes"] == 45
    assert result.plan["end_time"] == "08:45"


def test_duration_only_derives_end() -> None:
    plan = {
        "title": "X",
        "start_time": "08:00",
        "end_time": None,
        "duration_minutes": 15,
    }
    result = normalize_plan_times(plan, kind="habit")
    assert result.ok
    assert result.plan is not None
    assert result.plan["end_time"] == "08:15"
    assert result.plan["duration_minutes"] == 15


def test_reject_duration_below_15() -> None:
    """Do not silently stretch 10 → 15."""
    plan = {
        "title": "X",
        "start_time": "08:00",
        "end_time": "08:10",
        "duration_minutes": 10,
    }
    result = normalize_plan_times(plan, kind="habit")
    assert result.ok is False
    assert result.error is not None
    assert "reject_duration" in result.corrections


def test_reject_duration_not_multiple_of_15() -> None:
    plan = {
        "title": "X",
        "start_time": "08:00",
        "duration_minutes": 20,
    }
    result = normalize_plan_times(plan, kind="habit")
    assert result.ok is False
    assert "reject_duration" in result.corrections


def test_reject_missing_start() -> None:
    result = normalize_plan_times({"title": "X", "duration_minutes": 15})
    assert result.ok is False


def test_no_crash_none_empty() -> None:
    """None / empty / garbage → not ok, never raise."""
    for raw in (None, {}, {"title": ""}, "oops", 42, []):
        result = normalize_plan_times(raw)  # type: ignore[arg-type]
        assert isinstance(result, NormalizeResult)
        assert result.ok is False


def test_habit_missing_end_and_duration_rejected() -> None:
    plan = {"title": "X", "start_time": "10:00"}
    result = normalize_plan_times(plan, kind="habit")
    assert result.ok is False


def test_task_open_ended_allowed() -> None:
    plan = {
        "type": "propose_task",
        "title": "Open",
        "start_time": "11:00",
        "end_time": None,
        "duration_minutes": None,
    }
    result = normalize_plan_times(plan, kind="task")
    assert result.ok is True
    assert result.plan is not None
    assert result.plan["start_time"] == "11:00"
    assert result.plan["end_time"] is None
    assert result.plan["duration_minutes"] is None


def test_midnight_overflow_rejected() -> None:
    plan = {
        "title": "Late",
        "start_time": "23:30",
        "duration_minutes": 60,
    }
    result = normalize_plan_times(plan, kind="habit")
    assert result.ok is False


def test_already_clean_no_warnings() -> None:
    plan = {
        "title": "Clean",
        "start_time": "08:00",
        "end_time": "08:30",
        "duration_minutes": 30,
    }
    result = normalize_plan_times(plan, kind="habit")
    assert result.ok
    assert result.plan is not None
    assert result.plan["start_time"] == "08:00"
    assert result.plan["end_time"] == "08:30"
    assert result.plan["duration_minutes"] == 30
    assert result.warnings == []


def test_snap_end_then_duration_wins() -> None:
    """Off-grid end snapped, then duration still overrides."""
    plan = {
        "title": "X",
        "start_time": "09:00",
        "end_time": "09:07",
        "duration_minutes": 45,
    }
    result = normalize_plan_times(plan, kind="habit")
    assert result.ok
    assert result.plan is not None
    assert result.plan["end_time"] == "09:45"
    assert result.plan["duration_minutes"] == 45


def test_pydantic_propose_plan_input() -> None:
    """Accept ProposePlan model; off-grid times need schema to allow them."""
    # After B5 schema relax, off-grid may parse; use clean model here
    plan = ProposePlan(
        type="propose_plan",
        title="Run",
        start_time="08:00",
        end_time="08:30",
        duration_minutes=30,
    )
    result = normalize_plan_times(plan, kind="habit")
    assert result.ok
    assert result.plan is not None
    assert result.plan["duration_minutes"] == 30


def test_pydantic_propose_task_input() -> None:
    plan = ProposeTaskPlan(
        type="propose_task",
        title="Call",
        date="2026-07-12",
        start_time="10:00",
        end_time="10:30",
        duration_minutes=30,
    )
    result = normalize_plan_times(plan, kind="task")
    assert result.ok
    assert result.plan is not None
    assert result.plan["end_time"] == "10:30"


def test_invalid_range_end_before_start() -> None:
    plan = {
        "title": "X",
        "start_time": "10:00",
        "end_time": "09:00",
        "duration_minutes": None,
    }
    result = normalize_plan_times(plan, kind="habit")
    assert result.ok is False


def test_preserves_other_fields() -> None:
    plan = {
        "type": "propose_plan",
        "title": "Keep me",
        "start_time": "07:00",
        "end_time": "07:15",
        "duration_minutes": 15,
        "frequency": "weekdays",
        "comment": "hi",
        "schedule_ops": None,
    }
    result = normalize_plan_times(plan, kind="habit")
    assert result.ok
    assert result.plan is not None
    assert result.plan["title"] == "Keep me"
    assert result.plan["frequency"] == "weekdays"
    assert result.plan["comment"] == "hi"


@pytest.mark.parametrize(
    "start,end,duration,exp_start,exp_end,exp_dur,ok",
    [
        # clean
        ("08:00", "08:30", 30, "08:00", "08:30", 30, True),
        # duration wins over short end
        ("08:00", "08:10", 30, "08:00", "08:30", 30, True),
        # snap start down
        ("08:07", None, 30, "08:00", "08:30", 30, True),
        # snap start up
        ("08:08", None, 15, "08:15", "08:30", 15, True),
        # end only
        ("06:00", "07:00", None, "06:00", "07:00", 60, True),
        # bad duration
        ("08:00", "08:30", 10, None, None, None, False),
        ("08:00", None, 20, None, None, None, False),
        # missing start
        (None, "08:30", 30, None, None, None, False),
    ],
)
def test_normalize_matrix(
    start: str | None,
    end: str | None,
    duration: int | None,
    exp_start: str | None,
    exp_end: str | None,
    exp_dur: int | None,
    ok: bool,
) -> None:
    plan: dict[str, Any] = {"title": "M"}
    if start is not None:
        plan["start_time"] = start
    if end is not None:
        plan["end_time"] = end
    plan["duration_minutes"] = duration
    result = normalize_plan_times(plan, kind="habit")
    assert result.ok is ok
    if ok:
        assert result.plan is not None
        assert result.plan["start_time"] == exp_start
        assert result.plan["end_time"] == exp_end
        assert result.plan["duration_minutes"] == exp_dur
