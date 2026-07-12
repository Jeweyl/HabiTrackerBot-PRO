"""Strict Pydantic contract for AI assistant JSON responses.

B1 scope: parse + validate only. No DB writes, no handler/UI changes.
Invalid or untrusted AI output must never raise to callers — return ``None``.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import time
from typing import Annotated, Any, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from src.utils.time_picker import MINUTES_15

logger = logging.getLogger(__name__)

_HH_MM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
"""Strict ``HH:MM`` pattern (zero-padded hour and minute)."""

FrequencyLiteral = Literal["daily", "weekdays", "weekends"]
"""Allowed habit frequency values."""


def _parse_hh_mm(value: str) -> time:
    """Parse a zero-padded ``HH:MM`` string into :class:`datetime.time`.

    Args:
        value: Time string expected as ``HH:MM``.

    Returns:
        Parsed ``time`` instance.

    Raises:
        ValueError: If the format is invalid or minutes are not on the
            15-minute grid.
    """
    if not isinstance(value, str):
        raise ValueError("time must be a string in HH:MM format")
    match = _HH_MM_RE.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"invalid time format (expected HH:MM): {value!r}")
    hour = int(match.group(1))
    minute = int(match.group(2))
    if minute not in MINUTES_15:
        raise ValueError(
            f"minutes must be one of :00/:15/:30/:45, got {value!r}"
        )
    return time(hour, minute)


def _minutes_between(start: time, end: time) -> int:
    """Return same-day duration in minutes from *start* to *end*.

    Overnight ranges (end <= start) are not supported in B1.

    Args:
        start: Interval start.
        end: Interval end (must be strictly after *start*).

    Returns:
        Positive duration in minutes.

    Raises:
        ValueError: If *end* is not strictly after *start*.
    """
    start_m = start.hour * 60 + start.minute
    end_m = end.hour * 60 + end.minute
    if end_m <= start_m:
        raise ValueError(
            f"end_time must be after start_time on the same day "
            f"(got {start.strftime('%H:%M')}–{end.strftime('%H:%M')})"
        )
    return end_m - start_m


class ScheduleOp(BaseModel):
    """Optional schedule mutation proposed by the AI (applied in later steps).

    Attributes:
        op: Operation kind. Only ``set_schedule`` is allowed in B1.
        start_time: Proposed start time ``HH:MM`` on the 15-minute grid.
        end_time: Optional end time ``HH:MM`` on the 15-minute grid.
        frequency: Optional frequency override.
    """

    model_config = ConfigDict(extra="ignore")

    op: Literal["set_schedule"]
    start_time: str
    end_time: str | None = None
    frequency: FrequencyLiteral | None = None

    @field_validator("start_time")
    @classmethod
    def _validate_start_time(cls, value: str) -> str:
        _parse_hh_mm(value)
        return value.strip()

    @field_validator("end_time")
    @classmethod
    def _validate_end_time(cls, value: str | None) -> str | None:
        if value is None:
            return None
        _parse_hh_mm(value)
        return value.strip()

    @model_validator(mode="after")
    def _validate_range(self) -> ScheduleOp:
        if self.end_time is not None:
            start = _parse_hh_mm(self.start_time)
            end = _parse_hh_mm(self.end_time)
            _minutes_between(start, end)
        return self


class AskQuestions(BaseModel):
    """AI asks clarifying questions instead of proposing a plan yet.

    Attributes:
        type: Discriminator; always ``ask_questions``.
        questions: Non-empty list of questions for the user.
        context: Optional short context / reason for the questions.
    """

    model_config = ConfigDict(extra="ignore")

    type: Literal["ask_questions"] = "ask_questions"
    questions: list[str] = Field(min_length=1)
    context: str | None = None

    @field_validator("questions")
    @classmethod
    def _non_empty_questions(cls, value: list[str]) -> list[str]:
        cleaned = [q.strip() for q in value if isinstance(q, str) and q.strip()]
        if not cleaned:
            raise ValueError("questions must contain at least one non-empty string")
        return cleaned


class ProposePlan(BaseModel):
    """AI proposes a concrete habit plan with schedule fields.

    Attributes:
        type: Discriminator; always ``propose_plan``.
        title: Habit title (1–200 characters).
        start_time: Start time ``HH:MM`` on the 15-minute grid.
        end_time: Optional end time ``HH:MM`` on the 15-minute grid.
        frequency: Optional frequency (``daily`` / ``weekdays`` / ``weekends``).
        duration_minutes: Optional duration; if start+end+duration are all set,
            duration must equal ``end - start`` (reject + log on mismatch).
        comment: Free-text coach comment.
        schedule_ops: Optional list of schedule operations (stub for B3).
    """

    model_config = ConfigDict(extra="ignore")

    type: Literal["propose_plan"] = "propose_plan"
    title: str = Field(min_length=1, max_length=200)
    start_time: str
    end_time: str | None = None
    frequency: FrequencyLiteral | None = None
    duration_minutes: int | None = None
    comment: str = ""
    schedule_ops: list[ScheduleOp] | None = None

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("title must not be empty")
        return cleaned

    @field_validator("start_time")
    @classmethod
    def _validate_start_time(cls, value: str) -> str:
        _parse_hh_mm(value)
        return value.strip()

    @field_validator("end_time")
    @classmethod
    def _validate_end_time(cls, value: str | None) -> str | None:
        if value is None:
            return None
        _parse_hh_mm(value)
        return value.strip()

    @field_validator("duration_minutes")
    @classmethod
    def _validate_duration(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("duration_minutes must be an integer")
        if value <= 0:
            raise ValueError("duration_minutes must be positive")
        if value % 15 != 0:
            raise ValueError("duration_minutes must be a multiple of 15")
        return value

    @model_validator(mode="after")
    def _validate_duration_integrity(self) -> ProposePlan:
        """Reject when start/end/duration disagree; never auto-fix."""
        if self.end_time is not None:
            start = _parse_hh_mm(self.start_time)
            end = _parse_hh_mm(self.end_time)
            try:
                span = _minutes_between(start, end)
            except ValueError as exc:
                logger.warning(
                    "AI ProposePlan rejected: invalid time range %s–%s (%s)",
                    self.start_time,
                    self.end_time,
                    exc,
                )
                raise

            if self.duration_minutes is not None and self.duration_minutes != span:
                logger.warning(
                    "AI ProposePlan rejected: duration_minutes=%s but "
                    "end-start=%s (%s–%s); policy=reject (no auto-fix)",
                    self.duration_minutes,
                    span,
                    self.start_time,
                    self.end_time,
                )
                raise ValueError(
                    f"duration_minutes ({self.duration_minutes}) must equal "
                    f"end-start ({span}) minutes"
                )
        return self


AIResponse = Annotated[
    Union[AskQuestions, ProposePlan],
    Field(discriminator="type"),
]
"""Discriminated union of supported AI response shapes."""


def parse_ai_response(raw: str | dict[str, Any] | None) -> AskQuestions | ProposePlan | None:
    """Parse and validate a raw AI payload into a typed response.

    Never raises for untrusted input. Returns ``None`` on any failure
    (null/empty content, non-JSON, schema/validation errors).

    Args:
        raw: Raw model content string, already-parsed dict, or ``None``.

    Returns:
        Validated ``AskQuestions`` or ``ProposePlan``, or ``None``.
    """
    if raw is None:
        logger.warning("parse_ai_response: raw is None")
        return None

    data: Any
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            logger.warning("parse_ai_response: empty/whitespace content")
            return None
        # Tolerate optional markdown fences from chatty models
        if text.startswith("```"):
            lines = text.splitlines()
            # drop first fence line and optional trailing fence
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                "parse_ai_response: non-JSON content (%s): %s...",
                exc,
                text[:200],
            )
            return None
    elif isinstance(raw, dict):
        data = raw
    else:
        logger.warning(
            "parse_ai_response: unsupported raw type %s",
            type(raw).__name__,
        )
        return None

    if not isinstance(data, dict):
        logger.warning(
            "parse_ai_response: JSON root is not an object: %s",
            type(data).__name__,
        )
        return None

    try:
        # Pydantic v2 discriminated union via TypeAdapter-like validate
        response_type = data.get("type")
        if response_type == "ask_questions":
            return AskQuestions.model_validate(data)
        if response_type == "propose_plan":
            return ProposePlan.model_validate(data)
        logger.warning(
            "parse_ai_response: missing or unknown type %r",
            response_type,
        )
        return None
    except ValidationError as exc:
        logger.warning("parse_ai_response: validation failed: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001 — never crash callers
        logger.error(
            "parse_ai_response: unexpected error: %s",
            exc,
            exc_info=True,
        )
        return None
