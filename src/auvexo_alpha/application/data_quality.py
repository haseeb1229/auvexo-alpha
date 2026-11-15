"""Deterministic quality gates independent of network and storage."""

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Literal

from auvexo_alpha.domain.market_data import (
    PROVIDER_HOSTS,
    Candle,
    CooldownRelease,
    CooldownSpan,
    CoverageReport,
    DataQualityFinding,
    DatasetManifest,
    GapReview,
    IngestionEvent,
    Interval,
    ProviderHost,
    SourceComparison,
    SourceConflict,
    interval_seconds,
)

MARKET_FIELDS = (
    "open_at",
    "end_at",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_volume",
    "trades",
)
# One comparison or gap check reads at most this many stored versions; narrow the range.
MAX_COMPARED_VERSIONS = 4096


def market_values(bar: Candle) -> tuple[str, ...]:
    record = json.loads(bar.canonical_bytes())
    return tuple(str(record[field]) for field in MARKET_FIELDS)


def market_hash(bar: Candle) -> str:
    """Identify market values numerically: 67250.01000000 and 67250.01 are the same row.

    Fresh bars keep provider digits while stored bars are read back from their canonical
    record, so both sides are compared through that one canonical decimal form.
    """
    record = json.loads(bar.canonical_bytes())
    return hashlib.sha256(
        json.dumps([record[field] for field in MARKET_FIELDS]).encode("ascii")
    ).hexdigest()


Versioned = tuple[DatasetManifest, Sequence[Candle]]


def compare_sources(
    archive: Sequence[Versioned],
    rest: Sequence[Versioned],
    instrument: str,
    interval: Interval,
    start: datetime,
    end: datetime,
) -> tuple[SourceComparison, tuple[SourceConflict, ...]]:
    """Compare every archive version with every REST version for each bar in [start, end).

    Identical market values reconcile. Different values become conflicts that keep both
    source references; no source is chosen, no bar or availability time is rewritten.
    """
    step = timedelta(seconds=interval_seconds(interval))
    if start >= end or (end - start) % step:
        raise ValueError("COMPARISON_RANGE_INVALID")
    if len(archive) + len(rest) > MAX_COMPARED_VERSIONS:
        raise ValueError("COMPARISON_BUDGET_EXCEEDED")
    for expected, side in (("DS-01", archive), ("DS-02", rest)):
        for manifest, _ in side:
            if (
                manifest.source.source_id != expected
                or manifest.coverage.instrument_id != instrument
                or manifest.coverage.interval != interval
            ):
                raise ValueError("COMPARISON_SOURCE_MISMATCH")

    def by_open(side: Sequence[Versioned]) -> dict[datetime, list[tuple[DatasetManifest, Candle]]]:
        table: dict[datetime, list[tuple[DatasetManifest, Candle]]] = {}
        for manifest, bars in sorted(side, key=lambda item: item[0].dataset_version):
            for bar in bars:
                if start <= bar.open_at < end:
                    table.setdefault(bar.open_at, []).append((manifest, bar))
        return table

    archived, polled = by_open(archive), by_open(rest)
    matched = archive_only = rest_only = 0
    conflicts: list[SourceConflict] = []
    for opened in sorted(archived.keys() | polled.keys()):
        left, right = archived.get(opened, []), polled.get(opened, [])
        if not right:
            archive_only += 1
            continue
        if not left:
            rest_only += 1
            continue
        for a_manifest, a_bar in left:
            for r_manifest, r_bar in right:
                a_hash, r_hash = market_hash(a_bar), market_hash(r_bar)
                if a_hash == r_hash:
                    matched += 1
                    continue
                conflicts.append(
                    SourceConflict.model_validate(
                        dict(
                            instrument_id=a_bar.instrument_id,
                            interval=interval,
                            open_at=opened,
                            archive_version=a_manifest.dataset_version,
                            archive_source_hash=a_manifest.source_hash,
                            archive_rights_version=a_manifest.rights.version,
                            archive_market_hash=a_hash,
                            archive_values=market_values(a_bar),
                            rest_version=r_manifest.dataset_version,
                            rest_source_hash=r_manifest.source_hash,
                            rest_rights_version=r_manifest.rights.version,
                            rest_market_hash=r_hash,
                            rest_values=market_values(r_bar),
                            known_at=max(
                                a_bar.availability.available_at, r_bar.availability.available_at
                            ),
                        )
                    )
                )
    comparison = SourceComparison.model_validate(
        dict(
            instrument_id=instrument,
            interval=interval,
            range_start=start,
            range_end=end,
            archive_versions=tuple(sorted(m.dataset_version for m, _ in archive)),
            rest_versions=tuple(sorted(m.dataset_version for m, _ in rest)),
            matched=matched,
            archive_only=archive_only,
            rest_only=rest_only,
            conflicts=tuple(c.content_hash() for c in conflicts),
        )
    )
    return comparison, tuple(conflicts)


