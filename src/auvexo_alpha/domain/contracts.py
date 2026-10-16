"""Version 1 shapes, not a risk kernel, trading engine or permit mechanism."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator


class Mode(StrEnum):
    RESEARCH = "RESEARCH"
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    DEMO = "DEMO"
    SHADOW = "SHADOW"
    LIVE_LIMITED = "LIVE_LIMITED"
    LIVE = "LIVE"


class Venue(StrEnum):
    EXNESS = "EXNESS"
    BINANCE = "BINANCE"


class Product(StrEnum):
    SPOT = "SPOT"
    CFD = "CFD"
    PERPETUAL = "PERPETUAL"


class MoneyAction(StrEnum):
    OPEN = "OPEN"
    AMEND = "AMEND"
    CANCEL = "CANCEL"
    CLOSE = "CLOSE"
    WITHDRAW = "WITHDRAW"


def exact_decimal(value: object) -> Decimal:
    if isinstance(value, str):
        if not re.fullmatch(r"-?(0|[1-9][0-9]{0,17})(\.[0-9]{1,18})?", value):
            raise ValueError("expected a bounded plain decimal string")
        result = Decimal(value)
    elif isinstance(value, Decimal):
        result = value
    else:
        raise ValueError("financial input must be Decimal or a plain decimal string")
    if not result.is_finite():
        raise ValueError("financial input must be finite")
    exponent = result.as_tuple().exponent
    if (
        not isinstance(exponent, int)
        or not -18 <= exponent <= 18
        or len(result.as_tuple().digits) > 36
        or result.copy_abs() >= Decimal("1e18")
    ):
        raise ValueError("financial input exceeds supported precision")
    return result


def utc_time(value: object) -> datetime:
    if isinstance(value, str):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z", value):
            raise ValueError("expected UTC RFC3339 with Z and microsecond precision")
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must have UTC offset zero")
    return value.astimezone(UTC)


def uuid_value(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        result = UUID(value)
        if str(result) == value:
            return result
    raise ValueError("expected canonical lowercase UUID")


PositiveAmount = Annotated[
    Decimal, BeforeValidator(exact_decimal, json_schema_input_type=str), Field(gt=0)
]
NonnegativeAmount = Annotated[
    Decimal, BeforeValidator(exact_decimal, json_schema_input_type=str), Field(ge=0)
]
UTCTime = Annotated[datetime, BeforeValidator(utc_time)]
Identifier = Annotated[UUID, BeforeValidator(uuid_value)]
Label = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Currency = Literal["BTC", "ETH", "XAU", "USD", "USDT", "USDC", "EUR", "GBP", "JPY", "PKR"]


class Contract(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, hide_input_in_errors=True)
    schema_version: Literal["1.0"] = "1.0"

    def canonical_bytes(self) -> bytes:
        # Financial decimals always strings; sorted keys; UTC Z; no floats/NaN in contracts.
        def default(value: object) -> str:
            if isinstance(value, Decimal):
                if value == 0:
                    return "0"
                return (
                    format(value, "f").rstrip("0").rstrip(".")
                    if "." in format(value, "f")
                    else format(value, "f")
                )
            if isinstance(value, datetime):
                return (
                    value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
                )
            if isinstance(value, UUID):
                return str(value)
            raise TypeError("unsupported canonical value")

        return json.dumps(
            self.model_dump(mode="python"),
            default=default,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")

    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


class EvidenceRefs(Contract):
    source_ids: tuple[Label, ...] = Field(min_length=1, max_length=32)
    dataset_version: Digest
    strategy_version: Label
    model_version: Label | None = None


class Envelope(Contract):
    command_id: Identifier
    correlation_id: Identifier
    causation_id: Identifier | None = None
    source_id: Label
    mode: Mode
    created_at: UTCTime
    expires_at: UTCTime

    @model_validator(mode="after")
    def chronology(self) -> Self:
        if self.expires_at <= self.created_at:
            raise ValueError("expiry must follow creation")
        return self

    def is_expired(self, now: datetime) -> bool:
        return utc_time(now) >= self.expires_at


class InstrumentSpec(Contract):
    instrument_id: Label
    venue: Venue
    product: Product
    symbol: Label
    base_currency: Currency
    quote_currency: Currency
    quantity_unit: Literal["BASE_UNIT", "CONTRACT"]
    contract_multiplier: PositiveAmount
    price_tick: PositiveAmount
    quantity_step: PositiveAmount
    min_quantity: PositiveAmount
    max_quantity: PositiveAmount
    spec_version: Label
    observed_at: UTCTime

    @model_validator(mode="after")
    def units_and_bounds(self) -> Self:
        if self.base_currency == self.quote_currency:
            raise ValueError("base and quote currencies must differ")
        if self.max_quantity < self.min_quantity:
            raise ValueError("maximum quantity below minimum")
        with localcontext() as decimal_context:
            decimal_context.prec = 80
            for size in (self.min_quantity, self.max_quantity):
                if size % self.quantity_step != 0:
                    raise ValueError("quantity bounds must align with step")
        if self.product == Product.SPOT and (
            self.quantity_unit != "BASE_UNIT" or self.contract_multiplier != 1
        ):
            raise ValueError("spot units require base units and multiplier one")
        if self.product != Product.SPOT and self.quantity_unit != "CONTRACT":
            raise ValueError("derivative units require explicit contracts")
        if self.venue == Venue.EXNESS and self.product != Product.CFD:
            raise ValueError("Exness shape supports CFD identity only")
        if self.venue == Venue.BINANCE and self.product == Product.CFD:
            raise ValueError("Binance CFD identity unsupported")
        return self


class MarketState(Contract):
    market_state_id: Identifier
    instrument_id: Label
    as_of: UTCTime
    available_at: UTCTime
    decision_at: UTCTime
    source_watermark: UTCTime
    dataset_version: Digest
    health: Literal["HEALTHY", "STALE", "GAPPED", "UNKNOWN"]

    @model_validator(mode="after")
    def point_in_time(self) -> Self:
        if not self.source_watermark <= self.as_of <= self.available_at <= self.decision_at:
            raise ValueError("invalid point-in-time chronology")
        return self


class FeatureSnapshot(MarketState):
    feature_snapshot_id: Identifier
    feature_version: Label
    code_hash: Digest
    missing_features: tuple[Label, ...] = ()


class TradeCandidate(Envelope):
    candidate_id: Identifier
    instrument_id: Label
    venue: Venue
    product: Product
    side: Literal["BUY", "SELL"]
    quantity: PositiveAmount
    proposed_entry: PositiveAmount
    proposed_stop: PositiveAmount
    market_state_id: Identifier
    evidence: EvidenceRefs


class TradeIntent(TradeCandidate):
    intent_id: Identifier
    account_ref: Label
    action: MoneyAction
    policy_version: Label
    time_in_force: Literal["IOC", "FOK", "GTC"]


class RiskAuthorization(Envelope):
    """Inert shape only. A valid instance grants no capability in Phase 1."""

    authorization_id: Identifier
    intent_hash: Digest
    account_ref: Label
    account_epoch: Annotated[int, Field(ge=0)]
    policy_version: Label
    reservation_id: Identifier
    max_quantity: PositiveAmount
    max_notional: PositiveAmount
    max_modeled_loss: PositiveAmount
    issuer_ref: Label


class ExecutionReport(Contract):
    """An externally observed fact shape; never emitted as a fake broker result."""

    report_id: Identifier
    intent_id: Identifier
    attempt_id: Identifier
    broker_order_ref: Label | None
    broker_deal_ref: Label | None
    received_at: UTCTime
    broker_at: UTCTime | None
    status: Literal[
        "ACKNOWLEDGED", "REJECTED", "UNKNOWN", "PARTIALLY_FILLED", "FILLED", "CANCELED", "EXPIRED"
    ]
    requested_quantity: PositiveAmount
    filled_quantity: NonnegativeAmount
    fees: NonnegativeAmount
    raw_response_hash: Digest

    @model_validator(mode="after")
    def fill_consistency(self) -> Self:
        if self.filled_quantity > self.requested_quantity:
            raise ValueError("filled quantity exceeds requested quantity")
        if self.status == "FILLED" and self.filled_quantity != self.requested_quantity:
            raise ValueError("filled status requires full quantity")
        if (
            self.status == "PARTIALLY_FILLED"
            and not 0 < self.filled_quantity < self.requested_quantity
        ):
            raise ValueError("partial fill requires strict partial quantity")
        if self.filled_quantity > 0 and self.broker_deal_ref is None:
            raise ValueError("fill requires a broker deal reference")
        if self.status == "REJECTED" and self.filled_quantity != 0:
            raise ValueError("rejection cannot claim a fill")
        return self
