"""Nonproduction research contracts. None grants execution or promotion authority."""

from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from auvexo_alpha.domain.contracts import (
    Contract,
    Digest,
    Label,
    NonnegativeAmount,
    PositiveAmount,
    UTCTime,
    utc_time,
)
from auvexo_alpha.domain.market_data import Candle, DatasetManifest
from auvexo_alpha.domain.research_gaps import VenueUnavailable, coverage_disposition


class DataUseClass(StrEnum):
    ENGINEERING_ONLY = "ENGINEERING_ONLY"
    PERSONAL_RESEARCH = "PERSONAL_RESEARCH"
    PROMOTION_ELIGIBLE = "PROMOTION_ELIGIBLE"
    BLOCKED = "BLOCKED"


RESTRICTION = {
    DataUseClass.PROMOTION_ELIGIBLE: 0,
    DataUseClass.PERSONAL_RESEARCH: 1,
    DataUseClass.ENGINEERING_ONLY: 2,
    DataUseClass.BLOCKED: 3,
}


def inherited_use(inputs: tuple[DataUseClass, ...]) -> DataUseClass:
    return max(inputs, key=RESTRICTION.__getitem__) if inputs else DataUseClass.BLOCKED


class PriceAvailability(Contract):
    name: Literal["PRICE_CLOSE_PLUS_CAUSAL_LAG"] = "PRICE_CLOSE_PLUS_CAUSAL_LAG"
    version: Literal["price-lag.v1"] = "price-lag.v1"
    lag_microseconds: Annotated[int, Field(gt=0, le=86_400_000_000)]
    data_kind: Literal["FINALIZED_SPOT_PRICE"] = "FINALIZED_SPOT_PRICE"

    def available_at(self, bar: Candle) -> datetime:
        if not isinstance(bar, Candle):
            raise ValueError("PRICE_POLICY_CANNOT_WRAP_VINTAGE")
        return bar.end_at + timedelta(microseconds=self.lag_microseconds)

    def require(self, bar: Candle, decision_at: datetime) -> None:
        if utc_time(decision_at) < self.available_at(bar):
            raise ValueError("RESEARCH_LOOKAHEAD_BLOCKED")


class ResearchInput(Contract):
    manifest: DatasetManifest
    manifest_hash: Digest
    availability: PriceAvailability
    classification: DataUseClass
    intended_use: Literal["ENGINEERING", "PERSONAL_NONPRODUCTION", "PROMOTION"]
    evaluated_at: UTCTime
    derived_from: tuple[Digest, ...]
    evidence_refs: tuple[str, ...]
    reasons: tuple[str, ...]
    outages: tuple[VenueUnavailable, ...] = ()

    @model_validator(mode="after")
    def bound_hash(self) -> Self:
        if self.manifest_hash != self.manifest.content_hash():
            raise ValueError("RESEARCH_MANIFEST_HASH_MISMATCH")
        return self


