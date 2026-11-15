"""Versioned data contracts. No trading authority or inferred broker specification."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Final, Literal, Self

from pydantic import Field, model_validator

from auvexo_alpha.domain.contracts import (
    Contract,
    Currency,
    Digest,
    Label,
    NonnegativeAmount,
    PositiveAmount,
    Product,
    UTCTime,
    Venue,
    utc_time,
)

Symbol = Literal["BTCUSDT", "ETHUSDT"]
Interval = Literal["1m", "1h"]
QualityCode = Literal[
    "SCHEMA",
    "OHLC",
    "VOLUME",
    "DUPLICATE",
    "OUT_OF_ORDER",
    "GAP",
    "PARTIAL",
    "STALE",
    "TIMESTAMP_UNIT",
    "TRUNCATED_INTERVAL",
    "INTERVAL_BOUNDARY",
    "IMPLAUSIBLE_TIME",
    "SPEC_UNIT",
    "CHECKSUM",
    "CORRECTION",
    "INSUFFICIENT_HISTORY",
    "SESSION",
    "NETWORK",
    "QUOTA",
    "UNKNOWN",
]


class SourceRights(Contract):
    source_id: Literal["DS-01", "DS-02", "DS-03"]
    version: Label
    reviewed_at: UTCTime
    review_due: UTCTime
    evidence_urls: tuple[str, ...] = Field(min_length=1)
    terms_hash: Digest
    permitted_use: Literal["PERSONAL_NONPRODUCTION_RESEARCH", "BLOCKED"]
    redistribution: Literal["CC-BY-NC-SA-4.0", "NOT_AUTHORIZED"]
    retention: str = Field(min_length=1, max_length=512)

    def require_research(self, now: datetime) -> None:
        if self.permitted_use != "PERSONAL_NONPRODUCTION_RESEARCH" or not (
            self.reviewed_at <= utc_time(now) < self.review_due
        ):
            raise ValueError("SOURCE_RIGHTS_BLOCKED_OR_EXPIRED")


class SourceIdentity(Contract):
    source_id: Literal["DS-01", "DS-02", "DS-03"]
    provider: Literal["BINANCE", "EXNESS"]
    family: Literal["SPOT_ARCHIVE", "SPOT_REST", "MT5_DEMO"]
    endpoint: str
    rights_version: Label


class InstrumentAlias(Contract):
    instrument_id: Label
    asset: Literal["BTC", "ETH", "XAU"]
    venue: Venue
    product: Product
    provider_symbol: Label | None
    quote_currency: Currency | None
    mapping_version: Label

    @model_validator(mode="after")
    def identity(self) -> Self:
        if self.venue == Venue.BINANCE:
            if (
                self.product != Product.SPOT
                or self.asset not in ("BTC", "ETH")
                or self.provider_symbol != self.asset + "USDT"
                or self.quote_currency != "USDT"
                or self.instrument_id != "binance.spot." + self.provider_symbol
            ):
                raise ValueError("unsupported spot identity")
        elif self.product != Product.CFD or self.instrument_id != "exness.cfd." + self.asset:
            raise ValueError("unsupported CFD identity")
        return self


class SpecSnapshot(Contract):
    """Candidate facts: null explicitly means UNKNOWN; not an executable InstrumentSpec."""

    alias: InstrumentAlias
    source_id: Label
    observed_at: UTCTime
    spec_version: Digest
    provenance_url: str
    price_tick: PositiveAmount | None = None
    quantity_step: PositiveAmount | None = None
    min_quantity: NonnegativeAmount | None = None
    max_quantity: PositiveAmount | None = None
    contract_size: PositiveAmount | None = None
    quantity_unit: Literal["BASE_UNIT", "CONTRACT", "UNKNOWN"] = "UNKNOWN"
    session: str = "UNKNOWN"
    timezone: Literal["UTC", "UNKNOWN"] = "UNKNOWN"
    trade_status: str = "UNKNOWN"
    unknown_reason: str = "provider fact not supplied"


class DataAvailabilityWindow(Contract):
    provider_published_at: UTCTime | None = None
    original_first_seen_at: UTCTime | None = None
    received_at: UTCTime
    processed_at: UTCTime
    available_at: UTCTime
    historical_close_bound: UTCTime
    basis: Literal["OBSERVED_RECEIPT", "BACKFILL_RECEIPT"]
    limitation: Literal["ORIGINAL_PUBLICATION_UNKNOWN"] = "ORIGINAL_PUBLICATION_UNKNOWN"

    @model_validator(mode="after")
    def chronology(self) -> Self:
        if not self.received_at <= self.processed_at <= self.available_at:
            raise ValueError("invalid receipt chronology")
        if self.historical_close_bound > self.available_at:
            raise ValueError("unfinished candle cannot be available")
        if (
            self.original_first_seen_at is not None
            and self.original_first_seen_at > self.received_at
        ):
            raise ValueError("first seen after receipt")
        return self


class SourceRecord(Contract):
    source_id: Literal["DS-01", "DS-02"]
    source_url: str
    source_hash: Digest
    raw_open: Annotated[int, Field(ge=0)]
    raw_close: Annotated[int, Field(ge=0)]
    timestamp_unit: Literal["MILLISECOND", "MICROSECOND"]
    received_at: UTCTime


class Candle(Contract):
    instrument_id: Label
    symbol: Symbol
    interval: Interval
    venue: Literal["BINANCE"] = "BINANCE"
    product: Literal["SPOT"] = "SPOT"
    base_currency: Literal["BTC", "ETH"]
    quote_currency: Literal["USDT"] = "USDT"
    volume_unit: Literal["BASE_UNIT"] = "BASE_UNIT"
    quote_volume_unit: Literal["USDT"] = "USDT"
    open_at: UTCTime
    end_at: UTCTime
    open: PositiveAmount
    high: PositiveAmount
    low: PositiveAmount
    close: PositiveAmount
    volume: NonnegativeAmount
    quote_volume: NonnegativeAmount
    trades: Annotated[int, Field(ge=0, le=10**12)]
    finalization: Literal["FINAL"] = "FINAL"
    source: SourceRecord
    availability: DataAvailabilityWindow

    @model_validator(mode="after")
    def invariants(self) -> Self:
        if (
            self.instrument_id != "binance.spot." + self.symbol
            or self.symbol != self.base_currency + "USDT"
        ):
            raise ValueError("SPEC_UNIT")
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("OHLC")
        if self.end_at - self.open_at != timedelta(seconds=interval_seconds(self.interval)):
            raise ValueError("SESSION")
        if self.availability.historical_close_bound != self.end_at:
            raise ValueError("invalid historical bound")
        return self

    def require_as_of(self, as_of: datetime) -> None:
        if utc_time(as_of) < self.availability.available_at:
            raise ValueError("LOOKAHEAD_BLOCKED")


class DataQualityFinding(Contract):
    code: QualityCode
    count: Annotated[int, Field(ge=1)] = 1
    first_at: UTCTime | None = None
    last_at: UTCTime | None = None
    detail: str = Field(max_length=512)


class CoverageReport(Contract):
    instrument_id: Label
    interval: Interval
    requested_start: UTCTime
    requested_end: UTCTime
    earliest: UTCTime | None
    latest_end: UTCTime | None
    expected_rows: Annotated[int, Field(ge=0)]
    observed_rows: Annotated[int, Field(ge=0)]
    rejected_rows: Annotated[int, Field(ge=0)]
    findings: tuple[DataQualityFinding, ...]
    status: Literal["PASS", "DEGRADED", "BLOCKED"]

    def require_complete(self) -> None:
        if self.status != "PASS" or self.observed_rows != self.expected_rows:
            raise ValueError("INCOMPLETE_DATA")


class DatasetManifest(Contract):
    dataset_version: Digest
    logical_key: Label
    source: SourceIdentity
    rights: SourceRights
    source_url: str
    source_hash: Digest
    checksum_verified: bool
    raw_bytes: Annotated[int, Field(ge=0)]
    raw_relative_path: str = Field(pattern=r"^bronze/[0-9a-f]{64}\.raw$")
    parquet_hash: Digest
    parquet_bytes: Annotated[int, Field(gt=0)]
    relative_path: str = Field(pattern=r"^partitions/[a-zA-Z0-9_.-]+/[0-9a-f]{64}\.parquet$")
    normalized_hash: Digest
    parser_version: Literal["spot.v1", "spot.v2"] = "spot.v2"
    code_revision: Label
    code_hash: Digest
    parquet_writer: Literal["polars.2.0.0.zstd3"] = "polars.2.0.0.zstd3"
    created_at: UTCTime
    processed_at: UTCTime
    coverage: CoverageReport
    supersedes: Digest | None
    changed_rows: Annotated[int, Field(ge=0)]
    retention_profile: Literal["REVIEW_BEFORE_REMOVAL_NO_AGE_CAP"] = (
        "REVIEW_BEFORE_REMOVAL_NO_AGE_CAP"
    )


class Checkpoint(Contract):
    feed_key: Label
    next_open: UTCTime
    dataset_version: Digest
    recorded_at: UTCTime


# Binance limits are per IP and per service; the archive and REST hosts are separate services.
ProviderHost = Literal["data.binance.vision", "data-api.binance.vision"]
ARCHIVE_HOST: Final = "data.binance.vision"
REST_HOST: Final = "data-api.binance.vision"
PROVIDER_HOSTS: tuple[ProviderHost, ...] = (ARCHIVE_HOST, REST_HOST)


class IngestionEvent(Contract):
    event_id: Label
    feed_key: Label
    observed_at: UTCTime
    state: Literal["FRESH", "STALE", "UNKNOWN", "BLOCKED", "STOPPED"]
    reason: Label
    requests: Annotated[int, Field(ge=0)]
    network_bytes: Annotated[int, Field(ge=0)]
    dataset_version: Digest | None = None
    blocked_until: UTCTime | None = None
    quarantined_source_hash: Digest | None = None
    # Legacy cooldowns have no host and keep blocking every host.
    cooldown_host: ProviderHost | None = None

    @model_validator(mode="after")
    def scoped_cooldown(self) -> Self:
        if self.cooldown_host is not None and self.blocked_until is None:
            raise ValueError("COOLDOWN_HOST_WITHOUT_COOLDOWN")
        return self


class CooldownSpan(Contract):
    """One provider cooldown on one host as it actually lasted: until its expiry or a
    passed probe on that host. A legacy host-less cooldown is reported once per host.
    """

    event_id: Label
    host: ProviderHost
    reason: Label
    start: UTCTime
    end: UTCTime


class CooldownRelease(Contract):
    """Owner decision to end a cooldown early. It grants exactly one probe request."""

    host: ProviderHost
    released_at: UTCTime
    reviewer: Label
    reason: str = Field(pattern=r"^[ -~]{8,512}$")
    released_until: UTCTime
    released_events: tuple[Label, ...] = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def active(self) -> Self:
        if self.released_until <= self.released_at:
            raise ValueError("NO_ACTIVE_COOLDOWN")
        return self


class GapObservation(Contract):
    """One stored provider response whose bars omit the whole reviewed range."""

    dataset_version: Digest
    source_hash: Digest
    received_at: UTCTime


class GapReview(Contract):
    """Explicit reviewed provider gap: permanent coverage evidence, never a filled bar."""

    feed_key: Label
    source_id: Literal["DS-02"] = "DS-02"
    instrument_id: Literal["binance.spot.BTCUSDT", "binance.spot.ETHUSDT"]
    interval: Interval
    gap_start: UTCTime
    gap_end: UTCTime
    reason: Literal["PROVIDER_INTERVAL_ABSENT"] = "PROVIDER_INTERVAL_ABSENT"
    evidence: tuple[GapObservation, ...] = Field(min_length=2, max_length=64)
    reviewer: Label
    reviewed_at: UTCTime

    @model_validator(mode="after")
    def bounded(self) -> Self:
        step = timedelta(seconds=interval_seconds(self.interval))
        symbol = self.instrument_id.rsplit(".", 1)[-1]
        if self.feed_key != f"DS-02.{symbol}.{self.interval}":
            raise ValueError("GAP_FEED_MISMATCH")
        if (
            self.gap_end <= self.gap_start
            or (self.gap_start - EPOCH_UTC) % step
            or (self.gap_end - self.gap_start) % step
            or self.gap_end - self.gap_start > MAX_GAP_INTERVALS * step
        ):
            raise ValueError("GAP_RANGE_INVALID")
        if len({item.dataset_version for item in self.evidence}) != len(self.evidence) or len(
            {item.received_at for item in self.evidence}
        ) != len(self.evidence):
            raise ValueError("GAP_EVIDENCE_NOT_REPEATED")
        if self.reviewed_at < max(item.received_at for item in self.evidence):
            raise ValueError("GAP_REVIEW_BEFORE_EVIDENCE")
        return self

    def overlaps(self, start: datetime, end: datetime) -> bool:
        return self.gap_start < end and start < self.gap_end


class SourceConflict(Contract):
    """The same bar from the archive and from REST with different market values.

    Both facts stay, each under its own source rights; neither is preferred.
    """

    instrument_id: Literal["binance.spot.BTCUSDT", "binance.spot.ETHUSDT"]
    interval: Interval
    open_at: UTCTime
    archive_version: Digest
    archive_source_hash: Digest
    archive_rights_version: Label
    archive_market_hash: Digest
    archive_values: tuple[str, ...]
    rest_version: Digest
    rest_source_hash: Digest
    rest_rights_version: Label
    rest_market_hash: Digest
    rest_values: tuple[str, ...]
    # Point in time: the conflict was knowable only once both bars were available.
    known_at: UTCTime

    @model_validator(mode="after")
    def distinct(self) -> Self:
        if self.archive_market_hash == self.rest_market_hash:
            raise ValueError("IDENTICAL_FACTS_ARE_NOT_A_CONFLICT")
        return self


class SourceComparison(Contract):
    """Deterministic result of comparing every archive and REST version in one bounded range."""

    instrument_id: Literal["binance.spot.BTCUSDT", "binance.spot.ETHUSDT"]
    interval: Interval
    range_start: UTCTime
    range_end: UTCTime
    archive_versions: tuple[Digest, ...]
    rest_versions: tuple[Digest, ...]
    matched: Annotated[int, Field(ge=0)]
    archive_only: Annotated[int, Field(ge=0)]
    rest_only: Annotated[int, Field(ge=0)]
    conflicts: tuple[Digest, ...]
    method: Literal["NUMERIC_MARKET_FIELDS.v1"] = "NUMERIC_MARKET_FIELDS.v1"


def interval_seconds(interval: Interval) -> int:
    return 60 if interval == "1m" else 3600


EPOCH_UTC = datetime(1970, 1, 1, tzinfo=UTC)
# A reviewed gap never spans more than one day of bars; longer absences are outages.
MAX_GAP_INTERVALS = 1440
