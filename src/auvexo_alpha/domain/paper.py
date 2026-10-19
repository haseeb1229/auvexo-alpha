"""Strict immutable virtual PAPER contracts, with no broker account or credentials."""

import hashlib
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BeforeValidator, Field, TypeAdapter, model_validator

from auvexo_alpha.domain.contracts import (
    Contract,
    Currency,
    Digest,
    Identifier,
    Label,
    Mode,
    MoneyAction,
    NonnegativeAmount,
    PositiveAmount,
    Product,
    UTCTime,
    Venue,
    exact_decimal,
    uuid_value,
)
from auvexo_alpha.domain.paper_lifecycle import KillLevel

SignedAmount = Annotated[Decimal, BeforeValidator(exact_decimal)]
Count = Annotated[int, Field(ge=0, le=1_000_000)]
Fraction = Annotated[Decimal, BeforeValidator(exact_decimal), Field(ge=0, le=1)]
_ACCOUNT_LABEL: TypeAdapter[str] = TypeAdapter(Label)


def paper_position_ref(account_ref: str, intent_id: UUID) -> str:
    """A new OPEN's deterministic account-scoped identity; never a merge target."""
    account_ref = _ACCOUNT_LABEL.validate_python(account_ref, strict=True)
    if not account_ref.startswith("paper."):
        raise ValueError("VIRTUAL_PAPER_IDENTITY_REQUIRED")
    identity = uuid_value(intent_id)
    return (
        "position."
        + hashlib.sha256((account_ref + ":" + str(identity)).encode("ascii")).hexdigest()
    )


class PaperCandidate(Contract):
    """Proposal only; neither a candidate lifecycle registration nor authority."""

    candidate_id: Identifier
    fixture_evidence_hash: Digest
    instrument_id: Label
    side: Literal["BUY", "SELL"]
    quantity: PositiveAmount
    entry: PositiveAmount
    stop: PositiveAmount
    created_at: UTCTime


class PaperIntent(Contract):
    intent_id: Identifier
    logical_key: Label
    mode: Mode = Mode.PAPER
    account_ref: Label
    instrument_id: Label
    venue: Venue = Venue.BINANCE
    product: Product = Product.SPOT
    action: MoneyAction = MoneyAction.OPEN
    side: Literal["BUY", "SELL"] = "BUY"
    quantity: PositiveAmount
    entry: PositiveAmount
    stop: PositiveAmount
    release_hash: Digest
    spec_hash: Digest
    snapshot_hash: Digest
    account_snapshot_hash: Digest
    policy_hash: Digest
    created_at: UTCTime
    expires_at: UTCTime
    position_ref: Label | None = None
    target_intent_ref: Identifier | None = None

    @model_validator(mode="after")
    def chronology(self) -> Self:
        if self.expires_at <= self.created_at:
            raise ValueError("INTENT_EXPIRY_INVALID")
        if self.action == MoneyAction.OPEN and self.position_ref is not None:
            raise ValueError("OPEN_REQUIRES_NEW_POSITION")
        return self


class PaperInstrumentSpec(Contract):
    instrument_id: Label
    spec_version: Label
    origin: Literal["PAPER_FIXTURE"] = "PAPER_FIXTURE"
    fixture_version: Label
    venue: Venue = Venue.BINANCE
    product: Product = Product.SPOT
    base_currency: Currency
    quote_currency: Currency
    account_currency: Currency
    contract_multiplier: PositiveAmount
    price_tick: PositiveAmount
    quantity_step: PositiveAmount
    min_quantity: PositiveAmount
    max_quantity: PositiveAmount
    min_notional: NonnegativeAmount
    margin_fraction: Fraction
    fill_semantics: Literal["LINEAR_LONG_SPOT", "UNKNOWN"] = "LINEAR_LONG_SPOT"
    observed_at: UTCTime

    @model_validator(mode="after")
    def bounds(self) -> Self:
        if self.max_quantity < self.min_quantity or self.base_currency == self.quote_currency:
            raise ValueError("SPEC_BOUNDS_INVALID")
        return self


class PaperMarketSnapshot(Contract):
    snapshot_id: Identifier
    instrument_id: Label
    as_of: UTCTime
    available_at: UTCTime
    bid: PositiveAmount
    ask: PositiveAmount
    adverse_fx: PositiveAmount | None
    fx_as_of: UTCTime | None
    health: Literal["HEALTHY", "STALE", "UNKNOWN", "GAPPED"]
    session_open: bool
    clock_offset_ms: Annotated[int, Field(ge=-86_400_000, le=86_400_000)]

    @model_validator(mode="after")
    def chronology(self) -> Self:
        if self.as_of > self.available_at or self.bid > self.ask:
            raise ValueError("MARKET_SNAPSHOT_INVALID")
        return self