def gap_evidence_refusal(
    review: GapReview,
    evidence: Sequence[Versioned],
    contradicting: Sequence[Versioned],
    checkpoint_next_open: datetime | None,
) -> str | None:
    """Why the stored responses do not prove the reviewed range absent, or None if they do.

    Evidence must be at least two distinct DS-02 responses for this exact feed, each
    requesting the whole range and returning none of its bars. Any stored DS-02 response
    holding a bar in the range contradicts the claim. The range must not precede the
    feed's checkpoint: a reviewed gap only ever moves the collector forward.
    """
    symbol = review.instrument_id.rsplit(".", 1)[-1]
    step = timedelta(seconds=interval_seconds(review.interval))
    by_version = {manifest.dataset_version: (manifest, bars) for manifest, bars in evidence}
    if set(by_version) != {item.dataset_version for item in review.evidence}:
        return "GAP_EVIDENCE_NOT_STORED"
    if checkpoint_next_open is None:
        return "GAP_FEED_HAS_NO_CHECKPOINT"
    if review.gap_start < checkpoint_next_open:
        return "GAP_BEFORE_CHECKPOINT"
    for item in review.evidence:
        manifest, bars = by_version[item.dataset_version]
        coverage = manifest.coverage
        if (
            manifest.source.source_id != "DS-02"
            or manifest.source.family != "SPOT_REST"
            or coverage.instrument_id != review.instrument_id
            or coverage.interval != review.interval
            or not manifest.logical_key.startswith(f"DS-02.{symbol}.{review.interval}.")
            or manifest.source_hash != item.source_hash
            or manifest.created_at != item.received_at
        ):
            return "GAP_EVIDENCE_SOURCE_MISMATCH"
        if (
            not coverage.requested_start
            <= review.gap_start
            < review.gap_end
            <= (coverage.requested_end)
        ):
            return "GAP_EVIDENCE_DOES_NOT_REQUEST_RANGE"
        if any(review.overlaps(bar.open_at, bar.end_at) for bar in bars):
            return "GAP_EVIDENCE_CONFLICT"
        # The stored coverage report itself must name the absence; bars alone are not enough.
        if not any(
            finding.code == "GAP"
            and finding.first_at is not None
            and finding.last_at is not None
            and finding.first_at <= review.gap_start
            and review.gap_end <= finding.last_at + step
            for finding in coverage.findings
        ):
            return "GAP_NOT_RECORDED_BY_EVIDENCE"
    for _, bars in contradicting:
        if any(review.overlaps(bar.open_at, bar.end_at) for bar in bars):
            return "GAP_EVIDENCE_CONFLICT"
    return None


