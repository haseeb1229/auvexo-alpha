"""Immutable nonproduction observation evidence; objects alone cannot grant day credit."""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Annotated, Literal, Self
from uuid import NAMESPACE_URL, uuid5

from pydantic import BeforeValidator, Field, model_validator

from auvexo_alpha.domain.contracts import (
    Contract,
    Digest,
    Identifier,
    Label,
    Mode,
    NonnegativeAmount,
    PositiveAmount,
    Product,
    UTCTime,
    Venue,
    exact_decimal,
)
from auvexo_alpha.domain.market_data import Candle, DatasetManifest, SourceIdentity, SourceRights
from auvexo_alpha.domain.paper import (
    PaperAccountSnapshot,
    PaperAuthorization,
    PaperDecision,
    PaperInstrumentSpec,
    PaperIntent,
    PaperMarketSnapshot,
    PaperPolicy,
    PaperReservation,
    provisional_policy,
)
from auvexo_alpha.domain.paper_lifecycle import KillLevel, Release, ReleaseKind, ReleaseState
from auvexo_alpha.domain.research import DataUseClass

Commit = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
LocalDay = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
Count = Annotated[int, Field(ge=0, le=1_000_000)]
Percent = Annotated[Decimal, BeforeValidator(exact_decimal), Field(ge=0, le=100)]
OBSERVATION_INSTRUMENTS = ("binance.spot.BTCUSDT", "binance.spot.ETHUSDT")
OBSERVATION_SYMBOLS = ("BTCUSDT", "ETHUSDT")


def observation_window(local_day: date | str) -> tuple[datetime, datetime]:
    """Pakistan 21:00-22:00 is UTC 16:00-17:00 on the same calendar date."""
    day = date.fromisoformat(local_day) if isinstance(local_day, str) else local_day
    if type(day) is not date or (isinstance(local_day, str) and day.isoformat() != local_day):
        raise ValueError("OBSERVATION_DATE_INVALID")
    start = datetime(day.year, day.month, day.day, 16, tzinfo=UTC)
    return start, start + timedelta(hours=1)


class ObservationConfig(Contract):
    campaign_id: Label
    git_revision: Commit
    rights: SourceRights
    source: SourceIdentity
    specs: tuple[PaperInstrumentSpec, ...] = Field(min_length=2, max_length=2)
    account_ref: Literal["paper.observation"] = "paper.observation"
    fixture_version: Literal["paper.observation.fixture.v1"] = "paper.observation.fixture.v1"
    mode: Literal[Mode.PAPER] = Mode.PAPER
    evidence_use: Literal[DataUseClass.ENGINEERING_ONLY] = DataUseClass.ENGINEERING_ONLY
    schedule_id: Literal["paper-observation-2100-pkt-v1"] = "paper-observation-2100-pkt-v1"
    max_start_lateness_seconds: Literal[15] = 15
    minimum_paired_observations: Literal[50] = 50
    minimum_span_seconds: Literal[3000] = 3000
    max_gap_seconds: Literal[120] = 120
    shutdown_grace_seconds: Literal[30] = 30
    max_fixture_risk_fraction: NonnegativeAmount = Decimal("0.0005")

    @model_validator(mode="after")
    def fixed_boundary(self) -> Self:
        if (
            self.source.source_id != "DS-02"
            or self.source.provider != "BINANCE"
            or self.source.family != "SPOT_REST"
            or self.source.endpoint != "https://data-api.binance.vision"
            or self.rights.source_id != "DS-02"
            or self.source.rights_version != self.rights.version
            or self.rights.permitted_use != "PERSONAL_NONPRODUCTION_RESEARCH"
            or self.rights.redistribution != "NOT_AUTHORIZED"
            or self.rights.review_due <= self.rights.reviewed_at
            or tuple(spec.instrument_id for spec in self.specs) != OBSERVATION_INSTRUMENTS
            or self.max_fixture_risk_fraction <= 0
            or self.max_fixture_risk_fraction > Decimal("0.0005")
            or any(
                spec.origin != "PAPER_FIXTURE"
                or spec.fixture_version != self.fixture_version
                or spec.spec_version != "paper.observation.spec.v1"
                or spec.base_currency
                != ("BTC" if spec.instrument_id.endswith("BTCUSDT") else "ETH")
                or spec.venue != Venue.BINANCE
                or spec.product != Product.SPOT
                or spec.quote_currency != "USDT"
                or spec.account_currency != "USDT"
                or spec.contract_multiplier != Decimal("1")
                or spec.fill_semantics != "LINEAR_LONG_SPOT"
                for spec in self.specs
            )
        ):
            raise ValueError("OBSERVATION_SCOPE_INVALID")
        return self


