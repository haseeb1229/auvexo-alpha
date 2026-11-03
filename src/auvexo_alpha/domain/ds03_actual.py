"""Closed MT5 DEMO read-only DTO family; no SDK or account activation."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Annotated, Final, Literal, Self

from pydantic import BeforeValidator, Field, TypeAdapter, model_validator

from auvexo_alpha.domain.contracts import (
    Contract,
    Digest,
    Identifier,
    NonnegativeAmount,
    PositiveAmount,
    UTCTime,
    exact_decimal,
)
from auvexo_alpha.domain.ds03 import (
    MAX_FRAME_BYTES,
    MAX_RECORDS,
    MAX_SYMBOLS,
    AttestationPayload,
    AttestRequest,
    BarsPayload,
    BarsRequest,
    DealsRequest,
    DisconnectedPayload,
    DisconnectRequest,
    Ds03Attestation,
    Ds03Bar,
    Ds03Error,
    Ds03Identity,
    Ds03SymbolSpec,
    Ds03Tick,
    Operation,
    OrderHistoryRequest,
    OrdersRequest,
    PositionsRequest,
    SpecPayload,
    SpecRequest,
    SymbolsPayload,
    SymbolsRequest,
    TickPayload,
    TickRequest,
    TicksPayload,
    TicksRequest,
    _exact_bool,
    _exact_int,
    _reject_constant,
    _unique,
)

PROTOCOL_FAMILY: Final = "DS03_MT5_READONLY_V1"
MAX_CATALOG_SYMBOLS = 4096
BrokerSymbol = Annotated[str, Field(min_length=1, max_length=96, pattern=r"^[\x21-\x7e]+$")]
AccountRef = Annotated[str, Field(pattern=r"^ds03\.account\.[0-9a-f]{64}$")]
ServerRef = Annotated[str, Field(pattern=r"^ds03\.server\.[0-9a-f]{64}$")]
ProcessRef = Annotated[str, Field(pattern=r"^ds03\.process\.[0-9a-f]{64}$")]
OrderRef = Annotated[str, Field(pattern=r"^ds03\.order\.[0-9a-f]{64}$")]
PositionRef = Annotated[str, Field(pattern=r"^ds03\.position\.[0-9a-f]{64}$")]
DealRef = Annotated[str, Field(pattern=r"^ds03\.deal\.[0-9a-f]{64}$")]
SignedAmount = Annotated[Decimal, BeforeValidator(exact_decimal)]
ExactTrue = Annotated[Literal[True], BeforeValidator(_exact_bool)]
ExactFalse = Annotated[Literal[False], BeforeValidator(_exact_bool)]


class ActualIdentity(Ds03Identity):
    account_ref: AccountRef
    server: ServerRef
    process_ref: ProcessRef
    account_type_source: Literal["OWNER_METADATA_ONLY_NOT_EXPOSED_BY_MT5"]
    authority_hash: Digest


class ActualAttestation(Ds03Attestation):
    identity: ActualIdentity
    credential_authority_hash: Digest

    @model_validator(mode="after")
    def authority_provenance(self) -> Self:
        if self.credential_authority_hash != self.identity.authority_hash:
            raise Ds03Error()
        return self


class ActualRights(Contract):
    review_hash: Digest
    valid_until: UTCTime
    protocol_family: Literal["DS03_MT5_READONLY_V1"]
    synthetic: ExactFalse


class ActualSymbolsRequest(SymbolsRequest):
    offset: int = Field(default=0, ge=0, le=MAX_CATALOG_SYMBOLS)
    catalog_hash: Digest | None = None

    @model_validator(mode="after")
    def catalog_cursor(self) -> Self:
        if (self.offset == 0) != (self.catalog_hash is None):
            raise Ds03Error()
        return self


class ActualSpecRequest(SpecRequest):
    symbol: BrokerSymbol


class ActualTickRequest(TickRequest):
    symbol: BrokerSymbol


class ActualBarsRequest(BarsRequest):
    symbol: BrokerSymbol


class ActualTicksRequest(TicksRequest):
    symbol: BrokerSymbol


ActualAttestRequest = AttestRequest
ActualOrdersRequest = OrdersRequest
ActualPositionsRequest = PositionsRequest
ActualDealsRequest = DealsRequest
ActualOrderHistoryRequest = OrderHistoryRequest
ActualDisconnectRequest = DisconnectRequest

type ActualRequest = Annotated[
    AttestRequest
    | ActualSymbolsRequest
    | ActualSpecRequest
    | ActualTickRequest
    | ActualBarsRequest
    | ActualTicksRequest
    | OrdersRequest
    | PositionsRequest
    | DealsRequest
    | OrderHistoryRequest
    | DisconnectRequest,
    Field(discriminator="operation"),
]
actual_request_adapter: TypeAdapter[ActualRequest] = TypeAdapter(ActualRequest)


class ActualSymbolSpec(Ds03SymbolSpec):
    symbol: BrokerSymbol
    spread_unit: Literal["MT5_POINTS"] = "MT5_POINTS"
    source_ref: Digest
    provider_trade_mode: Annotated[Literal[0, 1, 2, 3, 4], BeforeValidator(_exact_int)]
    provider_order_mode: int = Field(ge=0, le=127)
    provider_filling_mode: int = Field(ge=0, le=7)
    provider_trade_calc_mode: Annotated[
        Literal[0, 1, 2, 3, 4, 5, 32, 33, 34, 36, 37, 38, 39, 64], BeforeValidator(_exact_int)
    ]


class ActualTick(Ds03Tick):
    symbol: BrokerSymbol
    first_seen_at: UTCTime
    source_ref: Digest
    time_msc: int = Field(ge=0, le=253402300799999)
    flags: int = Field(ge=0, le=255)
    volume_real: NonnegativeAmount

    @model_validator(mode="after")
    def tick_time_identity(self) -> Self:
        if self.provider_at > self.first_seen_at or self.provider_at.microsecond % 1000:
            raise Ds03Error()
        seconds = int(self.provider_at.timestamp())
        if seconds * 1000 + self.provider_at.microsecond // 1000 != self.time_msc:
            raise Ds03Error()
        return self


class ActualBar(Ds03Bar):
    symbol: BrokerSymbol
    timeframe_seconds: Annotated[Literal[60, 300, 900, 3600, 86400], BeforeValidator(_exact_int)]
    first_seen_at: UTCTime
    source_ref: Digest

    @model_validator(mode="after")
    def first_acquisition(self) -> Self:
        if self.provider_at > self.first_seen_at:
            raise Ds03Error()
        return self


class ActualOrderFact(Contract):
    order_ref: OrderRef
    symbol: BrokerSymbol
    spec_hash: Digest
    provider_state: Annotated[Literal[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], BeforeValidator(_exact_int)]
    provider_type: Annotated[Literal[0, 1, 2, 3, 4, 5, 6, 7, 8], BeforeValidator(_exact_int)]
    volume_initial: PositiveAmount
    volume_current: NonnegativeAmount
    price_open: NonnegativeAmount
    setup_at: UTCTime
    done_at: UTCTime | None
    provider_at: UTCTime
    first_seen_at: UTCTime
    source_ref: Digest

    @model_validator(mode="after")
    def order_facts(self) -> Self:
        if self.volume_current > self.volume_initial or self.provider_at > self.first_seen_at:
            raise Ds03Error()
        if (
            self.setup_at > self.provider_at
            or self.done_at is not None
            and not (self.setup_at <= self.done_at <= self.provider_at)
        ):
            raise Ds03Error()
        return self


class ActualPositionFact(Contract):
    position_ref: PositionRef
    symbol: BrokerSymbol
    spec_hash: Digest
    provider_type: Annotated[Literal[0, 1], BeforeValidator(_exact_int)]
    quantity: PositiveAmount
    price: PositiveAmount
    opened_at: UTCTime
    updated_at: UTCTime
    provider_at: UTCTime
    first_seen_at: UTCTime
    source_ref: Digest

    @model_validator(mode="after")
    def position_facts(self) -> Self:
        if not self.opened_at <= self.updated_at <= self.provider_at <= self.first_seen_at:
            raise Ds03Error()
        return self


class ActualDealFact(Contract):
    deal_ref: DealRef
    kind: Literal["TRADE", "NON_MARKET"]
    symbol: BrokerSymbol | None
    spec_hash: Digest | None
    provider_type: Annotated[
        Literal[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17],
        BeforeValidator(_exact_int),
    ]
    entry: Annotated[Literal[0, 1, 2, 3], BeforeValidator(_exact_int)]
    quantity: NonnegativeAmount
    price: NonnegativeAmount
    profit: SignedAmount
    commission: SignedAmount
    swap: SignedAmount
    fee: SignedAmount
    provider_at: UTCTime
    first_seen_at: UTCTime
    source_ref: Digest

    @model_validator(mode="after")
    def deal_variant(self) -> Self:
        if self.provider_at > self.first_seen_at:
            raise Ds03Error()
        if self.kind == "TRADE":
            if self.provider_type not in (0, 1) or self.symbol is None or self.spec_hash is None:
                raise Ds03Error()
            if self.quantity <= 0 or self.price <= 0:
                raise Ds03Error()
        elif self.provider_type in (0, 1) or self.symbol is not None or self.spec_hash is not None:
            raise Ds03Error()
        return self


class ActualAttestationPayload(AttestationPayload):
    attestation: ActualAttestation


class ActualSymbolsPayload(SymbolsPayload):
    symbols: tuple[BrokerSymbol, ...] = Field(max_length=MAX_SYMBOLS)
    catalog_hash: Digest
    total: int = Field(ge=0, le=MAX_CATALOG_SYMBOLS)
    offset: int = Field(ge=0, le=MAX_CATALOG_SYMBOLS)
    complete: Annotated[bool, BeforeValidator(_exact_bool)]

    @model_validator(mode="after")
    def catalog_page(self) -> Self:
        if self.offset + len(self.symbols) > self.total:
            raise Ds03Error()
        if self.complete != (self.offset + len(self.symbols) == self.total):
            raise Ds03Error()
        if not self.complete and len(self.symbols) != MAX_SYMBOLS:
            raise Ds03Error()
        return self


class ActualSpecPayload(SpecPayload):
    spec: ActualSymbolSpec


class ActualTickPayload(TickPayload):
    tick: ActualTick


class ActualBarsPayload(BarsPayload):
    bars: tuple[ActualBar, ...] = Field(max_length=MAX_RECORDS)


class ActualTicksPayload(TicksPayload):
    ticks: tuple[ActualTick, ...] = Field(max_length=MAX_RECORDS)


class ActualOrdersPayload(Contract):
    kind: Literal["ORDERS"] = "ORDERS"
    orders: tuple[ActualOrderFact, ...] = Field(max_length=MAX_RECORDS)


class ActualPositionsPayload(Contract):
    kind: Literal["POSITIONS"] = "POSITIONS"
    positions: tuple[ActualPositionFact, ...] = Field(max_length=MAX_RECORDS)


class ActualDealsPayload(Contract):
    kind: Literal["DEALS"] = "DEALS"
    deals: tuple[ActualDealFact, ...] = Field(max_length=MAX_RECORDS)


class ActualOrderHistoryPayload(Contract):
    kind: Literal["ORDER_HISTORY"] = "ORDER_HISTORY"
    orders: tuple[ActualOrderFact, ...] = Field(max_length=MAX_RECORDS)


ActualDisconnectedPayload = DisconnectedPayload

type ActualPayload = Annotated[
    ActualAttestationPayload
    | ActualSymbolsPayload
    | ActualSpecPayload
    | ActualTickPayload
    | ActualBarsPayload
    | ActualTicksPayload
    | ActualOrdersPayload
    | ActualPositionsPayload
    | ActualDealsPayload
    | ActualOrderHistoryPayload
    | DisconnectedPayload,
    Field(discriminator="kind"),
]


class ActualEnvelope(Contract):
    identity: ActualIdentity
    provider_at: UTCTime
    first_seen_at: UTCTime
    received_at: UTCTime
    processed_at: UTCTime
    available_at: UTCTime
    raw_hash: Digest
    normalized_hash: Digest
    connector_hash: Digest
    symbol: BrokerSymbol | None = None
    spec_hash: Digest | None = None
    source_id: Literal["DS-03"] = "DS-03"
    provider: Literal["EXNESS"] = "EXNESS"
    product: Literal["CFD"] = "CFD"
    provider_time_kind: Literal["SDK_EVENT_TIME", "LOCAL_OBSERVATION_NO_PROVIDER_TIMESTAMP"]
    protocol_family: Literal["DS03_MT5_READONLY_V1"]
    synthetic: ExactFalse
    clock_status: Literal["STRUCTURAL_ONLY_CLOCK_BLOCKED"] = "STRUCTURAL_ONLY_CLOCK_BLOCKED"

    @model_validator(mode="after")
    def causal_order(self) -> Self:
        if (
            not self.provider_at
            <= self.first_seen_at
            <= self.received_at
            <= self.processed_at
            <= self.available_at
        ):
            raise Ds03Error()
        if (self.symbol is None) != (self.spec_hash is None):
            raise Ds03Error()
        return self


class ActualReply(Contract):
    request_id: Identifier
    operation: Operation
    payload: ActualPayload
    envelope: ActualEnvelope
    protocol_family: Literal["DS03_MT5_READONLY_V1"]

    @model_validator(mode="after")
    def payload_binding(self) -> Self:
        if (
            self.operation != self.payload.kind
            or self.envelope.normalized_hash != self.payload.content_hash()
        ):
            raise Ds03Error()
        return self


def catalog_digest(symbols: tuple[str, ...]) -> str:
    return hashlib.sha256(
        json.dumps(symbols, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def decode_actual_request(raw: bytes) -> ActualRequest:
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_FRAME_BYTES:
            raise Ds03Error()
        json.loads(raw, object_pairs_hook=_unique, parse_constant=_reject_constant)
        return actual_request_adapter.validate_json(raw)
    except (ValueError, TypeError, RecursionError):
        raise Ds03Error() from None


def decode_actual_reply(raw: bytes) -> ActualReply:
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_FRAME_BYTES:
            raise Ds03Error()
        json.loads(raw, object_pairs_hook=_unique, parse_constant=_reject_constant)
        return ActualReply.model_validate_json(raw)
    except (ValueError, TypeError, RecursionError):
        raise Ds03Error() from None
