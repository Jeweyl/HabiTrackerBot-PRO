"""Unit tests for AI JSON schema contract (src/services/ai_schema.py)."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from src.services.ai_schema import (
    AskQuestions,
    ClarifyingQuestion,
    ProposePlan,
    normalize_question,
    parse_ai_response,
)



# ---------------------------------------------------------------------------
# Fixtures / sample payloads
# ---------------------------------------------------------------------------


def _valid_propose_plan(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "type": "propose_plan",
        "title": "Morning run",
        "start_time": "08:00",
        "end_time": "08:30",
        "frequency": "daily",
        "duration_minutes": 30,
        "comment": "Start slowly.",
        "schedule_ops": None,
    }
    base.update(overrides)
    return base


def _valid_ask_questions(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "type": "ask_questions",
        "questions": ["How many days per week?", "Morning or evening?"],
        "context": "Need schedule details",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Table-driven parse_ai_response cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected_type,check",
    [
        # 1. Valid propose_plan dict
        (
            _valid_propose_plan(),
            ProposePlan,
            lambda m: (
                m.title == "Morning run"
                and m.start_time == "08:00"
                and m.end_time == "08:30"
                and m.duration_minutes == 30
                and m.frequency == "daily"
            ),
        ),
        # 2. Valid propose_plan JSON string
        (
            json.dumps(_valid_propose_plan()),
            ProposePlan,
            lambda m: m.title == "Morning run",
        ),
        # 3. Valid ask_questions
        (
            _valid_ask_questions(),
            AskQuestions,
            lambda m: len(m.questions) == 2 and m.context == "Need schedule details",
        ),
        # 4. Optional end_time / duration omitted
        (
            _valid_propose_plan(end_time=None, duration_minutes=None),
            ProposePlan,
            lambda m: m.end_time is None and m.duration_minutes is None,
        ),
        # 5. Extra unknown fields ignored
        (
            _valid_propose_plan(refined_habit="legacy", foo="bar"),
            ProposePlan,
            lambda m: m.title == "Morning run",
        ),
        # 6. schedule_ops with valid set_schedule
        (
            _valid_propose_plan(
                schedule_ops=[
                    {
                        "op": "set_schedule",
                        "start_time": "09:00",
                        "end_time": "09:15",
                        "frequency": "weekdays",
                    }
                ]
            ),
            ProposePlan,
            lambda m: m.schedule_ops is not None and len(m.schedule_ops) == 1,
        ),
    ],
    ids=[
        "valid_propose_dict",
        "valid_propose_json_str",
        "valid_ask_questions",
        "optional_end_duration",
        "extra_fields_ignored",
        "valid_schedule_ops",
    ],
)
def test_parse_ai_response_valid(
    raw: Any,
    expected_type: type,
    check: Any,
) -> None:
    """Valid JSON/dict payloads must parse into the expected model."""
    result = parse_ai_response(raw)
    assert isinstance(result, expected_type)
    assert check(result)


@pytest.mark.parametrize(
    "raw,reason",
    [
        # Non-JSON / empty / null
        (None, "null"),
        ("", "empty"),
        ("   ", "whitespace"),
        ("This is just plain text, not JSON.", "non_json"),
        ("[]", "json_array"),
        ("42", "json_number"),
        ('"string"', "json_string_scalar"),
        # Missing / unknown type
        ({"title": "x", "start_time": "08:00"}, "missing_type"),
        ({"type": "unknown", "title": "x"}, "unknown_type"),
        # Invalid times
        (_valid_propose_plan(start_time="08:07"), "start_not_15min"),
        (_valid_propose_plan(end_time="08:07", duration_minutes=None), "end_not_15min"),
        (_valid_propose_plan(start_time="8:00"), "unpadded_hour"),
        (_valid_propose_plan(start_time="25:00"), "invalid_hour"),
        # Duration integrity: 15 but 08:00–09:00 → reject
        (
            _valid_propose_plan(
                start_time="08:00",
                end_time="09:00",
                duration_minutes=15,
            ),
            "duration_mismatch",
        ),
        # end before start
        (
            _valid_propose_plan(
                start_time="10:00",
                end_time="09:00",
                duration_minutes=None,
            ),
            "end_before_start",
        ),
        # overnight (B1 reject)
        (
            _valid_propose_plan(
                start_time="22:00",
                end_time="01:00",
                duration_minutes=None,
            ),
            "overnight",
        ),
        # duration not multiple of 15
        (
            _valid_propose_plan(
                end_time=None,
                duration_minutes=20,
            ),
            "duration_not_multiple_15",
        ),
        # non-positive duration
        (
            _valid_propose_plan(end_time=None, duration_minutes=0),
            "duration_zero",
        ),
        (
            _valid_propose_plan(end_time=None, duration_minutes=-15),
            "duration_negative",
        ),
        # empty title
        (_valid_propose_plan(title=""), "empty_title"),
        (_valid_propose_plan(title="   "), "whitespace_title"),
        # ask_questions with empty questions
        (_valid_ask_questions(questions=[]), "empty_questions"),
        (_valid_ask_questions(questions=["", "  "]), "blank_questions"),
        # bad schedule_ops
        (
            _valid_propose_plan(
                schedule_ops=[{"op": "delete_all", "start_time": "08:00"}]
            ),
            "bad_schedule_op",
        ),
        (
            _valid_propose_plan(
                schedule_ops=[
                    {"op": "set_schedule", "start_time": "08:07"}
                ]
            ),
            "schedule_op_bad_time",
        ),
    ],
    ids=[
        "null",
        "empty",
        "whitespace",
        "non_json",
        "json_array",
        "json_number",
        "json_string_scalar",
        "missing_type",
        "unknown_type",
        "start_not_15min",
        "end_not_15min",
        "unpadded_hour",
        "invalid_hour",
        "duration_mismatch",
        "end_before_start",
        "overnight",
        "duration_not_multiple_15",
        "duration_zero",
        "duration_negative",
        "empty_title",
        "whitespace_title",
        "empty_questions",
        "blank_questions",
        "bad_schedule_op",
        "schedule_op_bad_time",
    ],
)
def test_parse_ai_response_rejects(raw: Any, reason: str) -> None:
    """Invalid / untrusted payloads must return None and never raise."""
    result = parse_ai_response(raw)
    assert result is None, f"expected None for case {reason!r}, got {result!r}"


def test_duration_mismatch_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Duration mismatch policy: reject + log (no auto-fix)."""
    raw = _valid_propose_plan(
        start_time="08:00",
        end_time="09:00",
        duration_minutes=15,
    )
    with caplog.at_level(logging.WARNING):
        result = parse_ai_response(raw)

    assert result is None
    assert any(
        "duration" in record.message.lower() or "reject" in record.message.lower()
        for record in caplog.records
    )