def cooldown_spans(
    events: Sequence[IngestionEvent], passed_probes: Sequence[tuple[CooldownRelease, datetime]]
) -> tuple[CooldownSpan, ...]:
    """How long each cooldown actually blocked each host: to expiry, or to a passed owner
    probe on that host.

    A legacy cooldown without a host blocks every host (as in ``cooldown_state``), so it
    yields one span per host, each ended only by that host's own passed probe.
    """
    spans = []
    for event in events:
        if event.blocked_until is None:
            continue
        hosts = PROVIDER_HOSTS if event.cooldown_host is None else (event.cooldown_host,)
        for host in hosts:
            end = event.blocked_until
            for release, passed_at in passed_probes:
                if (
                    release.host == host
                    and event.event_id in release.released_events
                    and event.observed_at <= passed_at < end
                ):
                    end = passed_at
            spans.append(
                CooldownSpan(
                    event_id=event.event_id,
                    host=host,
                    reason=event.reason,
                    start=event.observed_at,
                    end=max(end, event.observed_at),
                )
            )
    return tuple(sorted(spans, key=lambda span: (span.start, span.event_id, span.host)))


CooldownState = Literal["CLEAR", "BLOCKED", "PROBE_AVAILABLE"]


def cooldown_state(
    now: datetime,
    host: ProviderHost,
    active: Sequence[IngestionEvent],
    release: CooldownRelease | None,
    probe_started: bool,
    probe_passed: bool,
) -> CooldownState:
    """Active cooldowns block a host until expiry. An owner release made after the latest
    active cooldown allows exactly one probe; only a passed probe clears the host early.
    """
    blocking = [
        e
        for e in active
        if e.blocked_until is not None
        and e.blocked_until > now
        and e.observed_at <= now
        and e.cooldown_host in (None, host)
    ]
    if not blocking:
        return "CLEAR"
    latest = max(e.observed_at for e in blocking)
    if (
        release is None
        or release.host != host
        or release.released_at < latest
        or not {e.event_id for e in blocking} <= set(release.released_events)
    ):
        return "BLOCKED"
    if not probe_started:
        return "PROBE_AVAILABLE"
    return "CLEAR" if probe_passed else "BLOCKED"


def assess(
    bars: list[Candle],
    instrument: str,
    interval: Interval,
    start: datetime,
    end: datetime,
    findings: list[DataQualityFinding] | None = None,
    rejected: int = 0,
) -> tuple[list[Candle], CoverageReport]:
    step = timedelta(seconds=interval_seconds(interval))
    if start >= end or (end - start) % step:
        raise ValueError("invalid coverage interval")
    issues = list(findings or [])
    unique: dict[datetime, Candle] = {}
    previous = None
    for bar in bars:
        if (
            bar.instrument_id != instrument
            or bar.interval != interval
            or not start <= bar.open_at < end
        ):
            raise ValueError("SPEC_UNIT_OR_RANGE")
        if previous is not None and bar.open_at < previous:
            issues.append(
                DataQualityFinding(code="OUT_OF_ORDER", detail="provider order regressed")
            )
        previous = bar.open_at
        if bar.open_at in unique:
            if bar != unique[bar.open_at]:
                raise ValueError("CONFLICTING_DUPLICATE")
            issues.append(DataQualityFinding(code="DUPLICATE", detail="identical row collapsed"))
        unique[bar.open_at] = bar
    ordered = [unique[key] for key in sorted(unique)]
    cursor = start
    for bar in ordered:
        if bar.open_at > cursor:
            issues.append(
                DataQualityFinding(
                    code="GAP",
                    count=(bar.open_at - cursor) // step,
                    first_at=cursor,
                    last_at=bar.open_at - step,
                    detail="absent candles; never filled",
                )
            )
        cursor = bar.end_at
    if cursor < end:
        issues.append(
            DataQualityFinding(
                code="GAP",
                count=(end - cursor) // step,
                first_at=cursor,
                last_at=end - step,
                detail="absent trailing candles",
            )
        )
    return ordered, CoverageReport(
        instrument_id=instrument,
        interval=interval,
        requested_start=start,
        requested_end=end,
        earliest=ordered[0].open_at if ordered else None,
        latest_end=ordered[-1].end_at if ordered else None,
        expected_rows=(end - start) // step,
        observed_rows=len(ordered),
        rejected_rows=rejected,
        findings=tuple(issues),
        status="BLOCKED" if not ordered else "DEGRADED" if issues else "PASS",
    )
