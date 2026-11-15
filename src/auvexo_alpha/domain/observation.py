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
    canonical_without_defaults,
    provisional_policy,
    spec_terms_hash,
)
from auvexo_alpha.domain.paper_lifecycle import KillLevel, Release, ReleaseKind, ReleaseState
from auvexo_alpha.domain.research import DataUseClass

Commit = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
LocalDay = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
Count = Annotated[int, Field(ge=0, le=1_000_000)]
Percent = Annotated[Decimal, BeforeValidator(exact_decimal), Field(ge=0, le=100)]
OBSERVATION_INSTRUMENTS = ("binance.spot.BTCUSDT", "binance.spot.ETHUSDT")
OBSERVATION_SYMBOLS = ("BTCUSDT", "ETHUSDT")
CampaignVersion = Literal["paper.observation.v1", "paper.observation.v2"]
# Campaign v1 stays readable and verifiable exactly as recorded but can begin nothing.
V1: CampaignVersion = "paper.observation.v1"
# ADR-032: the only campaign version that can prepare or begin a run.
V2: CampaignVersion = "paper.observation.v2"
SPEC_VERSIONS: dict[str, str] = {V1: "paper.observation.spec.v1", V2: "paper.observation.spec.v2"}
CheckStatus = Literal["PASS", "FAIL", "NOT_CHECKED"]


def _bound_ms(sent_at: datetime, received_at: datetime, server_at: datetime) -> int:
    """Ceiling of the worst absolute local-provider offset over one request interval."""
    delta = max(abs(server_at - sent_at), abs(server_at - received_at))
    return (
        delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds + 999
    ) // 1000


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
    # Added for campaign v2 (ADR-032); omitted from canonical bytes at v1, so every v1
    # configuration keeps its recorded hash.
    version: CampaignVersion = V1

    def canonical_bytes(self) -> bytes:
        return canonical_without_defaults(self, {"version": V1})

    @property
    def is_v2(self) -> bool:
        return self.version == V2

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
                or spec.spec_version != SPEC_VERSIONS[self.version]
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
    return _bound_ms(proof.sent_at, proof.received_at, proof.server_at)


class ObservationClockGate(Contract):
    """OBV2-05 run-start inputs: the Windows Time status and one provider-time proof.

    Only the check outcomes and the digest of the read-only status text are kept; the
    trust decision is recomputed from these values wherever a receipt is evaluated.
    """

    windows_time_hash: Digest
    windows_checks: tuple[tuple[Label, CheckStatus], ...] = Field(max_length=16)
    provider: ObservationClockProof


class ObservationSpecCheck(Contract):
    """OBV2-04: one provider exchangeInfo observation of a symbol's trading terms."""

    symbol: Literal["BTCUSDT", "ETHUSDT"]
    raw_hash: Digest
    sent_at: UTCTime
    received_at: UTCTime
    server_at: UTCTime
    trade_status: Label
    price_tick: PositiveAmount
    quantity_step: PositiveAmount
    min_quantity: PositiveAmount
    max_quantity: PositiveAmount
    min_notional: NonnegativeAmount

    @model_validator(mode="after")
    def chronology(self) -> Self:
        if self.sent_at > self.received_at:
            raise ValueError("OBSERVATION_SPEC_CHECK_INVALID")
        return self

    def bound_ms(self) -> int:
        return _bound_ms(self.sent_at, self.received_at, self.server_at)


class ObservationProvenance(Contract):
    """OBV2-06 scheduler provenance of one run; only VERIFIED can let a night count."""

    status: Literal["VERIFIED", "NOT_SCHEDULED", "UNVERIFIABLE"]
    reason: Label
    evidence_hash: Digest | None = None


class ObservationStandingResume(Contract):
    """OBV2-01 standing owner authority, recorded with START and bound to its campaign.

    It may clear only the K1 that a writer acquisition sets, through the journaled owner
    resume, after a clean previous night. It never lowers K2 or higher.
    """

    authority: Literal["paper.observation.standing_resume.v1"] = (
        "paper.observation.standing_resume.v1"
    )
    scope: Literal["WRITER_ACQUISITION_K1"] = "WRITER_ACQUISITION_K1"
    campaign_hash: Digest
    reviewed_sha: Commit
    start_resume_event_hash: Digest
    valid_through: LocalDay
    owner: Label

    @model_validator(mode="after")
    def owner_only(self) -> Self:
        observation_window(self.valid_through)
        if "agent" in self.owner.lower() or not self.owner.startswith("owner."):
            raise ValueError("OBSERVATION_STANDING_AUTHORITY_INVALID")
        return self


class ObservationStandingResumeUse(Contract):
    """The facts one standing-resume use relied on; journaled with the resume event."""

    authority_hash: Digest
    activation_id: Label
    run_id: Identifier
    local_day: LocalDay
    boundary: Literal["START_RESUME", "PREVIOUS_RECEIPT"]
    boundary_hash: Digest
    boundary_journal_hash: Digest
    roll_event_hash: Digest
    examined_event_hashes: tuple[Digest, ...] = Field(max_length=4096)
    ledger_mismatch_count: Literal[0] = 0
    journal_tail_hash: Digest
    evaluated_at: UTCTime


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
    # Campaign v2 (ADR-032) evidence; omitted from canonical bytes at these v1 defaults.
    provenance: ObservationProvenance | None = None
    clock_gate: ObservationClockGate | None = None
    closing_clock: ObservationClockProof | None = None
    spec_checks: tuple[ObservationSpecCheck, ...] = Field(default=(), max_length=2)
    day_roll_hash: Digest | None = None
    terminal_authorization_count: Count | None = None
    ledger_mismatch_count: Count | None = None

    def canonical_bytes(self) -> bytes:
        return canonical_without_defaults(self, V2_EVIDENCE_DEFAULTS)


