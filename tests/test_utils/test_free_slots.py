"""Tests for free-slot discovery used by check-in reschedule."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from src.utils.free_slots import (
    end_of_local_day_utc,
    find_free_slots,
    shift_end_time,
    task_duration_minutes,
)


class TestTaskDurationMinutes:
    def test_open_ended(self) -> None:
        assert task_duration_minutes(time(9, 0), None) is None

    def test_fixed_duration(self) -> None:
        assert task_duration_minutes(time(9, 0), time(10, 30)) == 90

    def test_invalid_zero_or_negative(self) -> None:
        assert task_duration_minutes(time(10, 0), time(10, 0)) is None
        assert task_duration_minutes(time(11, 0), time(10, 0)) is None


class TestFindFreeSlots:
    def test_empty_day_after_noon(self) -> None:
        slots = find_free_slots(
            occupied=[],
            duration_minutes=30,
            after=time(12, 0),
        )
        assert time(12, 15) in slots
        assert time(12, 0) not in slots  # not strictly after
        assert time(11, 45) not in slots
        assert time(23, 30) in slots  # 23:30 + 30 = 24:00 ok
        assert time(23, 45) not in slots  # would overflow

    def test_respects_occupied_block(self) -> None:
        occupied = [(time(14, 0), time(15, 0))]
        slots = find_free_slots(
            occupied=occupied,
            duration_minutes=30,
            after=time(13, 0),
        )
        assert time(13, 30) in slots
        assert time(14, 0) not in slots
        assert time(14, 30) not in slots
        assert time(15, 0) in slots

    def test_open_ended_candidate_conflicts_with_later_task(self) -> None:
        occupied = [(time(16, 0), time(17, 0))]
        slots = find_free_slots(
            occupied=occupied,
            duration_minutes=None,
            after=time(10, 0),
        )
        # Open-ended from 15:00 would overlap 16:00–17:00
        assert time(15, 0) not in slots
        # After the occupied block ends is fine
        assert time(17, 0) in slots

    def test_excludes_past_slots_only(self) -> None:
        slots = find_free_slots(
            occupied=[],
            duration_minutes=15,
            after=time(22, 0),
        )
        assert all(s > time(22, 0) for s in slots)
        assert time(22, 15) in slots

    def test_full_day_busy_returns_empty(self) -> None:
        occupied = [(time(0, 0), None)]  # open-ended from midnight
        slots = find_free_slots(
            occupied=occupied,
            duration_minutes=15,
            after=time(8, 0),
        )
        assert slots == []


class TestShiftEndTime:
    def test_preserves_duration(self) -> None:
        assert shift_end_time(time(9, 0), time(10, 0), time(14, 0)) == time(15, 0)

    def test_open_ended_stays_none(self) -> None:
        assert shift_end_time(time(9, 0), None, time(14, 0)) is None


class TestEndOfLocalDayUtc:
    def test_utc_plus_three(self) -> None:
        tz = timezone(timedelta(hours=3))
        local = datetime(2026, 7, 12, 16, 0, tzinfo=tz)
        eod = end_of_local_day_utc(local)
        assert eod.tzinfo == timezone.utc
        # 23:59:59.999999 +3 → 20:59:59.999999 UTC
        assert eod.date() == date(2026, 7, 12)
        assert eod.hour == 20
        assert eod.minute == 59