class ObservationClockProof(Contract):
    """Retained public provider-time response and local request interval."""

    source_url: Literal["https://data-api.binance.vision/api/v3/time"]
    raw_json: Annotated[str, Field(min_length=1, max_length=512)]
    raw_hash: Digest
    sent_at: UTCTime
    received_at: UTCTime
    server_at: UTCTime

    @model_validator(mode="after")
    def response_binding(self) -> Self:
        raw = self.raw_json.encode("ascii")
        data = json.loads(self.raw_json)
        if (
            not isinstance(data, dict)
            or tuple(data) != ("serverTime",)
            or type(data["serverTime"]) is not int
            or data["serverTime"] < 0
            or data["serverTime"] > 253402300799999
            or self.sent_at > self.received_at
            or sha256(raw).hexdigest() != self.raw_hash
            or datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=data["serverTime"])
            != self.server_at
        ):
            raise ValueError("OBSERVATION_CLOCK_PROOF_INVALID")
        return self


def observation_clock_bound_ms(proof: ObservationClockProof) -> int:
    """Ceiling of the worst absolute offset over the measured request interval."""
    delta = max(abs(proof.server_at - proof.sent_at), abs(proof.server_at - proof.received_at))
    return (
        delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds + 999
    ) // 1000


class ObservationFact(Contract):
    observation_id: Identifier
    candle: Candle
    manifest: DatasetManifest
    clock: ObservationClockProof


class ObservationResources(Contract):
    observed_at: UTCTime
    available_ram_bytes: Annotated[int, Field(ge=0)]
    cpu_percent: Percent
    cpu_high_for_seconds: Count


class ObservationProposalTrace(Contract):
    proposal_id: Identifier
    source_observation_hash: Digest
    intent: PaperIntent
    decision: PaperDecision
    account_before: PaperAccountSnapshot
    market: PaperMarketSnapshot
    spec: PaperInstrumentSpec
    release: Release
    authorization: PaperAuthorization | None = None
    reservation: PaperReservation | None = None
    prior_reservations: tuple[PaperReservation, ...] = ()
    journal_event_hash: Digest


class ObservationSimulationTrace(Contract):
    label: Literal["SIMULATED"] = "SIMULATED"
    version: Literal["paper.observation.simulator.v1"] = "paper.observation.simulator.v1"
    intent_hash: Digest
    proposal_source_hash: Digest
    fill_source_hash: Digest
    truth_event_id: Identifier
    quantity: PositiveAmount
    price: PositiveAmount
    observed_at: UTCTime


class ObservationRunEvidence(Contract):
    run_id: Identifier
    campaign_id: Label
    local_day: LocalDay
    kind: Literal["NON_COUNTING", "SCHEDULED"] = "NON_COUNTING"
    scheduled_at: UTCTime
    started_at: UTCTime
    ended_at: UTCTime
    config_hash: Digest
    facts: tuple[ObservationFact, ...] = Field(default=(), max_length=240)
    traces: tuple[ObservationProposalTrace, ...] = Field(default=(), max_length=240)
    final_account: PaperAccountSnapshot
    truth_cursor: Count
    journal_tail_hash: Digest
    reservation_hashes: tuple[Digest, ...] = ()
    outbox_hashes: tuple[Digest, ...] = ()
    fill_hashes: tuple[Digest, ...] = ()
    simulation_traces: tuple[ObservationSimulationTrace, ...] = ()
    unknown_order_refs: tuple[Label, ...] = ()
    mismatch_refs: tuple[Label, ...] = ()
    operational_reasons: tuple[Label, ...] = ()
    resource_snapshots: tuple[ObservationResources, ...] = Field(default=(), max_length=240)


class ObservationVerification(Contract):
    """Replay/source witness, independently derived at the persistence boundary.

    This caller-constructible value has no qualification authority on its own.
    The observation store must verify it from immutable source, journal and trace rows.
    """

    run_evidence_hash: Digest
    source_fact_hashes: tuple[Digest, ...]
    trace_hashes: tuple[Digest, ...]
    journal_tail_hash: Digest
    replay_journal_hash: Digest
    replay_intent_hashes: tuple[Digest, ...]
    replay_decision_hashes: tuple[Digest, ...]
    reservation_hashes: tuple[Digest, ...]
    outbox_hashes: tuple[Digest, ...]
    fill_hashes: tuple[Digest, ...]
    privilege_identity_hash: Digest


