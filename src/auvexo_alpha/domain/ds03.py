"""Strict synthetic DS-03 source contracts; no provider or execution capability."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, Field, TypeAdapter, model_validator

from auvexo_alpha.domain.contracts import (
    Contract,
    Digest,
    Identifier,
    Label,
    NonnegativeAmount,
    PositiveAmount,
    UTCTime,
    exact_decimal,
)

MAX_FRAME_BYTES = 65536
MAX_REQUESTS = 256
MAX_SYMBOLS = 128
MAX_RECORDS = 256
MAX_REQUEST_SECONDS = 10
MAX_ATTESTATION_AGE_SECONDS = 30
type Operation = Literal[
    "ATTEST",
    "SYMBOLS",
    "SPEC",
    "TICK",
    "BARS",
    "TICKS",
    "ORDERS",
    "POSITIONS",
    "DEALS",
    "ORDER_HISTORY",
    "DISCONNECT",
]
Symbol = Annotated[str, Field(pattern=r"^synthetic\.[A-Za-z0-9_.-]{1,64}$")]
SyntheticLabel = Annotated[str, Field(pattern=r"^synthetic\.[A-Za-z0-9_.:-]{1,80}$")]
Text = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[\x20-\x7e]+$")]
CurrencyCode = Annotated[str, Field(pattern=r"^[A-Z]{3,8}$")]


class Ds03Error(ValueError):
    """Only fixed redacted codes leave this boundary."""

    def __init__(self) -> None:
        super().__init__("DS03_UNAVAILABLE")


class Ds03Identity(Contract):
    account_ref: SyntheticLabel
    login_hash: Digest
    server: SyntheticLabel
    account_type: Label
    currency: CurrencyCode
    leverage: int = Field(gt=0, le=100000)
    mode: Literal["DEMO"]
    terminal_build: int = Field(ge=4755, le=1000000)
    terminal_version: Label
    process_ref: SyntheticLabel
    profile_hash: Digest
    release_hash: Digest
    config_hash: Digest
    rights_hash: Digest

    @model_validator(mode="after")
    def known_identity_metadata(self) -> Self:
        unknown = {"UNKNOWN", "UNAVAILABLE", "NONE", "NULL", "UNSPECIFIED", "NA"}
        fields = (self.account_type, self.currency, self.terminal_version)
        if any(value.upper() in unknown for value in fields):
            raise Ds03Error()
        for label in (self.account_ref, self.server, self.process_ref):
            if label.rsplit(".", 1)[-1].upper() in unknown:
                raise Ds03Error()
        return self


def _exact_bool(value: object) -> bool:
    if type(value) is not bool:
        raise Ds03Error()
    return value


class Ds03Attestation(Contract):
    identity: Ds03Identity
    observed_at: UTCTime
    connected: Annotated[Literal[True], BeforeValidator(_exact_bool)]
    credential_readonly: Annotated[Literal[True], BeforeValidator(_exact_bool)]
    account_trade_allowed: Annotated[Literal[False], BeforeValidator(_exact_bool)]
    terminal_trade_allowed: Annotated[Literal[False], BeforeValidator(_exact_bool)]


class Ds03Rights(Contract):
    review_hash: Digest
    valid_until: UTCTime
    synthetic: Annotated[Literal[True], BeforeValidator(_exact_bool)] = True


class _Request(Contract):
    request_id: Identifier
    created_at: UTCTime
    expires_at: UTCTime
    release_hash: Digest
    config_hash: Digest

    @model_validator(mode="after")
    def bounded_lifetime(self) -> Self:
        if (
            not timedelta(0)
            < self.expires_at - self.created_at
            <= timedelta(seconds=MAX_REQUEST_SECONDS)
        ):
            raise Ds03Error()
        return self


class AttestRequest(_Request):
    operation: Literal["ATTEST"] = "ATTEST"


class SymbolsRequest(_Request):
    operation: Literal["SYMBOLS"] = "SYMBOLS"


class SpecRequest(_Request):
    operation: Literal["SPEC"] = "SPEC"
    symbol: Symbol


class TickRequest(_Request):
    operation: Literal["TICK"] = "TICK"
    symbol: Symbol


class _RangeRequest(_Request):
    start: UTCTime
    end: UTCTime
    limit: int = Field(ge=1, le=MAX_RECORDS)

    @model_validator(mode="after")
    def bounded_range(self) -> Self:
        if not self.start < self.end <= self.created_at or self.end - self.start > timedelta(
            days=366
        ):
            raise Ds03Error()
        return self


def _exact_int(value: object) -> int:
    if type(value) is not int:
        raise Ds03Error()
    return value


class BarsRequest(_RangeRequest):
    operation: Literal["BARS"] = "BARS"
    symbol: Symbol
    timeframe_seconds: Annotated[Literal[60, 300, 900, 3600, 86400], BeforeValidator(_exact_int)]


class TicksRequest(_RangeRequest):
    operation: Literal["TICKS"] = "TICKS"
    symbol: Symbol


class OrdersRequest(_Request):
    operation: Literal["ORDERS"] = "ORDERS"


class PositionsRequest(_Request):
    operation: Literal["POSITIONS"] = "POSITIONS"


class DealsRequest(_RangeRequest):
    operation: Literal["DEALS"] = "DEALS"


class OrderHistoryRequest(_RangeRequest):
    operation: Literal["ORDER_HISTORY"] = "ORDER_HISTORY"


class DisconnectRequest(_Request):
    operation: Literal["DISCONNECT"] = "DISCONNECT"


type Ds03Request = Annotated[
    AttestRequest
    | SymbolsRequest
    | SpecRequest
    | TickRequest
    | BarsRequest
    | TicksRequest
    | OrdersRequest
    | PositionsRequest
    | DealsRequest
    | OrderHistoryRequest
    | DisconnectRequest,
    Field(discriminator="operation"),
]
request_adapter: TypeAdapter[Ds03Request] = TypeAdapter(Ds03Request)


class Ds03SymbolSpec(Contract):
    symbol: Symbol
    description: Text
    category: Text
    digits: int = Field(ge=0, le=18)
    point: PositiveAmount
    tick_size: PositiveAmount
    contract_size: PositiveAmount
    volume_min: PositiveAmount
    volume_max: PositiveAmount
    volume_step: PositiveAmount
    tick_value: NonnegativeAmount | None = None
    tick_value_profit: NonnegativeAmount | None = None
    tick_value_loss: NonnegativeAmount | None = None
    volume_limit: NonnegativeAmount | None = None
    stops_level: int | None = Field(default=None, ge=0, le=100000000)
    freeze_level: int | None = Field(default=None, ge=0, le=100000000)
    trade_mode: Label | None = None
    order_modes: tuple[Label, ...] | None = Field(default=None, max_length=32)
    fill_modes: tuple[Label, ...] | None = Field(default=None, max_length=32)
    margin_mode: Label | None = None
    execution_mode: Label | None = None
    base_currency: CurrencyCode | None = None
    profit_currency: CurrencyCode | None = None
    margin_currency: CurrencyCode | None = None
    sessions: tuple[Text, ...] | None = Field(default=None, max_length=32)
    spread: NonnegativeAmount | None = None
    swap_mode: Label | None = None
    swap_long: Annotated[Decimal, BeforeValidator(exact_decimal)] | None = None
    swap_short: Annotated[Decimal, BeforeValidator(exact_decimal)] | None = None
    quote_at: UTCTime | None = None
    history_start: UTCTime | None = None
    history_end: UTCTime | None = None

    @model_validator(mode="after")
    def semantic_bounds(self) -> Self:
        if self.volume_min > self.volume_max or self.volume_step > self.volume_max:
            raise Ds03Error()
        if self.history_start is not None and self.history_end is not None:
            if self.history_start > self.history_end:
                raise Ds03Error()
        return self


class Ds03Tick(Contract):
    symbol: Symbol
    provider_at: UTCTime
    bid: NonnegativeAmount
    ask: NonnegativeAmount
    last: NonnegativeAmount | None = None
    volume: NonnegativeAmount | None = None

    @model_validator(mode="after")
    def quote_order(self) -> Self:
        if self.bid > self.ask:
            raise Ds03Error()
        return self


class Ds03Bar(Contract):
    symbol: Symbol
    provider_at: UTCTime
    open: PositiveAmount
    high: PositiveAmount
    low: PositiveAmount
    close: PositiveAmount
    tick_volume: int = Field(default=0, ge=0, le=1000000000000000000)
    spread: int | None = Field(default=None, ge=0, le=100000000)
    real_volume: NonnegativeAmount | None = None

    @model_validator(mode="after")
    def ohlc_order(self) -> Self:
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise Ds03Error()
        return self


class Ds03Gap(Contract):
    start: UTCTime
    end: UTCTime
    reason: Label = "UNKNOWN"

    @model_validator(mode="after")
    def gap_order(self) -> Self:
        if self.start >= self.end:
            raise Ds03Error()
        return self


class Ds03OrderFact(Contract):
    order_ref: SyntheticLabel
    symbol: Symbol
    spec_hash: Digest
    state: Literal["OPEN", "CLOSED", "CANCELLED"]
    quantity: PositiveAmount
    provider_at: UTCTime


class Ds03PositionFact(Contract):
    position_ref: SyntheticLabel
    symbol: Symbol
    spec_hash: Digest
    side: Literal["BUY", "SELL"]
    quantity: PositiveAmount
    price: PositiveAmount
    provider_at: UTCTime


class Ds03DealFact(Contract):
    deal_ref: SyntheticLabel
    symbol: Symbol
    spec_hash: Digest
    side: Literal["BUY", "SELL"]
    quantity: PositiveAmount
    price: PositiveAmount
    provider_at: UTCTime


class AttestationPayload(Contract):
    kind: Literal["ATTEST"] = "ATTEST"
    attestation: Ds03Attestation


class SymbolsPayload(Contract):
    kind: Literal["SYMBOLS"] = "SYMBOLS"
    symbols: tuple[Symbol, ...] = Field(max_length=MAX_SYMBOLS)

    @model_validator(mode="after")
    def unique_symbols(self) -> Self:
        if len(set(self.symbols)) != len(self.symbols):
            raise Ds03Error()
        return self


class SpecPayload(Contract):
    kind: Literal["SPEC"] = "SPEC"
    spec: Ds03SymbolSpec


class TickPayload(Contract):
    kind: Literal["TICK"] = "TICK"
    tick: Ds03Tick


type Coverage = Literal["COMPLETE", "PARTIAL", "UNKNOWN"]


class BarsPayload(Contract):
    kind: Literal["BARS"] = "BARS"
    bars: tuple[Ds03Bar, ...] = Field(max_length=MAX_RECORDS)
    gaps: tuple[Ds03Gap, ...] = Field(default=(), max_length=MAX_RECORDS)
    coverage: Coverage = "UNKNOWN"

    @model_validator(mode="after")
    def complete_has_no_gaps(self) -> Self:
        if self.coverage == "COMPLETE" and self.gaps:
            raise Ds03Error()
        return self


class TicksPayload(Contract):
    kind: Literal["TICKS"] = "TICKS"
    ticks: tuple[Ds03Tick, ...] = Field(max_length=MAX_RECORDS)
    gaps: tuple[Ds03Gap, ...] = Field(default=(), max_length=MAX_RECORDS)
    coverage: Coverage = "UNKNOWN"

    @model_validator(mode="after")
    def complete_has_no_gaps(self) -> Self:
        if self.coverage == "COMPLETE" and self.gaps:
            raise Ds03Error()
        return self


class OrdersPayload(Contract):
    kind: Literal["ORDERS"] = "ORDERS"
    orders: tuple[Ds03OrderFact, ...] = Field(max_length=MAX_RECORDS)


class PositionsPayload(Contract):
    kind: Literal["POSITIONS"] = "POSITIONS"
    positions: tuple[Ds03PositionFact, ...] = Field(max_length=MAX_RECORDS)


class DealsPayload(Contract):
    kind: Literal["DEALS"] = "DEALS"
    deals: tuple[Ds03DealFact, ...] = Field(max_length=MAX_RECORDS)


class OrderHistoryPayload(Contract):
    kind: Literal["ORDER_HISTORY"] = "ORDER_HISTORY"
    orders: tuple[Ds03OrderFact, ...] = Field(max_length=MAX_RECORDS)


class DisconnectedPayload(Contract):
    kind: Literal["DISCONNECT"] = "DISCONNECT"


type Ds03Payload = Annotated[
    AttestationPayload
    | SymbolsPayload
    | SpecPayload
    | TickPayload
    | BarsPayload
    | TicksPayload
    | OrdersPayload
    | PositionsPayload
    | DealsPayload
    | OrderHistoryPayload
    | DisconnectedPayload,
    Field(discriminator="kind"),
]


class Ds03SourceEnvelope(Contract):
    identity: Ds03Identity
    provider_at: UTCTime
    first_seen_at: UTCTime
    received_at: UTCTime
    processed_at: UTCTime
    available_at: UTCTime
    raw_hash: Digest
    normalized_hash: Digest
    connector_hash: Digest
    symbol: Symbol | None = None
    spec_hash: Digest | None = None
    source_id: Literal["DS-03"] = "DS-03"
    provider: Literal["EXNESS"] = "EXNESS"
    product: Literal["CFD"] = "CFD"
    synthetic: Annotated[Literal[True], BeforeValidator(_exact_bool)] = True
    clock_status: Literal["STRUCTURAL_ONLY_CLOCK_BLOCKED"] = "STRUCTURAL_ONLY_CLOCK_BLOCKED"

    @model_validator(mode="after")
    def causal_order(self) -> Self:
        if (
            not self.provider_at
            <= self.first_seen_at
            <= self.received_at
            <= self.processed_at
            <= (self.available_at)
        ):
            raise Ds03Error()
        if (self.symbol is None) != (self.spec_hash is None):
            raise Ds03Error()
        return self


class Ds03Reply(Contract):
    request_id: Identifier
    operation: Operation
    payload: Ds03Payload
    envelope: Ds03SourceEnvelope

    @model_validator(mode="after")
    def payload_binding(self) -> Self:
        if self.operation != self.payload.kind:
            raise Ds03Error()
        if self.envelope.normalized_hash != self.payload.content_hash():
            raise Ds03Error()
        return self


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise Ds03Error()
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise Ds03Error()


def decode_request(raw: bytes) -> Ds03Request:
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_FRAME_BYTES:
            raise Ds03Error()
        # JSON parser detects duplicates before strict Pydantic UTC/Decimal decoding.
        json.loads(raw, object_pairs_hook=_unique, parse_constant=_reject_constant)
        return request_adapter.validate_json(raw)
    except (ValueError, TypeError, RecursionError):
        raise Ds03Error() from None


def decode_reply(raw: bytes) -> Ds03Reply:
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_FRAME_BYTES:
            raise Ds03Error()
        json.loads(raw, object_pairs_hook=_unique, parse_constant=_reject_constant)
        return Ds03Reply.model_validate_json(raw)
    except (ValueError, TypeError, RecursionError):
        raise Ds03Error() from None
