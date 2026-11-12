"""Classify scheduled public-data wrapper summaries. Reporting only; never qualification."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from auvexo_alpha.application.data_schedule import (
    FIRST_SCHEDULED_DAY,
    SCHEDULE_ID,
    START_TOLERANCE,
    qualification_window,
)

NightState = Literal[
    "COMPLETE",  # one on-time scheduled wrapper run reported COMMAND_COMPLETE
    "FAILED",  # one on-time scheduled run reported a failure
    "MISSED_START",  # the wrapper itself recorded a missed window start
    "REFUSED",  # the wrapper refused to run (for example, started outside the pre-window)
    "AMBIGUOUS",  # more than one scheduled summary, or a completed run with an off-time start
    "NO_SUMMARY",  # nothing was recorded: the task did not start, or it failed before writing
]
MAX_REASON = 64


@dataclass(frozen=True)
class NightEvidence:
    day: date
    state: NightState
    started_at: datetime | None
    reason: str | None
    summaries: int


def _started(summary: Mapping[str, object]) -> datetime | None:
    raw = summary.get("started_at")
    if type(raw) is not str or len(raw) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _reason(summary: Mapping[str, object]) -> str | None:
    """Only short upper-case codes are surfaced; free text never leaves the summary file."""
    for key in ("reason", "status"):
        value = summary.get(key)
        if (
            type(value) is str
            and 0 < len(value) <= MAX_REASON
            and value.replace("_", "").isalnum()
            and value == value.upper()
        ):
            return value
    return None


def _on_time(started: datetime, day: date) -> bool:
    target, _ = qualification_window(day)
    return timedelta(0) < target - started <= START_TOLERANCE


def _scheduled(summary: Mapping[str, object]) -> bool:
    return summary.get("mode") == "scheduled" and summary.get("schedule_id") == SCHEDULE_ID


def classify_nights(
    summaries: Iterable[Mapping[str, object]], *, last_day: date
) -> tuple[tuple[NightEvidence, ...], int]:
    """Return one record per UTC day from the first eligible day and the unreadable count.

    A wrapper summary proves only what the wrapper did. COMPLETE is therefore an upper
    bound on qualifying dates, never a qualifying date: qualification is decided from
    verified stored events by the reviewed qualification command.
    """
    by_day: dict[date, list[tuple[datetime, Mapping[str, object]]]] = {}
    unreadable = 0
    for summary in summaries:
        if not _scheduled(summary):
            continue
        started = _started(summary)
        if started is None:
            unreadable += 1
            continue
        by_day.setdefault(started.date(), []).append((started, summary))
    nights: list[NightEvidence] = []
    day = FIRST_SCHEDULED_DAY
    while day <= last_day:
        found = sorted(by_day.get(day, []), key=lambda item: item[0])
        if not found:
            nights.append(NightEvidence(day, "NO_SUMMARY", None, None, 0))
        elif len(found) > 1:
            nights.append(NightEvidence(day, "AMBIGUOUS", found[0][0], None, len(found)))
        else:
            started, summary = found[0]
            status = summary.get("status")
            state: NightState
            if status == "COMMAND_COMPLETE":
                state = "COMPLETE" if _on_time(started, day) else "AMBIGUOUS"
            elif status == "MISSED_START":
                state = "MISSED_START"
            elif type(status) is str and status.startswith("REFUSED"):
                state = "REFUSED"
            else:
                state = "FAILED"
            nights.append(NightEvidence(day, state, started, _reason(summary), 1))
        day += timedelta(days=1)
    return tuple(nights), unreadable


def summarize(nights: tuple[NightEvidence, ...]) -> dict[str, object]:
    counts: dict[str, int] = {}
    for night in nights:
        counts[night.state] = counts.get(night.state, 0) + 1
    longest = current = 0
    for night in nights:
        current = current + 1 if night.state == "COMPLETE" else 0
        longest = max(longest, current)
    return {
        "nights": len(nights),
        "by_state": dict(sorted(counts.items())),
        "wrapper_complete_nights": counts.get("COMPLETE", 0),
        "longest_consecutive_complete": longest,
        "current_consecutive_complete": current,
        "qualification": "NOT_INFERRED",
        "meaning": (
            "wrapper_complete_nights is an upper bound on genuine qualifying dates; "
            "zero completed nights proves zero qualifying dates"
        ),
    }
