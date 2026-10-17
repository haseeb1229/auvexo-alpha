"""Research venue unavailability is explicit evidence, never a replacement candle."""

from datetime import datetime, timedelta
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from auvexo_alpha.domain.contracts import Contract, Digest, Label, UTCTime
from auvexo_alpha.domain.market_data import DatasetManifest, interval_seconds


class ProviderEvidence(Contract):
    url: str
    sha256: Digest
    retrieved_at: UTCTime
    representation: Literal["VERIFIED_FACT_EXTRACT", "SOURCE_BYTES"]
    reviewer_ref: Label

    @model_validator(mode="after")
    def official_provider(self) -> Self:
        parsed = urlsplit(self.url)
        if parsed.scheme != "https" or parsed.hostname not in ("www.binance.com", "binance.com"):
            raise ValueError("OFFICIAL_PROVIDER_EVIDENCE_REQUIRED")
        if parsed.username or parsed.password or parsed.port:
            raise ValueError("INVALID_PROVIDER_EVIDENCE_URL")
        return self


class VenueUnavailable(Contract):
    category: Literal["PROVIDER_OUTAGE_CONFIRMED"] = "PROVIDER_OUTAGE_CONFIRMED"
    source_id: Literal["DS-01", "DS-02"]
    provider: Literal["BINANCE"] = "BINANCE"
    product: Literal["SPOT"] = "SPOT"
    instrument: Literal["binance.spot.BTCUSDT", "binance.spot.ETHUSDT"]
    start: UTCTime
    end: UTCTime
    effective_at: UTCTime
    source_manifest: Digest
    source_hash: Digest
    missing_start: UTCTime
    missing_end: UTCTime
    truncated_openings: tuple[UTCTime, ...]
    rejected_rows: Annotated[int, Field(ge=0, le=1000)]
    source_diagnosis_hash: Digest
    evidence: tuple[ProviderEvidence, ...] = Field(min_length=1, max_length=8)
    knowledge: Literal["UNPLANNED_EFFECTIVE_AT_UNAVAILABILITY"] = (
        "UNPLANNED_EFFECTIVE_AT_UNAVAILABILITY"
    )

    @model_validator(mode="after")
    def bounded_unplanned(self) -> Self:
        if not (
            self.start == self.effective_at < self.end <= self.start + timedelta(days=7)
            and self.start <= self.missing_start < self.missing_end <= self.end
        ):
            raise ValueError("INVALID_OR_ANTICIPATED_UNAVAILABLE_INTERVAL")
        if self.rejected_rows != len(self.truncated_openings) or any(
            not self.start <= t < self.end for t in self.truncated_openings
        ):
            raise ValueError("UNBOUND_TRUNCATED_ROW_EVIDENCE")
        return self

    def contains(self, at: datetime) -> bool:
        return self.effective_at <= at < self.end

    def overlaps(self, start: datetime, end: datetime) -> bool:
        return self.start < end and start < self.end


def coverage_disposition(
    manifest: DatasetManifest, outages: tuple[VenueUnavailable, ...] = ()
) -> Literal["COMPLETE", "PROVIDER_OUTAGE_CONFIRMED", "UNKNOWN_GAP_BLOCKED"]:
    coverage = manifest.coverage
    if (
        coverage.status == "PASS"
        and coverage.observed_rows == coverage.expected_rows
        and not coverage.findings
        and coverage.rejected_rows == 0
    ):
        return "COMPLETE"
    if coverage.status != "DEGRADED" or coverage.observed_rows <= 0:
        return "UNKNOWN_GAP_BLOCKED"
    matched = tuple(
        o
        for o in outages
        if (
            o.source_manifest == manifest.dataset_version
            and o.source_hash == manifest.source_hash
            and o.source_id == manifest.source.source_id
            and o.instrument == coverage.instrument_id
            and manifest.source.provider == o.provider
        )
    )
    if not matched or coverage.rejected_rows != sum(o.rejected_rows for o in matched):
        return "UNKNOWN_GAP_BLOCKED"
    step = timedelta(seconds=interval_seconds(coverage.interval))
    gaps = 0
    rejected = 0
    for finding in coverage.findings:
        if finding.code == "GAP":
            if finding.first_at is None or finding.last_at is None:
                return "UNKNOWN_GAP_BLOCKED"
            if not any(
                o.missing_start == finding.first_at and finding.last_at + step == o.missing_end
                for o in matched
            ):
                return "UNKNOWN_GAP_BLOCKED"
            gaps += finding.count
        elif finding.code in ("TRUNCATED_INTERVAL", "TIMESTAMP_UNIT"):
            # Legacy spot.v1's label is admitted ONLY by a source-bound raw diagnosis.
            if finding.code == "TIMESTAMP_UNIT" and manifest.parser_version != "spot.v1":
                return "UNKNOWN_GAP_BLOCKED"
            rejected += finding.count
        else:
            return "UNKNOWN_GAP_BLOCKED"
    if (
        gaps != coverage.expected_rows - coverage.observed_rows
        or rejected != coverage.rejected_rows
        or gaps <= 0
    ):
        return "UNKNOWN_GAP_BLOCKED"
    return "PROVIDER_OUTAGE_CONFIRMED"
