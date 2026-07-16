"""Central AI plan time normalization (B5).

Policy: correct + show warning (never silently stretch duration).
Snap times to the 15-minute grid; recompute end from duration when set.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import time
from typing import Any, Literal

from src.utils.time_picker import MINUTES_15

logger = logging.getLogger(__name__)

_HH_MM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
"""Strict zero-padded ``HH:MM`` (any minute 00–59; grid applied by snap)."""

PlanKind = Literal["habit", "task"]


@dataclass(frozen=True)
class NormalizeResult:
    """Outcome of :func:`normalize_plan_times`.

    Attributes:
        ok: True when the plan can be used after normalization.
        plan: Normalized plan dict (HH:MM strings, int duration) when ok.
        warnings: Human-readable corrections for preview UI.
        corrections: Machine-readable tags for logs/tests.
        error: Reason when ``ok`` is False.
    """

    ok: bool
    plan: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    corrections: list[str] = field(default_factory=list)
    error: str | None = None


def snap_total_minutes(total: int) -> int:
    """Round *total* minutes-from-midnight to nearest 15-min slot.

    Ties (exactly halfway, e.g. +7.5 is impossible for int minutes; for
    remainder 8..14 go up, 1..7 go down) use nearest; remainder 7.5 N/A.
    Equal distance: remainder 7.5 doesn't exist; for remainder==7.5 we'd
    round half up — with ints, rem 8 is closer to +15 than to 0.

    Clamped to ``[0, 23*60+45]`` (last valid same-day slot).
    """
    if total < 0:
        return 0
    max_slot = 23 * 60 + 45
    if total > max_slot:
        # Prefer last slot of the day rather than wrapping
        return max_slot
    # Nearest 15: rem 0..7 → down, 8..14 → up
    rem = total % 15
    if rem == 0:
        return total
    if rem <= 7:
        return total - rem
    return total - rem + 15


def snap_time(t: time) -> time:
    """Snap a :class:`~datetime.time` to the nearest 15-minute grid."""
    total = snap_total_minutes(t.hour * 60 + t.minute)
    return time(total // 60, total % 60)


def snap_hh_mm(value: Any) -> tuple[str | None, bool]:
    """Parse ``HH:MM`` (lenient minutes 0–59) and snap to 15-min grid.

    Returns:
        ``(snapped_hh_mm, was_corrected)`` or ``(None, False)`` on failure.
    """
    if value is None or not isinstance(value, str):
        return None, False
    text = value.strip()
    match = _HH_MM_RE.fullmatch(text)
    if match is None:
        return None, False
    hour = int(match.group(1))
    minute = int(match.group(2))
    original = time(hour, minute)
    snapped = snap_time(original)
    snapped_s = snapped.strftime("%H:%M")
    corrected = snapped != original
    return snapped_s, corrected


def _parse_duration(value: Any) -> tuple[int | None, str | None]:
    """Return ``(duration, error)``.

    Valid: positive int, multiple of 15, >= 15, not bool.
    ``None`` is allowed (no duration).
    """
    if value is None:
        return None, None
    if isinstance(value, bool) or not isinstance(value, int):
        try:
            if isinstance(value, float) and value == int(value):
                value = int(value)
            else:
                value = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None, "duration_minutes is not an integer"
    if isinstance(value, bool):
        return None, "duration_minutes must not be a boolean"
    if value <= 0:
        return None, "duration_minutes must be positive"
    if value < 15:
        return None, "duration_minutes must be >= 15"
    if value % 15 != 0:
        return None, "duration_minutes must be a multiple of 15"
    return value, None


def _add_minutes_hh_mm(start_s: str, minutes: int) -> str | None:
    """Return end HH:MM = start + minutes, or None if crosses midnight."""
    match = _HH_MM_RE.fullmatch(start_s)
    if match is None:
        return None
    total = int(match.group(1)) * 60 + int(match.group(2)) + minutes
    if total >= 24 * 60:
        return None
    return f"{total // 60:02d}:{total % 60:02d}"


def _minutes_between_hh_mm(start_s: str, end_s: str) -> int | None:
    """Same-day duration; None if invalid / end <= start."""
    sm = _HH_MM_RE.fullmatch(start_s)
    em = _HH_MM_RE.fullmatch(end_s)
    if sm is None or em is None:
        return None
    start_m = int(sm.group(1)) * 60 + int(sm.group(2))
    end_m = int(em.group(1)) * 60 + int(em.group(2))
    if end_m <= start_m:
        return None
    return end_m - start_m


def _as_dict(plan: Any) -> dict[str, Any] | None:
    if plan is None:
        return None
    if isinstance(plan, dict):
        return dict(plan)
    if hasattr(plan, "model_dump"):
        try:
            return plan.model_dump()
        except Exception:
            return None
    return None


def normalize_plan_times(
    plan: Any,
    *,
    kind: PlanKind = "habit",
) -> NormalizeResult:
    """Normalize start/end/duration on a ProposePlan / ProposeTaskPlan payload.

    Rules:
      1. Snap start/end to nearest 15-minute grid.
      2. If duration is set and valid → recompute end = start + duration.
      3. If end set without duration → compute duration from snapped range.
      4. Reject duration < 15 or not multiple of 15 (no silent stretch).
      5. Never raise; missing/invalid fields → ``ok=False``.

    Args:
        plan: ProposePlan, ProposeTaskPlan, dict dump, or None.
        kind: ``habit`` requires end or duration; ``task`` allows open-ended.

    Returns:
        NormalizeResult with corrected plan and warnings when ok.
    """
    data = _as_dict(plan)
    if data is None:
        return NormalizeResult(ok=False, error="plan is missing or invalid")

    warnings: list[str] = []
    corrections: list[str] = []

    # --- start_time (required) ---
    raw_start = data.get("start_time")
    start_s, start_corrected = snap_hh_mm(raw_start)
    if start_s is None:
        logger.warning(
            "normalize_plan_times: missing/invalid start_time %r", raw_start
        )
        return NormalizeResult(
            ok=False,
            error="missing or invalid start_time",
            corrections=["reject_start"],
        )
    if start_corrected:
        corrections.append("snap_start")
        warnings.append(f"start_time {raw_start} → {start_s}")
        logger.warning(
            "AI times corrected: start_time %r → %s", raw_start, start_s
        )

    # --- end_time (optional, snap if present) ---
    raw_end = data.get("end_time")
    end_s: str | None = None
    if raw_end is not None and raw_end != "":
        end_s, end_corrected = snap_hh_mm(raw_end)
        if end_s is None:
            logger.warning(
                "normalize_plan_times: invalid end_time %r", raw_end
            )
            return NormalizeResult(
                ok=False,
                error="invalid end_time",
                corrections=corrections + ["reject_end"],
                warnings=warnings,
            )
        if end_corrected:
            corrections.append("snap_end")
            warnings.append(f"end_time {raw_end} → {end_s}")
            logger.warning(
                "AI times corrected: end_time %r → %s", raw_end, end_s
            )

    # --- duration ---
    raw_duration = data.get("duration_minutes")
    duration, dur_err = _parse_duration(raw_duration)
    if dur_err is not None and raw_duration is not None:
        # Explicit invalid duration → reject (do not silently fix 10→15)
        logger.warning(
            "AI plan rejected: duration_minutes=%r (%s)", raw_duration, dur_err
        )
        return NormalizeResult(
            ok=False,
            error=dur_err,
            corrections=corrections + ["reject_duration"],
            warnings=warnings,
        )

    # --- recompute end / duration ---
    if duration is not None:
        derived_end = _add_minutes_hh_mm(start_s, duration)
        if derived_end is None:
            logger.warning(
                "AI plan rejected: start %s + duration %s crosses midnight",
                start_s,
                duration,
            )
            return NormalizeResult(
                ok=False,
                error="end time would cross midnight",
                corrections=corrections + ["reject_midnight"],
                warnings=warnings,
            )
        if end_s is not None and end_s != derived_end:
            corrections.append("duration_overrides_end")
            warnings.append(
                f"end_time {end_s} → {derived_end} "
                f"(duration_minutes={duration})"
            )
            logger.warning(
                "AI times corrected: duration_minutes=%s overrides end "
                "%s → %s (start=%s)",
                duration,
                end_s,
                derived_end,
                start_s,
            )
        end_s = derived_end
    elif end_s is not None:
        span = _minutes_between_hh_mm(start_s, end_s)
        if span is None:
            logger.warning(
                "AI plan rejected: invalid range %s–%s", start_s, end_s
            )
            return NormalizeResult(
                ok=False,
                error="end_time must be after start_time",
                corrections=corrections + ["reject_range"],
                warnings=warnings,
            )
        # Span after snap should already be multiple of 15 if both on grid
        if span % 15 != 0:
            # Should not happen if both snapped; reject defensively
            logger.warning(
                "AI plan rejected: span %s not multiple of 15 (%s–%s)",
                span,
                start_s,
                end_s,
            )
            return NormalizeResult(
                ok=False,
                error="duration must be a multiple of 15",
                corrections=corrections + ["reject_span"],
                warnings=warnings,
            )
        if span < 15:
            logger.warning(
                "AI plan rejected: span %s < 15 (%s–%s)", span, start_s, end_s
            )
            return NormalizeResult(
                ok=False,
                error="duration must be >= 15",
                corrections=corrections + ["reject_span"],
                warnings=warnings,
            )
        duration = span
        corrections.append("duration_from_range")
    else:
        # No end, no duration
        if kind == "habit":
            logger.warning(
                "AI plan rejected: habit plan missing end_time and duration"
            )
            return NormalizeResult(
                ok=False,
                error="missing end_time and duration_minutes",
                corrections=corrections + ["reject_missing_end"],
                warnings=warnings,
            )
        # task open-ended OK
        duration = None

    # Final grid check (derived end always on grid if start+duration are)
    if end_s is not None:
        em = _HH_MM_RE.fullmatch(end_s)
        if em is None or int(em.group(2)) not in MINUTES_15:
            logger.warning(
                "AI plan rejected: end_time %s not on 15-min grid", end_s
            )
            return NormalizeResult(
                ok=False,
                error="end_time not on 15-min grid",
                corrections=corrections + ["reject_end_grid"],
                warnings=warnings,
            )

    out = dict(data)
    out["start_time"] = start_s
    out["end_time"] = end_s
    out["duration_minutes"] = duration

    if warnings:
        logger.info(
            "normalize_plan_times ok with corrections=%s warnings=%s",
            corrections,
            warnings,
        )

    return NormalizeResult(
        ok=True,
        plan=out,
        warnings=warnings,
        corrections=corrections,
        error=None,
    )
