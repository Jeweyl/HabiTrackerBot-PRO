"""Unit tests for the two-step 15-minute time picker helpers and keyboards."""

from __future__ import annotations

from datetime import time

from src.keyboards.inline import (
    get_minute_selection_keyboard,
    get_time_selection_keyboard,
)
from src.utils.time_picker import (
    available_hours,
    available_minutes,
    parse_time_callback,
    slot_allowed,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _callbacks(markup) -> set[str]:
    return {
        btn.callback_data
        for row in markup.inline_keyboard
        for btn in row
        if btn.callback_data
    }


def _labels(markup) -> set[str]:
    return {btn.text for row in markup.inline_keyboard for btn in row}


# ---------------------------------------------------------------------------
# parse_time_callback
# ---------------------------------------------------------------------------


class TestParseTimeCallback:
    def test_hour(self) -> None:
        assert parse_time_callback("time:hour:08") == ("hour", 8)
        assert parse_time_callback("time:hour:00") == ("hour", 0)
        assert parse_time_callback("time:hour:23") == ("hour", 23)

    def test_final_quarter_hours(self) -> None:
        assert parse_time_callback("time:08:00") == ("final", time(8, 0))
        assert parse_time_callback("time:08:15") == ("final", time(8, 15))
        assert parse_time_callback("time:08:30") == ("final", time(8, 30))
        assert parse_time_callback("time:08:45") == ("final", time(8, 45))
        assert parse_time_callback("time:09:00") == ("final", time(9, 0))

    def test_null(self) -> None:
        assert parse_time_callback("time:null") == ("null", None)

    def test_invalid(self) -> None:
        assert parse_time_callback("time:xx") == ("invalid", None)
        assert parse_time_callback("time:hour:99") == ("invalid", None)
        assert parse_time_callback("time:08:10") == ("invalid", None)
        assert parse_time_callback("time:08:60") == ("invalid", None)
        assert parse_time_callback("time:25:00") == ("invalid", None)
        assert parse_time_callback(None) == ("invalid", None)
        assert parse_time_callback("nav:back") == ("invalid", None)
        assert parse_time_callback("time:hour:") == ("invalid", None)


# ---------------------------------------------------------------------------
# available_hours / available_minutes / slot_allowed
# ---------------------------------------------------------------------------


class TestFilters:
    def test_slot_allowed_strictly_after(self) -> None:
        assert slot_allowed(time(8, 30), time(8, 15)) is True
        assert slot_allowed(time(8, 15), time(8, 15)) is False
        assert slot_allowed(time(8, 0), time(8, 15)) is False
        assert slot_allowed(time(8, 0), None) is True

    def test_available_hours_no_filter(self) -> None:
        assert available_hours() == list(range(24))

    def test_available_hours_min_time_0815(self) -> None:
        hours = available_hours(time(8, 15))
        assert 7 not in hours
        assert 8 in hours  # 08:30, 08:45 still free
        assert 9 in hours
        assert 0 not in hours

    def test_available_hours_min_time_0845(self) -> None:
        hours = available_hours(time(8, 45))
        assert 8 not in hours  # no minute > 08:45
        assert 9 in hours

    def test_available_hours_min_time_2345(self) -> None:
        assert available_hours(time(23, 45)) == []

    def test_available_minutes_min_time_0815(self) -> None:
        mins = available_minutes(8, time(8, 15))
        assert mins == [30, 45]

    def test_available_minutes_full_hour(self) -> None:
        assert available_minutes(8) == [0, 15, 30, 45]

    def test_available_minutes_invalid_hour(self) -> None:
        assert available_minutes(99) == []


# ---------------------------------------------------------------------------
# Hour keyboard
# ---------------------------------------------------------------------------


class TestHourKeyboard:
    def test_all_hours_present(self) -> None:
        kb = get_time_selection_keyboard()
        cbs = _callbacks(kb)
        for h in range(24):
            assert f"time:hour:{h:02d}" in cbs
        assert "nav:back" in cbs
        assert "nav:cancel" in cbs
        assert "time:null" not in cbs

    def test_no_final_time_callbacks(self) -> None:
        """Hour step must not emit final time:HH:MM callbacks."""
        cbs = _callbacks(get_time_selection_keyboard())
        assert not any(
            cb.startswith("time:") and not cb.startswith("time:hour:") and cb != "time:null"
            for cb in cbs
        )

    def test_min_time_0815_hides_early_hours(self) -> None:
        kb = get_time_selection_keyboard(min_time=time(8, 15))
        cbs = _callbacks(kb)
        assert "time:hour:07" not in cbs
        assert "time:hour:08" in cbs
        assert "time:hour:09" in cbs
        assert "time:hour:00" not in cbs

    def test_min_time_0845_hides_hour_08(self) -> None:
        kb = get_time_selection_keyboard(min_time=time(8, 45))
        cbs = _callbacks(kb)
        assert "time:hour:08" not in cbs
        assert "time:hour:09" in cbs

    def test_null_option(self) -> None:
        kb = get_time_selection_keyboard(show_null_option=True)
        assert "time:null" in _callbacks(kb)

    def test_empty_grid_placeholder(self) -> None:
        kb = get_time_selection_keyboard(min_time=time(23, 45), show_null_option=True)
        cbs = _callbacks(kb)
        labels = _labels(kb)
        assert "Нет доступных вариантов" in labels
        assert "time:null" in cbs
        assert "nav:back" in cbs


# ---------------------------------------------------------------------------
# Minute keyboard
# ---------------------------------------------------------------------------


class TestMinuteKeyboard:
    def test_quarter_hours_for_08(self) -> None:
        kb = get_minute_selection_keyboard(8)
        cbs = _callbacks(kb)
        assert "time:08:00" in cbs
        assert "time:08:15" in cbs
        assert "time:08:30" in cbs
        assert "time:08:45" in cbs
        assert "nav:back" in cbs
        assert "nav:cancel" in cbs

    def test_min_time_0815_filters_minutes(self) -> None:
        kb = get_minute_selection_keyboard(8, min_time=time(8, 15))
        cbs = _callbacks(kb)
        assert "time:08:00" not in cbs
        assert "time:08:15" not in cbs
        assert "time:08:30" in cbs
        assert "time:08:45" in cbs

    def test_labels_are_minutes_only(self) -> None:
        kb = get_minute_selection_keyboard(9)
        labels = _labels(kb)
        assert "00" in labels
        assert "15" in labels
        assert "30" in labels
        assert "45" in labels

    def test_null_option_on_minutes(self) -> None:
        kb = get_minute_selection_keyboard(10, show_null_option=True)
        assert "time:null" in _callbacks(kb)

    def test_no_hour_callbacks_on_minute_kb(self) -> None:
        cbs = _callbacks(get_minute_selection_keyboard(8))
        assert not any(cb.startswith("time:hour:") for cb in cbs)