class PaperPosition(Contract):
    position_ref: Label
    instrument_id: Label
    bucket: Label
    quantity: PositiveAmount
    entry_price: PositiveAmount
    mark_price: PositiveAmount
    mark_as_of: UTCTime | None = None
    fx_as_of: UTCTime | None = None
    mark_available_at: UTCTime | None = None
    mark_snapshot_hash: Digest | None = None
    mark_fact_hash: Digest | None = None
    stop_price: PositiveAmount
    multiplier: PositiveAmount = Decimal("1")
    adverse_fx: PositiveAmount = Decimal("1")
    modeled_costs: NonnegativeAmount = Decimal("0")
    margin_used: NonnegativeAmount = Decimal("0")


class PaperMarkHealth(Contract):
    """Time-derived readiness evidence, separate from immutable valuation fields."""

    position_ref: Label
    state: Literal["FRESH", "STALE", "UNPRICEABLE"]
    fact_hash: Digest | None = None
    snapshot_hash: Digest | None = None
    observed_at: UTCTime | None = None
    available_at: UTCTime | None = None
    fx_as_of: UTCTime | None = None


class PaperAccountSnapshot(Contract):
    account_ref: Label
    epoch: Count
    snapshot_id: Identifier
    as_of: UTCTime
    reconciled_at: UTCTime
    day_start_at: UTCTime
    currency: Currency = "USD"
    cash: NonnegativeAmount
    equity: NonnegativeAmount
    high_water_equity: NonnegativeAmount
    day_start_equity: NonnegativeAmount
    day_net_flows: SignedAmount = Decimal("0")
    net_flows_since_high_water: SignedAmount = Decimal("0")
    positions: tuple[PaperPosition, ...] = ()
    reconciled: bool = False
    unknown_orders: bool = False
    journal_healthy: bool = True
    kill: KillLevel = KillLevel.K1
    prior_logical_keys: tuple[Label, ...] = ()
    prior_intent_ids: tuple[Identifier, ...] = ()
    recent_intent_times: tuple[UTCTime, ...] = ()

    @model_validator(mode="after")
    def virtual_identity(self) -> Self:
        if not self.account_ref.startswith("paper."):
            raise ValueError("VIRTUAL_PAPER_IDENTITY_REQUIRED")
        if (
            self.day_start_at.hour
            or self.day_start_at.minute
            or self.day_start_at.second
            or self.day_start_at.microsecond
            or self.day_start_at > self.as_of
            or self.reconciled_at > self.as_of
        ):
            raise ValueError("ACCOUNT_CHRONOLOGY_INVALID")
        refs = [position.position_ref for position in self.positions]
        if len(refs) != len(set(refs)):
            raise ValueError("DUPLICATE_POSITION")
        if len(self.prior_intent_ids) != len(set(self.prior_intent_ids)):
            raise ValueError("DUPLICATE_PRIOR_INTENT_ID")
        return self


class PaperPolicy(Contract):
    version: Label
    allowed_instruments: tuple[Label, ...]
    allowed_accounts: tuple[Label, ...]
    bucket_by_instrument: tuple[tuple[Label, Label], ...]
    allowed_venues: tuple[Venue, ...]
    allowed_products: tuple[Product, ...]
    max_trade_risk_fraction: Fraction
    max_total_risk_fraction: Fraction
    max_bucket_risk_fraction: Fraction
    max_asset_risk_fraction: Fraction
    max_daily_loss_fraction: Fraction
    max_drawdown_fraction: Fraction
    max_positions: Count
    max_gross_fraction: NonnegativeAmount
    max_net_fraction: NonnegativeAmount
    max_margin_fraction: Fraction
    max_intents_per_minute: Count
    max_market_age_seconds: Count
    max_account_age_seconds: Count
    max_fx_age_seconds: Count
    max_spec_age_seconds: Count
    max_clock_offset_ms: Count
    fee_bps: NonnegativeAmount
    slippage_bps: NonnegativeAmount
    gap_bps: NonnegativeAmount
    max_queue_depth: Count

    @model_validator(mode="after")
    def coherent(self) -> Self:
        mapping = dict(self.bucket_by_instrument)
        if (
            len(mapping) != len(self.bucket_by_instrument)
            or set(mapping) != set(self.allowed_instruments)
            or len(self.allowed_instruments) != len(set(self.allowed_instruments))
            or any(not value.startswith("paper.") for value in self.allowed_accounts)
        ):
            raise ValueError("PAPER_POLICY_MAPPING_INVALID")
        return self


