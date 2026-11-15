"""Coverage and actual calendar-day qualification; absent observations remain absent."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from auvexo_alpha.application.data_schedule import (
    FIRST_SCHEDULED_DAY,
    SCHEDULE_DESCRIPTION,
    SCHEDULE_ID,
    prewindow,
    qualification_window,
)
from auvexo_alpha.domain.contracts import utc_time
from auvexo_alpha.domain.market_data import (
    CooldownSpan,
    DatasetManifest,
    GapReview,
    IngestionEvent,
)

STABLE_CODE = re.compile(r"[A-Z][A-Z0-9_]{2,63}")


def stable_code(value: object) -> str | None:
    """Pass a project UPPER_SNAKE code through; exception or child text is never evidence."""
    return value if isinstance(value, str) and STABLE_CODE.fullmatch(value) else None


@dataclass(frozen=True)
class ScheduledSummary:
    """Wrapper receipt fields parsed by the outer layer.

    `provenance` is the wrapper's own read-only Task Scheduler check (ADR-032 OBV2-06,
    applied to the public-data wrapper); a summary written before it existed is UNRECORDED.
    """

    started_at: datetime
    schedule_id: str
    mode: str
    status: str
    provenance: str = "UNRECORDED"


def scheduled_binding(day: date, summaries: Sequence[ScheduledSummary]) -> str:
    """Require the day's single scheduled wrapper receipt: on time, COMMAND_COMPLETE and
    launched by a Task Scheduler time trigger (provenance VERIFIED)."""
    found = [
        s
        for s in summaries
        if s.mode == "scheduled"
        and s.schedule_id == SCHEDULE_ID
        and utc_time(s.started_at).date() == day
    ]
    if not found:
        return "MISSING"
    if len(found) > 1:
        return "DUPLICATE"
    earliest, target = prewindow(day)
    if found[0].status != "COMMAND_COMPLETE":
        return "NOT_COMPLETE"
    if not earliest <= utc_time(found[0].started_at) < target:
        return "OUTSIDE_PREWINDOW"
    if found[0].provenance != "VERIFIED":
        return "PROVENANCE_" + (stable_code(found[0].provenance) or "INVALID")
    return "MATCHED"


def coverage_matrix(manifests: list[DatasetManifest]) -> list[dict[str, object]]:
    superseded = {m.supersedes for m in manifests if m.supersedes}
    rows: list[dict[str, object]] = []
    for m in manifests:
        if m.dataset_version in superseded:
            continue
        c = m.coverage
        rows.append(
            dict(
                instrument=c.instrument_id,
                venue="BINANCE",
                product="SPOT",
                symbol=c.instrument_id.rsplit(".", 1)[-1],
                timeframe=c.interval,
                source=m.source.source_id,
                earliest=c.earliest.isoformat() if c.earliest else None,
                latest_end=c.latest_end.isoformat() if c.latest_end else None,
                observed_rows=c.observed_rows,
                expected_rows=c.expected_rows,
                quality=c.status,
                findings=[f.model_dump(mode="json") for f in c.findings],
                dataset_version=m.dataset_version,
                source_url=m.source_url,
                source_hash=m.source_hash,
                rights=m.rights.version,
                permitted_use=m.rights.permitted_use,
                bytes=m.parquet_bytes,
                availability="Actual receipt only; historical publication UNKNOWN",
                limitation="Spot research only; not executable CFD quotes; "
                "unselected history UNKNOWN",
            )
        )
    for asset in ("BTC", "ETH", "XAU"):
        rows.append(
            dict(
                instrument="exness.cfd." + asset,
                venue="EXNESS",
                product="CFD",
                symbol=None,
                timeframe=None,
                source="DS-03",
                earliest=None,
                latest_end=None,
                observed_rows=0,
                expected_rows=None,
                quality="BLOCKED",
                bytes=0,
                limitation="Owner demo access/isolation/attestation absent; no substitute",
            )
        )
    return rows


def gap_rows(gaps: Sequence[GapReview]) -> list[dict[str, object]]:
    """Reviewed provider gaps stay in coverage for good: absent bars, never filled."""
    return [
        dict(
            instrument=g.instrument_id,
            venue="BINANCE",
            product="SPOT",
            symbol=g.instrument_id.rsplit(".", 1)[-1],
            timeframe=g.interval,
            source=g.source_id,
            quality="REVIEWED_PROVIDER_GAP",
            gap_start=g.gap_start.isoformat(),
            gap_end=g.gap_end.isoformat(),
            reason=g.reason,
            reviewer=g.reviewer,
            evidence=[e.model_dump(mode="json") for e in g.evidence],
            limitation="No bar exists for this range; it is never filled or repaired",
        )
        for g in gaps
    ]


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(), UTC)
    return start, start + timedelta(days=1)


def qualification(
    events: list[IngestionEvent],
    start: date,
    now: datetime,
    verified_manifests: list[DatasetManifest],
    summaries: Sequence[ScheduledSummary],
    *,
    cooldowns: Sequence[CooldownSpan],
    gaps: Sequence[GapReview],
) -> dict[str, object]:
    """Qualify observations only against caller-verified stored artifacts, never IDs alone.

    Stored events cannot tell a manual in-window run from the scheduled one, so each day
    also needs its single on-time completed wrapper receipt from the caller. A UTC day
    touched by any provider cooldown, or containing a reviewed provider gap, never
    qualifies: a failed day stays failed.
    """
    by_version = {m.dataset_version: m for m in verified_manifests}

    def verified(event: IngestionEvent) -> bool:
        manifest = by_version.get(event.dataset_version or "")
        if event.state != "FRESH" or manifest is None:
            return False
        coverage = manifest.coverage
        return (
            manifest.source.source_id == "DS-02"
            and manifest.source.family == "SPOT_REST"
            and coverage.interval == "1m"
            and coverage.status == "PASS"
            and coverage.observed_rows == coverage.expected_rows > 0
            and not coverage.findings
            and event.feed_key == "DS-02." + coverage.instrument_id.rsplit(".", 1)[-1] + ".1m"
            and manifest.logical_key.startswith(event.feed_key + ".")
            and event.observed_at == manifest.created_at
            and manifest.created_at <= manifest.processed_at <= now
            and timedelta(0) <= event.observed_at - coverage.requested_end <= timedelta(minutes=2)
        )

    days = []
    for offset in range(7):
        day = start + timedelta(days=offset)
        window_start, window_end = qualification_window(day)
        # Scheduled public-data window: 18:00 through 18:12 UTC. At least ten minutes
        # of genuine per-symbol observations, no >120-second heartbeat gaps.
        selected = sorted(
            [
                e
                for e in events
                if window_start <= e.observed_at < window_end
                and e.observed_at <= now
                and e.feed_key.startswith("DS-02.")
            ],
            key=lambda e: e.observed_at,
        )
        good = day >= FIRST_SCHEDULED_DAY
        for symbol in ("BTCUSDT", "ETHUSDT"):
            feed = sorted(
                (e for e in selected if e.feed_key == f"DS-02.{symbol}.1m"),
                key=lambda e: e.observed_at,
            )
            good = (
                good
                and len(feed) >= 11
                and len({e.event_id for e in feed}) == len(feed)
                and len({e.dataset_version for e in feed}) == len(feed)
                and all(verified(e) for e in feed)
            )
            if feed:
                good = good and (feed[-1].observed_at - feed[0].observed_at).total_seconds() >= 600
                good = good and all(
                    (b.observed_at - a.observed_at).total_seconds() <= 120
                    for a, b in zip(feed, feed[1:], strict=False)
                )
        closed = now >= window_end
        binding = scheduled_binding(day, summaries)
        first, last = day_bounds(day)
        cooled = sorted({c.event_id for c in cooldowns if c.start < last and first < c.end})
        gapped = sorted(
            f"{g.feed_key}:{g.gap_start.isoformat()}" for g in gaps if g.overlaps(first, last)
        )
        good = good and binding == "MATCHED" and not cooled and not gapped
        days.append(
            dict(
                day=day.isoformat(),
                events=len(selected),
                verified_events=sum(verified(e) for e in selected),
                invalid_event_ids=[e.event_id for e in selected if not verified(e)],
                scheduled_summary=binding,
                provider_cooldowns=cooled,
                reviewed_gaps=gapped,
                status="PASS" if good and closed else "OPEN" if not closed else "INCOMPLETE",
                first=selected[0].observed_at.isoformat() if selected else None,
                last=selected[-1].observed_at.isoformat() if selected else None,
            )
        )
    return dict(
        status="PASS" if all(d["status"] == "PASS" for d in days) else "OPEN",
        schedule_id=SCHEDULE_ID,
        schedule=SCHEDULE_DESCRIPTION,
        first_eligible_day=FIRST_SCHEDULED_DAY.isoformat(),
        days=days,
        scope="Public scheduled 12-minute UTC windows only; "
        "not continuous uptime or Exness qualification",
        scheduled_provenance="One on-time COMMAND_COMPLETE wrapper summary per day whose "
        "wrapper-recorded read-only Task Scheduler check is VERIFIED (time trigger, "
        "scheduler parent); the summary itself remains a local receipt",
    )
