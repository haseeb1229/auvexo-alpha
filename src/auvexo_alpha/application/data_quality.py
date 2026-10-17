"""Deterministic quality gates independent of network and storage."""

from datetime import datetime, timedelta

from auvexo_alpha.domain.market_data import (
    Candle,
    CoverageReport,
    DataQualityFinding,
    Interval,
    interval_seconds,
)


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