class ObservationDayReceipt(Contract):
    run_id: Identifier
    campaign_id: Label
    local_day: LocalDay
    kind: Literal["NON_COUNTING", "SCHEDULED"]
    config_hash: Digest
    git_revision: Commit
    policy_hash: Digest
    spec_hashes: tuple[Digest, ...]
    rights_hash: Digest
    source_hash: Digest
    schedule_id: Label
    scheduled_at: UTCTime
    started_at: UTCTime
    ended_at: UTCTime
    evidence_hash: Digest
    verification_hash: Digest
    status: Literal["PASS", "INCOMPLETE"]
    reasons: tuple[Label, ...]
    operational_reasons: tuple[Label, ...]
    first_observation_at: UTCTime | None
    last_observation_at: UTCTime | None
    paired_observations: Count
    max_gap_seconds: Count
    proposal_count: Count
    decision_count: Count
    authorization_count: Count
    denial_count: Count
    reservation_count: Count
    outbox_count: Count
    fill_count: Count
    truth_cursor: Count
    journal_tail_hash: Digest
    final_account_hash: Digest
    final_kill: KillLevel
    final_reconciled: bool
    position_hashes: tuple[Digest, ...]
    resource_hashes: tuple[Digest, ...]
    resources: tuple[ObservationResources, ...]

    @model_validator(mode="after")
    def disposition(self) -> Self:
        observation_window(self.local_day)
        if (self.status == "PASS") != (not self.reasons):
            raise ValueError("OBSERVATION_RECEIPT_DISPOSITION_INVALID")
        return self


class ObservationLedgerProof(Contract):
    """Server-verified unique scheduled receipts; never an imported JSON counter."""

    campaign_id: Label
    activated_at: UTCTime
    first_eligible_day: LocalDay
    verified_at: UTCTime
    receipt_hashes: tuple[Digest, ...]
    ledger_tail_hash: Digest


class ObservationCalendarSummary(Contract):
    campaign_id: Label
    status: Literal["OPEN", "PASS", "INVALID"]
    reasons: tuple[Label, ...]
    qualified_dates: tuple[LocalDay, ...]
    qualified_count: Count
    calendar_span_days: Count
    observation_started: bool


def observation_policy(config: ObservationConfig) -> PaperPolicy:
    """Remap identity only; every accepted canonical numerical cap remains unchanged."""
    payload = provisional_policy().model_dump()
    payload.update(
        version="paper.observation.policy.v1",
        allowed_accounts=(config.account_ref,),
        allowed_instruments=OBSERVATION_INSTRUMENTS,
        bucket_by_instrument=tuple(
            (instrument, "crypto") for instrument in OBSERVATION_INSTRUMENTS
        ),
    )
    return PaperPolicy.model_validate(payload)


def observation_release(config: ObservationConfig, *, now: datetime) -> Release:
    return Release(
        release_id=config.fixture_version,
        kind=ReleaseKind.TEST_ONLY,
        state=ReleaseState.PAPER,
        code_hash=config.content_hash(),
        config_hash=config.content_hash(),
        data_hash=config.source.content_hash(),
        evidence_hash=config.rights.content_hash(),
        allowed_modes=(Mode.PAPER,),
        approved_by=("owner.observation.fixture",),
        created_at=now,
        data_use=DataUseClass.ENGINEERING_ONLY,
        independent_evidence=False,
        fixture_namespace="PAPER_QUALIFICATION_FIXTURE",
    )


def observation_spec(symbol: str, *, observed_at: datetime) -> PaperInstrumentSpec:
    if symbol not in OBSERVATION_SYMBOLS:
        raise ValueError("OBSERVATION_SYMBOL_INVALID")
    return PaperInstrumentSpec(
        instrument_id="binance.spot." + symbol,
        spec_version="paper.observation.spec.v1",
        fixture_version="paper.observation.fixture.v1",
        base_currency="BTC" if symbol == "BTCUSDT" else "ETH",
        quote_currency="USDT",
        account_currency="USDT",
        contract_multiplier=Decimal("1"),
        price_tick=Decimal("0.01"),
        quantity_step=Decimal("0.000001"),
        min_quantity=Decimal("0.000001"),
        max_quantity=Decimal("1000000"),
        min_notional=Decimal("1"),
        margin_fraction=Decimal("0"),
        observed_at=observed_at,
    )


def observation_market(fact: ObservationFact) -> PaperMarketSnapshot:
    """Actual bar end remains as_of; identity USDT conversion asserts no USD peg."""
    candle = fact.candle
    if (
        candle.instrument_id not in OBSERVATION_INSTRUMENTS
        or candle.interval != "1m"
        or candle.source.source_id != "DS-02"
        or fact.manifest.source.source_id != "DS-02"
        or fact.manifest.source.family != "SPOT_REST"
        or fact.manifest.source_hash != candle.source.source_hash
        or fact.manifest.normalized_hash != sha256(candle.canonical_bytes()).hexdigest()
    ):
        raise ValueError("OBSERVATION_MARKET_SOURCE_INVALID")
    return PaperMarketSnapshot(
        snapshot_id=uuid5(NAMESPACE_URL, "observation.market." + fact.content_hash()),
        instrument_id=candle.instrument_id,
        as_of=candle.end_at,
        available_at=candle.availability.available_at,
        bid=candle.close,
        ask=candle.close,
        adverse_fx=Decimal("1"),
        fx_as_of=candle.end_at,
        health="HEALTHY",
        session_open=True,
        clock_offset_ms=min(observation_clock_bound_ms(fact.clock), 86_400_000),
    )