def classify_manifest(
    manifest: DatasetManifest,
    now: datetime,
    availability: PriceAvailability,
    intended_use: Literal["ENGINEERING", "PERSONAL_NONPRODUCTION", "PROMOTION"] = (
        "PERSONAL_NONPRODUCTION"
    ),
    instrument: str | None = None,
    parents: tuple[ResearchInput, ...] = (),
    outages: tuple[VenueUnavailable, ...] = (),
) -> ResearchInput:
    """Artifact verification is additionally mandatory at the infrastructure read boundary."""
    reasons = []
    m = manifest
    endpoint = urlsplit(m.source_url)
    expected_host = (
        "data.binance.vision" if m.source.source_id == "DS-01" else "data-api.binance.vision"
    )
    expected_path = "/data/spot/" if m.source.source_id == "DS-01" else "/api/v3/klines"
    if (
        endpoint.scheme != "https"
        or endpoint.hostname != expected_host
        or not endpoint.path.startswith(expected_path)
        or endpoint.username
        or endpoint.password
        or endpoint.port
    ):
        reasons.append("UNQUALIFIED_SOURCE_ENDPOINT")
    if (
        m.source.source_id not in ("DS-01", "DS-02")
        or m.source.provider != "BINANCE"
        or m.source.family != ("SPOT_ARCHIVE" if m.source.source_id == "DS-01" else "SPOT_REST")
        or m.coverage.instrument_id not in ("binance.spot.BTCUSDT", "binance.spot.ETHUSDT")
        or (instrument is not None and instrument != m.coverage.instrument_id)
        or m.rights.source_id != m.source.source_id
        or m.source.rights_version != m.rights.version
    ):
        reasons.append("UNQUALIFIED_SOURCE_OR_CROSS_PRODUCT_TRANSFER")
    accepted_hashes = {
        "DS-01": {
            "dcf358e9d18f598a7a635fac80f6e643fa24a0e111a4d39bda47f1e246b31eb1",
            "99c4921dbe023cd68c1a447775707d621453cc78aec6ac0bfe2e6c06a5114ee0",
        },
        "DS-02": {"bf4879710c904b991848972ec4818ba2cf9e4ce314c09adae84fa2750d3477f7"},
    }
    if m.rights.terms_hash not in accepted_hashes.get(m.source.source_id, set()):
        reasons.append("UNKNOWN_RIGHTS_SNAPSHOT")
    try:
        m.rights.require_research(now)
    except ValueError:
        reasons.append("EXPIRED_RIGHTS_OR_INCOMPLETE_DATA")
    disposition = coverage_disposition(m, outages)
    if disposition == "UNKNOWN_GAP_BLOCKED":
        reasons.append("UNKNOWN_OR_UNEXPLAINED_QUALITY_FINDINGS")
    if (
        m.processed_at > now
        or m.created_at > m.processed_at
        or m.coverage.requested_end > m.created_at
    ):
        reasons.append("FUTURE_OR_INVALID_RECEIPT")
    if m.source.source_id == "DS-01" and not m.checksum_verified:
        reasons.append("ARCHIVE_CHECKSUM_REQUIRED")
    if intended_use == "PROMOTION":
        reasons.append("CURRENT_SOURCES_HAVE_NO_PRODUCTION_ENTITLEMENT")
    for parent in parents:
        current = classify_manifest(
            parent.manifest, now, parent.availability, parent.intended_use, outages=parent.outages
        )
        if current.classification == DataUseClass.BLOCKED:
            reasons.append("BLOCKED_DERIVED_LINEAGE")
    own = (
        DataUseClass.ENGINEERING_ONLY
        if intended_use == "ENGINEERING"
        else (DataUseClass.PERSONAL_RESEARCH)
    )
    result = (
        DataUseClass.BLOCKED
        if reasons
        else inherited_use((own, *(p.classification for p in parents)))
    )
    return ResearchInput(
        manifest=m,
        manifest_hash=m.content_hash(),
        availability=availability,
        classification=result,
        intended_use=intended_use,
        evaluated_at=now,
        derived_from=tuple(p.manifest_hash for p in parents),
        evidence_refs=("acceptance.bdae1a1.DS01-02.spot", *m.rights.evidence_urls),
        reasons=tuple(reasons),
        outages=tuple(o for o in outages if o.source_manifest == m.dataset_version),
    )


class CostModel(Contract):
    fee_bps: NonnegativeAmount = Decimal("10")
    spread_bps: NonnegativeAmount = Decimal("5")
    slippage_bps: NonnegativeAmount = Decimal("2")
    multiplier: PositiveAmount = Decimal("1")
    latency_microseconds: Annotated[int, Field(ge=0, le=86_400_000_000)] = 1_000_000
    label: Literal["ASSUMED_NO_HISTORICAL_BID_ASK"] = "ASSUMED_NO_HISTORICAL_BID_ASK"
    financing: Literal["UNLEVERED_SPOT_NO_SWAP_OR_FUNDING"] = "UNLEVERED_SPOT_NO_SWAP_OR_FUNDING"

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if max(self.fee_bps, self.spread_bps, self.slippage_bps) * self.multiplier > 1000:
            raise ValueError("UNSUPPORTED_COST_SCALE")
        return self