class PaperReservation(Contract):
    reservation_id: Identifier
    intent_hash: Digest
    logical_key: Label
    account_ref: Label
    instrument_id: Label
    bucket: Label
    action: MoneyAction
    intent_id: Identifier | None = None
    target_intent_ref: Identifier | None = None
    quantity: NonnegativeAmount
    notional: NonnegativeAmount
    modeled_loss: NonnegativeAmount
    margin: NonnegativeAmount
    state: Literal["ACTIVE", "PARTIAL", "UNKNOWN", "RELEASED"] = "ACTIVE"
    position_ref: Label | None = None
    created_at: UTCTime
    expires_at: UTCTime

    @model_validator(mode="after")
    def chronology(self) -> Self:
        if self.expires_at <= self.created_at:
            raise ValueError("RESERVATION_EXPIRY_INVALID")
        return self


class PaperExposure(Contract):
    quantity: NonnegativeAmount
    notional: NonnegativeAmount
    modeled_loss: NonnegativeAmount
    margin_required: NonnegativeAmount
    cash_required: NonnegativeAmount
    bucket: Label


class PaperReason(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    MODE_MISMATCH = "MODE_MISMATCH"
    ACCOUNT_UNKNOWN = "ACCOUNT_UNKNOWN"
    ACCOUNT_MISMATCH = "ACCOUNT_MISMATCH"
    HASH_MISMATCH = "HASH_MISMATCH"
    VENUE_PRODUCT_INELIGIBLE = "VENUE_PRODUCT_INELIGIBLE"
    RELEASE_INELIGIBLE = "RELEASE_INELIGIBLE"
    FIXTURE_MODE_BLOCKED = "FIXTURE_MODE_BLOCKED"
    INTENT_EXPIRED = "INTENT_EXPIRED"
    MARKET_INVALID = "MARKET_INVALID"
    MARKET_STALE = "MARKET_STALE"
    ACCOUNT_STALE = "ACCOUNT_STALE"
    ACCOUNT_UNRECONCILED = "ACCOUNT_UNRECONCILED"
    SPEC_STALE = "SPEC_STALE"
    SPEC_UNSUPPORTED = "SPEC_UNSUPPORTED"
    FX_UNKNOWN = "FX_UNKNOWN"
    FX_STALE = "FX_STALE"
    CLOCK_OFFSET = "CLOCK_OFFSET"
    SESSION_CLOSED = "SESSION_CLOSED"
    PRICE_INVALID = "PRICE_INVALID"
    QUANTITY_INVALID = "QUANTITY_INVALID"
    STOP_INVALID = "STOP_INVALID"
    SHORT_UNSUPPORTED = "SHORT_UNSUPPORTED"
    FILL_UNSUPPORTED = "FILL_UNSUPPORTED"
    JOURNAL_UNHEALTHY = "JOURNAL_UNHEALTHY"
    UNKNOWN_ORDER = "UNKNOWN_ORDER"
    DUPLICATE_INTENT = "DUPLICATE_INTENT"
    KILL_BLOCKED = "KILL_BLOCKED"
    ORDER_RATE_CAP = "ORDER_RATE_CAP"
    MINIMUM_QUANTITY = "MINIMUM_QUANTITY"
    MINIMUM_NOTIONAL = "MINIMUM_NOTIONAL"
    BALANCE_CAP = "BALANCE_CAP"
    TRADE_RISK_CAP = "TRADE_RISK_CAP"
    ASSET_RISK_CAP = "ASSET_RISK_CAP"
    BUCKET_RISK_CAP = "BUCKET_RISK_CAP"
    TOTAL_RISK_CAP = "TOTAL_RISK_CAP"
    GROSS_CAP = "GROSS_CAP"
    NET_CAP = "NET_CAP"
    POSITIONS_CAP = "POSITIONS_CAP"
    MARGIN_CAP = "MARGIN_CAP"
    DAILY_LOSS_CAP = "DAILY_LOSS_CAP"
    DRAWDOWN_CAP = "DRAWDOWN_CAP"
    POSITION_UNKNOWN = "POSITION_UNKNOWN"
    OVER_CLOSE = "OVER_CLOSE"
    TARGET_UNKNOWN = "TARGET_UNKNOWN"


class PaperDecision(Contract):
    status: Literal["APPROVED", "DENIED"]
    intent_hash: Digest
    policy_hash: Digest
    account_snapshot_hash: Digest
    market_hash: Digest
    spec_hash: Digest
    release_hash: Digest
    reasons: tuple[PaperReason, ...]
    exposure: PaperExposure | None
    decision_at: UTCTime

    @model_validator(mode="after")
    def approval(self) -> Self:
        if (self.status == "APPROVED") != (not self.reasons and self.exposure is not None):
            raise ValueError("DECISION_INCONSISTENT")
        if self.status == "DENIED" and not self.reasons:
            raise ValueError("DENIAL_REASON_REQUIRED")
        if self.reasons != tuple(reason for reason in PaperReason if reason in self.reasons):
            raise ValueError("REASONS_MUST_BE_ORDERED_UNIQUE")
        return self


class PaperAuthorization(Contract):
    authorization_id: Identifier
    intent_hash: Digest
    policy_hash: Digest
    account_snapshot_hash: Digest
    market_hash: Digest
    spec_hash: Digest
    release_hash: Digest
    account_ref: Label
    writer_epoch: Count
    reservation_id: Identifier
    issued_at: UTCTime
    expires_at: UTCTime
    exposure: PaperExposure
    semantics: Literal["PAPER_NONEXTERNAL"] = "PAPER_NONEXTERNAL"

    @model_validator(mode="after")
    def paper_only(self) -> Self:
        if not self.account_ref.startswith("paper.") or self.expires_at <= self.issued_at:
            raise ValueError("PAPER_AUTHORIZATION_INVALID")
        return self


def provisional_policy() -> PaperPolicy:
    """Explicit versioned engineering fixture, never inherited by money modes."""
    instruments = ("paper.spot.BTCUSD", "paper.spot.ETHUSD", "paper.spot.SYNTHUSD")
    return PaperPolicy(
        version="paper.provisional.v1",
        allowed_instruments=instruments,
        allowed_accounts=("paper.test",),
        bucket_by_instrument=tuple(
            (i, "synthetic" if "SYNTH" in i else "crypto") for i in instruments
        ),
        allowed_venues=(Venue.BINANCE,),
        allowed_products=(Product.SPOT,),
        max_trade_risk_fraction=Decimal("0.0025"),
        max_total_risk_fraction=Decimal("0.01"),
        max_bucket_risk_fraction=Decimal("0.005"),
        max_asset_risk_fraction=Decimal("0.005"),
        max_daily_loss_fraction=Decimal("0.01"),
        max_drawdown_fraction=Decimal("0.05"),
        max_positions=3,
        max_gross_fraction=Decimal("1"),
        max_net_fraction=Decimal("1"),
        max_margin_fraction=Decimal("0.20"),
        max_intents_per_minute=5,
        max_market_age_seconds=2,
        max_account_age_seconds=5,
        max_fx_age_seconds=2,
        max_spec_age_seconds=86400,
        max_clock_offset_ms=250,
        fee_bps=Decimal("10"),
        slippage_bps=Decimal("5"),
        gap_bps=Decimal("5"),
        max_queue_depth=1000,
    )


def bind_authorization(
    decision: PaperDecision,
    intent: PaperIntent,
    account: PaperAccountSnapshot,
    reservation_id: UUID,
    authorization_id: UUID,
    now: datetime,
) -> PaperAuthorization:
    """Bind an approved calculation; storage must commit all records atomically."""
    # Roundtrip validation also rejects model_construct/model_copy validation bypasses.
    decision = PaperDecision.model_validate_json(decision.model_dump_json(warnings="error"))
    intent = PaperIntent.model_validate_json(intent.model_dump_json(warnings="error"))
    account = PaperAccountSnapshot.model_validate_json(account.model_dump_json(warnings="error"))
    if (
        decision.status != "APPROVED"
        or decision.exposure is None
        or intent.mode != Mode.PAPER
        or decision.intent_hash != intent.content_hash()
        or decision.account_snapshot_hash != account.content_hash()
        or intent.account_snapshot_hash != account.content_hash()
        or intent.account_ref != account.account_ref
        or decision.policy_hash != intent.policy_hash
        or decision.market_hash != intent.snapshot_hash
        or decision.spec_hash != intent.spec_hash
        or decision.release_hash != intent.release_hash
        or not intent.created_at <= decision.decision_at <= now < intent.expires_at
    ):
        raise ValueError("PAPER_AUTHORIZATION_BINDING_DENIED")
    return PaperAuthorization(
        authorization_id=authorization_id,
        intent_hash=intent.content_hash(),
        policy_hash=decision.policy_hash,
        account_snapshot_hash=decision.account_snapshot_hash,
        market_hash=decision.market_hash,
        spec_hash=decision.spec_hash,
        release_hash=decision.release_hash,
        account_ref=account.account_ref,
        writer_epoch=account.epoch,
        reservation_id=reservation_id,
        issued_at=now,
        expires_at=intent.expires_at,
        exposure=decision.exposure,
    )