def test_invalid_time_08_07_rejected() -> None:
    """Explicit acceptance criterion: 08:07 must be rejected."""
    assert parse_ai_response(_valid_propose_plan(start_time="08:07")) is None


def test_parse_never_raises_on_garbage() -> None:
    """Edge-cases must not raise for any garbage input."""
    garbage = [
        None,
        "",
        "{",
        object(),
        3.14,
        ["propose_plan"],
        {"type": "propose_plan"},  # missing required fields
    ]
    for item in garbage:
        assert parse_ai_response(item) is None  # type: ignore[arg-type]


def test_markdown_fenced_json_accepted() -> None:
    """Chatty models sometimes wrap JSON in ``` fences — accept if body valid."""
    body = json.dumps(_valid_propose_plan())
    fenced = f"```json\n{body}\n```"
    result = parse_ai_response(fenced)
    assert isinstance(result, ProposePlan)
    assert result.title == "Morning run"


def test_propose_plan_all_15_min_slots() -> None:
    """All four quarter-hour slots are accepted for start_time."""
    for minute in (0, 15, 30, 45):
        start = f"08:{minute:02d}"
        # end 15 minutes later when possible
        end_minute = minute + 15
        if end_minute >= 60:
            end = "09:00"
            duration = 60 - minute
        else:
            end = f"08:{end_minute:02d}"
            duration = 15
        result = parse_ai_response(
            _valid_propose_plan(
                start_time=start,
                end_time=end,
                duration_minutes=duration,
            )
        )
        assert isinstance(result, ProposePlan), f"failed for {start}"
        assert result.start_time == start


def test_ask_questions_string_items_normalized() -> None:
    """Plain string questions remain valid (B1 compat → ClarifyingQuestion)."""
    result = parse_ai_response(_valid_ask_questions())
    assert isinstance(result, AskQuestions)
    assert len(result.questions) == 2
    assert all(isinstance(q, ClarifyingQuestion) for q in result.questions)
    assert result.questions[0].kind == "text"


def test_ask_questions_structured_choice_and_time() -> None:
    """Structured choice/time questions parse correctly."""
    raw = {
        "type": "ask_questions",
        "questions": [
            {
                "text": "When?",
                "kind": "choice",
                "options": ["Morning", "Evening"],
            },
            {"text": "Start time?", "kind": "time"},
        ],
    }
    result = parse_ai_response(raw)
    assert isinstance(result, AskQuestions)
    assert result.questions[0].kind == "choice"
    assert result.questions[0].options == ["Morning", "Evening"]
    assert result.questions[1].kind == "time"


def test_choice_without_options_becomes_text() -> None:
    """choice without options is downgraded to text."""
    q = normalize_question({"text": "Anything?", "kind": "choice", "options": []})
    assert q is not None
    assert q.kind == "text"


def test_normalize_question_garbage_returns_none() -> None:
    """normalize_question never raises on garbage."""
    assert normalize_question(None) is None
    assert normalize_question("") is None
    assert normalize_question(42) is None
    assert normalize_question({"kind": "choice"}) is None  # missing text