V2_EVIDENCE_DEFAULTS: dict[str, object] = {
    "provenance": None,
    "clock_gate": None,
    "closing_clock": None,
    "spec_checks": (),
    "day_roll_hash": None,
    "terminal_authorization_count": None,
    "ledger_mismatch_count": None,
}


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
    # Campaign v2 (ADR-032, OBV2-12) disposition inputs; omitted at v1 defaults.
    campaign_version: CampaignVersion = V1
    provenance_status: Literal["VERIFIED", "NOT_SCHEDULED", "UNVERIFIABLE"] | None = None
    clock_trusted: bool | None = None
    specs_verified: bool | None = None
    day_rolled: bool | None = None
    terminal_authorization_count: Count | None = None
    ledger_mismatch_count: Count | None = None
    # A bar close is used as both sides, so a passed spread gate measured nothing.
    price_basis: Literal["BAR_CLOSE"] | None = None

    def canonical_bytes(self) -> bytes:
        return canonical_without_defaults(
            self,
            {
                "campaign_version": V1,
                "provenance_status": None,
                "clock_trusted": None,
                "specs_verified": None,
                "day_rolled": None,
                "terminal_authorization_count": None,
                "ledger_mismatch_count": None,
                "price_basis": None,
            },
        )

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
    """Remap identity only; every accepted canonical numerical cap remains unchanged.

    Campaign v2 (ADR-032 OBV2-03, OBV2-07) changes exactly three freshness bounds to the
    one-minute bar (market and FX age 60 s, clock offset 2000 ms) and requires store-verified
    inputs against the configuration's pinned specification terms.
    """
    payload = provisional_policy().model_dump()
    payload.update(
        version="paper.observation.policy.v1",
        allowed_accounts=(config.account_ref,),
        allowed_instruments=OBSERVATION_INSTRUMENTS,
        bucket_by_instrument=tuple(
            (instrument, "crypto") for instrument in OBSERVATION_INSTRUMENTS
        ),
    )
    if config.is_v2:
        payload.update(
            version="paper.observation.policy.v2",
            max_market_age_seconds=60,
            max_fx_age_seconds=60,
            max_clock_offset_ms=2000,
            input_trust="STORE_VERIFIED",
            pinned_spec_terms=tuple(spec_terms_hash(spec) for spec in config.specs),
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


def observation_spec(
    symbol: str, *, observed_at: datetime, terms: ObservationSpecCheck | None = None
) -> PaperInstrumentSpec:
    """v1 fixture terms, or (v2) the provider terms of one observation, pinned as given."""
    if symbol not in OBSERVATION_SYMBOLS or (terms is not None and terms.symbol != symbol):
        raise ValueError("OBSERVATION_SYMBOL_INVALID")
    return PaperInstrumentSpec(
        instrument_id="binance.spot." + symbol,
        spec_version=SPEC_VERSIONS[V1 if terms is None else V2],
        fixture_version="paper.observation.fixture.v1",
        base_currency="BTC" if symbol == "BTCUSDT" else "ETH",
        quote_currency="USDT",
        account_currency="USDT",
        contract_multiplier=Decimal("1"),
        price_tick=Decimal("0.01") if terms is None else terms.price_tick,
        quantity_step=Decimal("0.000001") if terms is None else terms.quantity_step,
        min_quantity=Decimal("0.000001") if terms is None else terms.min_quantity,
        max_quantity=Decimal("1000000") if terms is None else terms.max_quantity,
        min_notional=Decimal("1") if terms is None else terms.min_notional,
        margin_fraction=Decimal("0"),
        observed_at=observed_at,
    )


def spec_drift(pinned: PaperInstrumentSpec, check: ObservationSpecCheck) -> tuple[str, ...]:
    """OBV2-04: the pinned terms that the provider no longer states; empty when unchanged."""
    if pinned.instrument_id != "binance.spot." + check.symbol:
        return ("instrument",)
    return tuple(
        name
        for name, drifted in (
            ("price_tick", pinned.price_tick != check.price_tick),
            ("quantity_step", pinned.quantity_step != check.quantity_step),
            ("min_quantity", pinned.min_quantity != check.min_quantity),
            ("min_notional", pinned.min_notional != check.min_notional),
            ("trade_status", check.trade_status != "TRADING"),
        )
        if drifted
    )


def observed_spec(pinned: PaperInstrumentSpec, check: ObservationSpecCheck) -> PaperInstrumentSpec:
    """The pinned specification, observed at provider time; a drifted one is never used."""
    if spec_drift(pinned, check):
        raise ValueError("SPEC_DRIFT")
    return PaperInstrumentSpec.model_validate(
        pinned.model_dump() | {"observed_at": check.server_at}
    )


def pinned_spec(config: ObservationConfig, spec: PaperInstrumentSpec) -> bool:
    """v1: one of the configured fixtures. v2: a configured pin, observed at any instant."""
    if not config.is_v2:
        return spec in config.specs
    return any(
        pinned.instrument_id == spec.instrument_id
        and spec_terms_hash(pinned) == spec_terms_hash(spec)
        for pinned in config.specs
    )


def observation_market(fact: ObservationFact, config: ObservationConfig) -> PaperMarketSnapshot:
    """Actual bar end remains as_of; identity USDT conversion asserts no USD peg.

    Campaign v2 states the BAR_CLOSE basis: one close as both sides, zero spread by
    construction. v1 snapshots keep their recorded (QUOTE default) form and hash.
    """
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
        price_basis="BAR_CLOSE" if config.is_v2 else "QUOTE",
    )