class StrategyConfig(Contract):
    family: Literal["NO_TRADE", "PASSIVE", "FIXED_RULE", "BREAKOUT", "MEAN_REVERSION"]
    lookback: Annotated[int, Field(ge=2, le=168)] = 24
    holding_bars: Annotated[int, Field(ge=1, le=168)] = 24
    exposure_fraction: PositiveAmount
    stop_fraction: PositiveAmount
    target_fraction: PositiveAmount
    deviation_fraction: PositiveAmount
    entry_fill_fraction: PositiveAmount

    @model_validator(mode="after")
    def unlevered(self) -> Self:
        if (
            max(self.exposure_fraction, self.entry_fill_fraction) > 1
            or max(self.stop_fraction, self.target_fraction, self.deviation_fraction) >= 1
        ):
            raise ValueError("INVALID_UNLEVERED_SPOT_CONFIGURATION")
        return self


class ResearchSplit(Contract):
    train_start: UTCTime
    train_end: UTCTime
    validation_start: UTCTime
    validation_end: UTCTime
    oos_start: UTCTime
    oos_end: UTCTime
    purge_embargo_seconds: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def separation(self) -> Self:
        gap = timedelta(seconds=self.purge_embargo_seconds)
        if not (
            self.train_start < self.train_end
            and self.train_end + gap <= self.validation_start < self.validation_end
            and self.validation_end + gap <= self.oos_start < self.oos_end
        ):
            raise ValueError("CHRONOLOGICAL_PURGE_EMBARGO_REQUIRED")
        return self


class StudyManifest(Contract):
    study_id: Label
    version: Label
    registered_at: UTCTime
    instrument: Literal["binance.spot.BTCUSDT", "binance.spot.ETHUSDT"]
    product: Literal["SPOT"] = "SPOT"
    timeframe: Literal["1h"] = "1h"
    hypotheses: tuple[str, ...] = Field(min_length=2)
    mechanism_and_falsification: str = Field(min_length=20)
    inputs: tuple[ResearchInput, ...] = Field(min_length=1, max_length=128)
    availability: PriceAvailability
    configs: tuple[StrategyConfig, ...] = Field(min_length=4, max_length=12)
    costs: CostModel
    stress_multipliers: tuple[PositiveAmount, ...]
    split: ResearchSplit
    seed: Annotated[int, Field(ge=0, le=2**32 - 1)]
    code_revision: Label
    code_hash: Digest
    dependency_hash: Digest
    data_plan_v1_hash: Digest
    data_plan_v2_hash: Digest
    feature_version: Literal["causal-price.v1"] = "causal-price.v1"
    baseline_families: tuple[str, ...]
    parameter_budget: Annotated[int, Field(ge=1, le=12)]
    trial_budget: Annotated[int, Field(ge=1, le=128)]
    max_drawdown: PositiveAmount
    min_closed_trades: Literal[100] = 100
    min_oos_months: Literal[6] = 6
    bootstrap_samples: Annotated[int, Field(ge=1000, le=10000)] = 2000
    bootstrap_block_days: Annotated[int, Field(ge=7, le=90)] = 14
    comparisons: Annotated[int, Field(ge=4, le=100)] = 4
    worker_count: Literal[1] = 1
    cpu_threads: Literal[2] = 2
    ram_target_bytes: Literal[2_000_000_000] = 2_000_000_000
    checkpoint_seconds: Literal[1800] = 1800
    holdout_claim: Literal["FRESH_PREREGISTERED"] = "FRESH_PREREGISTERED"

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if len(self.configs) > self.parameter_budget or self.max_drawdown >= 1:
            raise ValueError("STUDY_BUDGET")
        if self.split.purge_embargo_seconds < max(c.holding_bars for c in self.configs) * 3600:
            raise ValueError("EMBARGO_SHORTER_THAN_HOLDING_HORIZON")
        for item in self.inputs:
            if item.manifest.coverage.interval != self.timeframe:
                raise ValueError("STUDY_TIMEFRAME_MISMATCH")
            current = classify_manifest(
                item.manifest,
                self.registered_at,
                item.availability,
                item.intended_use,
                self.instrument,
                outages=item.outages,
            )
            if (
                item.classification != DataUseClass.PERSONAL_RESEARCH
                or current.classification != item.classification
                or item.availability != self.availability
            ):
                raise ValueError("STUDY_INPUT_BLOCKED")
        return self
