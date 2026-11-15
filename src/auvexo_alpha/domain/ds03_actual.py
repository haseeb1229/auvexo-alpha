"""Closed MT5 DEMO read-only DTO family; no SDK or account activation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Final, Literal, Self, cast, get_args

from pydantic import BeforeValidator, Field, TypeAdapter, ValidationError, model_validator

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
    _Request,
    _unique,
)

PROTOCOL_FAMILY: Final = "DS03_MT5_READONLY_V1"
MAX_CATALOG_SYMBOLS = 4096

# Closed, non-secret refusal reasons. A reason names which control refused, never a
# value: no login, server, account number, password, path or provider text can be one.
type Ds03ReasonCode = Literal[
    "AUTHORITY_INVALID",
    "AUTHORITY_EXPIRED",
    "BINDING_MISMATCH",
    "PACKAGE_MISMATCH",
    "INTERPRETER_MISMATCH",
    "METADATA_UNAVAILABLE",
    "METADATA_MISMATCH",
    "CREDENTIAL_UNAVAILABLE",
    "REFERENCE_KEY_UNAVAILABLE",
    "REFERENCE_MISMATCH",
    "JOB_CONTAINMENT",
    "TERMINAL_NOT_CONTAINED",
    "TERMINAL_IDENTITY",
    "TERMINAL_VERSION",
    "TERMINAL_PROFILE",
    "TERMINAL_DISCONNECTED",
    "INITIALIZE_FAILED",
    "SHUTDOWN_FAILED",
    "ACCOUNT_NOT_DEMO",
    "ACCOUNT_IDENTITY",
    "TRADE_FLAG_TRUE",
    "IDENTITY_DRIFT",
    "ATTESTATION_STALE",
    "RIGHTS_EXPIRED",
    "RIGHTS_MISMATCH",
    "IPC_PROTOCOL",
    "DEADLINE",
    "SESSION_CLOSED",
    "REQUEST_INVALID",
    "REPLY_INVALID",
    "CATALOG_DRIFT",
    "SYMBOL_NOT_ADMITTED",
    "SPEC_DRIFT",
    "PROVIDER_DATA_INVALID",
    "PROVIDER_FUTURE_TIME",
    "HISTORY_CONFLICT",
    "TIME_REGRESSION",
    "TIME_BASIS_UNBOUND",
    "TIME_BASIS_MISMATCH",
    "UNCLASSIFIED",
]
REASON_CODES: Final[frozenset[str]] = frozenset(get_args(Ds03ReasonCode.__value__))


def closed_reason(value: object) -> Ds03ReasonCode:
    """Any value outside the closed set, including secret-shaped text, is UNCLASSIFIED."""
    if type(value) is str and value in REASON_CODES:
        return cast(Ds03ReasonCode, value)
    return "UNCLASSIFIED"


class Ds03Reasoned:
    """Marker for project errors that carry exactly one closed reason code."""

    reason: Ds03ReasonCode


class Ds03Refusal(Ds03Error, Ds03Reasoned):
    """Redacted actual-family refusal: ``DS03_UNAVAILABLE:<closed reason>`` and nothing else."""

    def __init__(self, reason: Ds03ReasonCode) -> None:
        super().__init__()
        self.reason = closed_reason(reason)
        self.args = ("DS03_UNAVAILABLE:" + self.reason,)


def refusal(error: BaseException, default: Ds03ReasonCode) -> Ds03Refusal:
    """A fresh refusal: a closed reason survives, every other error gets the caller's default.

    Raise it ``from None``; the original exception, its text and context never travel.
    """
    if isinstance(error, Ds03Reasoned):
        return Ds03Refusal(error.reason)
    if isinstance(error, ValidationError):
        # A contract validator that refused with a closed reason keeps that reason.
        for detail in error.errors(include_url=False, include_input=False):
            cause = detail.get("ctx", {}).get("error")
            if isinstance(cause, Ds03Reasoned):
                return Ds03Refusal(cause.reason)
    return Ds03Refusal(default)


# Server-time basis. MT5 reports bar/tick/order/deal times in trade-server time; nothing
# may be labelled UTC until an onboarding measurement has classified that basis and an
# accepted authority binds the classification and its evidence hash.
TIME_BASIS_METHOD: Final = "MT5_TICK_TIME_VS_LOCAL_UTC_RECEIPT.v1"
TIME_BASIS_MIN_SAMPLES: Final = 5
TIME_BASIS_MIN_DISTINCT: Final = 3
TIME_BASIS_TOLERANCE_MS: Final = 120_000
TIME_BASIS_MAX_RECEIPT_MS: Final = 10_000
TIME_BASIS_MAX_SAMPLES: Final = 64
# One measurement is one bounded request: its pauses leave room inside the request deadline.
TIME_BASIS_MAX_PAUSE_MS: Final = 5_000
MAX_SERVER_OFFSET_SECONDS: Final = 14 * 3600
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
ServerOffset = Annotated[
    int, Field(ge=-MAX_SERVER_OFFSET_SECONDS, le=MAX_SERVER_OFFSET_SECONDS, multiple_of=3600)
]
RawMilliseconds = Annotated[int, Field(ge=0, le=253402300799999)]
RawSeconds = Annotated[int, Field(ge=0, le=253402300799)]
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


def server_time(raw_milliseconds: int, offset_seconds: int) -> datetime:
    """UTC instant of a raw trade-server millisecond time under a bound whole-hour basis."""
    return _EPOCH + timedelta(milliseconds=raw_milliseconds) - timedelta(seconds=offset_seconds)


class ServerTimeSample(Contract):
    """One raw provider tick time bracketed by local UTC receipt, in epoch milliseconds."""

    symbol: BrokerSymbol
    provider_time: RawSeconds
    provider_time_msc: RawMilliseconds
    local_before_ms: RawMilliseconds
    local_after_ms: RawMilliseconds

    @model_validator(mode="after")
    def bracketed(self) -> Self:
        if self.provider_time_msc // 1000 != self.provider_time or not (
            0 <= self.local_after_ms - self.local_before_ms <= TIME_BASIS_MAX_RECEIPT_MS
        ):
            raise Ds03Refusal("PROVIDER_DATA_INVALID")
        return self


class ServerTimeEvidence(Contract):
    method: Literal["MT5_TICK_TIME_VS_LOCAL_UTC_RECEIPT.v1"] = TIME_BASIS_METHOD
    local_clock_evidence_hash: Digest
    samples: tuple[ServerTimeSample, ...] = Field(min_length=1, max_length=TIME_BASIS_MAX_SAMPLES)


class ServerTimeBasis(Contract):
    """Observed classification; only UTC or a whole-hour offset can ever be bound."""

    method: Literal["MT5_TICK_TIME_VS_LOCAL_UTC_RECEIPT.v1"] = TIME_BASIS_METHOD
    classification: Literal["UTC", "WHOLE_HOUR_OFFSET", "UNKNOWN"]
    offset_seconds: ServerOffset | None
    evidence_hash: Digest
    local_clock_evidence_hash: Digest
    sample_count: int = Field(ge=1, le=TIME_BASIS_MAX_SAMPLES)
    measured_at: UTCTime

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if (self.classification == "UTC") != (self.offset_seconds == 0) or (
            self.classification == "UNKNOWN"
        ) != (self.offset_seconds is None):
            raise Ds03Refusal("TIME_BASIS_MISMATCH")
        return self


def _liveness_bound(samples: tuple[ServerTimeSample, ...]) -> int | None:
    """Least proven upper bound on the offset from ticks that advanced during measurement.

    When a symbol's tick time advances between two of its samples, the newer tick was not
    yet available at the earlier request, so it happened after that request began: provider
    time minus the earlier request time bounds the offset from above, with staleness at
    most the sampling interval. No advancing tick, a tick regression or same-symbol samples
    out of local order prove nothing (None): frozen ticks of a closed or broken feed could
    be hours old, and that age would otherwise be absorbed into a smaller offset.
    """
    previous: dict[str, ServerTimeSample] = {}
    bound: int | None = None
    for sample in samples:
        prior = previous.get(sample.symbol)
        if prior is not None:
            if (
                sample.local_before_ms < prior.local_after_ms
                or sample.provider_time_msc < prior.provider_time_msc
            ):
                return None
            if sample.provider_time_msc > prior.provider_time_msc:
                advanced = sample.provider_time_msc - prior.local_before_ms
                bound = advanced if bound is None else min(bound, advanced)
        previous[sample.symbol] = sample
    return bound


def classify_server_time(evidence: ServerTimeEvidence) -> ServerTimeBasis:
    """Pure classification. A tick cannot precede its event, so provider minus local
    receipt bounds the server offset from below; the freshest sample must land within the
    fixed tolerance of one whole hour and no sample may exceed it. The upper side must be
    proven by liveness (``_liveness_bound``), never assumed from freshness. Anything else,
    including half-hour zones, frozen or stale-only samples or too few distinct ticks, is
    UNKNOWN.
    """
    checked = ServerTimeEvidence.model_validate_json(evidence.canonical_bytes())
    samples = checked.samples
    offset: int | None = None
    distinct = {(sample.symbol, sample.provider_time_msc) for sample in samples}
    live = _liveness_bound(samples)
    if (
        len(samples) >= TIME_BASIS_MIN_SAMPLES
        and len(distinct) >= TIME_BASIS_MIN_DISTINCT
        and live is not None
    ):
        lower = max(sample.provider_time_msc - sample.local_after_ms for sample in samples)
        hours = (lower + 1_800_000) // 3_600_000
        candidate = hours * 3_600_000
        if (
            abs(hours) * 3600 <= MAX_SERVER_OFFSET_SECONDS
            and lower >= candidate - TIME_BASIS_TOLERANCE_MS
            and candidate <= live + TIME_BASIS_TOLERANCE_MS
            and all(
                sample.provider_time_msc - sample.local_before_ms
                <= candidate + TIME_BASIS_TOLERANCE_MS
                for sample in samples
            )
        ):
            offset = hours * 3600
    return ServerTimeBasis(
        classification="UNKNOWN"
        if offset is None
        else "UTC"
        if offset == 0
        else "WHOLE_HOUR_OFFSET",
        offset_seconds=offset,
        evidence_hash=checked.content_hash(),
        local_clock_evidence_hash=checked.local_clock_evidence_hash,
        sample_count=len(samples),
        measured_at=_EPOCH + timedelta(milliseconds=max(s.local_after_ms for s in samples)),
    )


class _ServerTimed(Contract):
    """Raw provider times are retained; the UTC label exists only under a bound basis."""

    server_offset_seconds: ServerOffset
    time_basis_hash: Digest


class ActualIdentity(Ds03Identity):
    account_ref: AccountRef
    server: ServerRef
    process_ref: ProcessRef
    account_type_source: Literal["OWNER_METADATA_ONLY_NOT_EXPOSED_BY_MT5"]
    authority_hash: Digest
    time_basis_hash: Digest | None
    server_offset_seconds: ServerOffset | None

    @model_validator(mode="after")
    def bound_or_unbound_basis(self) -> Self:
        if (self.time_basis_hash is None) != (self.server_offset_seconds is None):
            raise Ds03Refusal("TIME_BASIS_MISMATCH")
        return self


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


class ActualServerTimeRequest(_Request):
    """Onboarding measurement of raw tick times against local UTC receipt; labels nothing.

    Actual family only: the accepted synthetic request union is unchanged.
    """

    operation: Literal["SERVER_TIME"] = "SERVER_TIME"
    symbols: tuple[BrokerSymbol, ...] = Field(min_length=1, max_length=TIME_BASIS_MAX_SAMPLES)
    samples: int = Field(ge=TIME_BASIS_MIN_SAMPLES, le=TIME_BASIS_MAX_SAMPLES)
    interval_ms: int = Field(ge=0, le=TIME_BASIS_MAX_PAUSE_MS)
    local_clock_evidence_hash: Digest

    @model_validator(mode="after")
    def bounded_measurement(self) -> Self:
        if (
            len(set(self.symbols)) != len(self.symbols)
            or (self.samples - 1) * self.interval_ms > TIME_BASIS_MAX_PAUSE_MS
        ):
            raise Ds03Refusal("REQUEST_INVALID")
        return self


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
    | ActualServerTimeRequest
    | DisconnectRequest,
    Field(discriminator="operation"),
]
actual_request_adapter: TypeAdapter[ActualRequest] = TypeAdapter(ActualRequest)
type ActualOperation = Operation | Literal["SERVER_TIME"]


class ActualSymbolSpec(Ds03SymbolSpec, _ServerTimed):
    symbol: BrokerSymbol
    spread_unit: Literal["MT5_POINTS"] = "MT5_POINTS"
    source_ref: Digest
    provider_trade_mode: Annotated[Literal[0, 1, 2, 3, 4], BeforeValidator(_exact_int)]
    provider_order_mode: int = Field(ge=0, le=127)
    provider_filling_mode: int = Field(ge=0, le=7)
    provider_trade_calc_mode: Annotated[
        Literal[0, 1, 2, 3, 4, 5, 32, 33, 34, 36, 37, 38, 39, 64], BeforeValidator(_exact_int)
    ]
    provider_quote_time_raw: RawSeconds | None

    @model_validator(mode="after")
    def quote_time_identity(self) -> Self:
        raw = self.provider_quote_time_raw
        expected = None if raw is None else server_time(raw * 1000, self.server_offset_seconds)
        if raw == 0 or self.quote_at != expected:
            raise Ds03Refusal("TIME_BASIS_MISMATCH")
        return self


class ActualTick(Ds03Tick, _ServerTimed):
    symbol: BrokerSymbol
    first_seen_at: UTCTime
    source_ref: Digest
    time_msc: RawMilliseconds
    flags: int = Field(ge=0, le=255)
    volume_real: NonnegativeAmount

    @model_validator(mode="after")
    def tick_time_identity(self) -> Self:
        if self.provider_at > self.first_seen_at:
            raise Ds03Refusal("PROVIDER_FUTURE_TIME")
        if self.provider_at != server_time(self.time_msc, self.server_offset_seconds):
            raise Ds03Refusal("TIME_BASIS_MISMATCH")
        return self


class ActualBar(Ds03Bar, _ServerTimed):
    symbol: BrokerSymbol
    timeframe_seconds: Annotated[Literal[60, 300, 900, 3600, 86400], BeforeValidator(_exact_int)]
    first_seen_at: UTCTime
    source_ref: Digest
    provider_time_raw: RawSeconds

    @model_validator(mode="after")
    def first_acquisition(self) -> Self:
        if self.provider_at > self.first_seen_at:
            raise Ds03Refusal("PROVIDER_FUTURE_TIME")
        if self.provider_at != server_time(
            self.provider_time_raw * 1000, self.server_offset_seconds
        ):
            raise Ds03Refusal("TIME_BASIS_MISMATCH")
        return self


class ActualOrderFact(_ServerTimed):
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
    setup_time_msc_raw: RawMilliseconds
    # Zero is the provider's own "not done" value; it is retained, never relabelled.
    done_time_msc_raw: RawMilliseconds

    @model_validator(mode="after")
    def order_facts(self) -> Self:
        if self.provider_at > self.first_seen_at:
            raise Ds03Refusal("PROVIDER_FUTURE_TIME")
        if self.volume_current > self.volume_initial:
            raise Ds03Error()
        if (
            self.setup_at > self.provider_at
            or self.done_at is not None
            and not (self.setup_at <= self.done_at <= self.provider_at)
        ):
            raise Ds03Error()
        offset = self.server_offset_seconds
        done = None if not self.done_time_msc_raw else server_time(self.done_time_msc_raw, offset)
        if self.setup_at != server_time(self.setup_time_msc_raw, offset) or self.done_at != done:
            raise Ds03Refusal("TIME_BASIS_MISMATCH")
        return self


class ActualPositionFact(_ServerTimed):
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
    opened_time_msc_raw: RawMilliseconds
    updated_time_msc_raw: RawMilliseconds

    @model_validator(mode="after")
    def position_facts(self) -> Self:
        if self.provider_at > self.first_seen_at:
            raise Ds03Refusal("PROVIDER_FUTURE_TIME")
        if not self.opened_at <= self.updated_at <= self.provider_at:
            raise Ds03Error()
        offset = self.server_offset_seconds
        if self.opened_at != server_time(
            self.opened_time_msc_raw, offset
        ) or self.updated_at != server_time(self.updated_time_msc_raw, offset):
            raise Ds03Refusal("TIME_BASIS_MISMATCH")
        return self


class ActualDealFact(_ServerTimed):
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
    time_msc_raw: RawMilliseconds

    @model_validator(mode="after")
    def deal_variant(self) -> Self:
        if self.provider_at > self.first_seen_at:
            raise Ds03Refusal("PROVIDER_FUTURE_TIME")
        if self.provider_at != server_time(self.time_msc_raw, self.server_offset_seconds):
            raise Ds03Refusal("TIME_BASIS_MISMATCH")
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


class ActualServerTimePayload(Contract):
    """Raw samples plus their classification; the receiver re-derives the basis."""

    kind: Literal["SERVER_TIME"] = "SERVER_TIME"
    evidence: ServerTimeEvidence
    basis: ServerTimeBasis

    @model_validator(mode="after")
    def classified_from_evidence(self) -> Self:
        if classify_server_time(self.evidence) != self.basis:
            raise Ds03Refusal("TIME_BASIS_MISMATCH")
        return self


def require_server_time_binding(
    request: ActualServerTimeRequest, payload: ActualServerTimePayload, envelope: ActualEnvelope
) -> None:
    """The measurement answers exactly this request and was sampled after it was made.

    Its envelope carries local observation time only; no provider time is labelled.
    """
    evidence, symbols = payload.evidence, request.symbols
    created_ms = (request.created_at - _EPOCH) // timedelta(milliseconds=1)
    received_ms = (envelope.received_at - _EPOCH) // timedelta(milliseconds=1)
    if (
        envelope.provider_time_kind != "LOCAL_OBSERVATION_NO_PROVIDER_TIMESTAMP"
        or envelope.symbol is not None
        or evidence.local_clock_evidence_hash != request.local_clock_evidence_hash
        or len(evidence.samples) != request.samples
        or any(
            sample.symbol != symbols[index % len(symbols)]
            or not created_ms <= sample.local_before_ms <= sample.local_after_ms <= received_ms
            for index, sample in enumerate(evidence.samples)
        )
    ):
        raise Ds03Refusal("REPLY_INVALID")


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
    | ActualServerTimePayload
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
        if self.provider_time_kind == "SDK_EVENT_TIME" and self.identity.time_basis_hash is None:
            raise Ds03Refusal("TIME_BASIS_UNBOUND")
        return self


def _timed_records(payload: ActualPayload) -> tuple[_ServerTimed, ...]:
    if isinstance(payload, ActualSpecPayload):
        return (payload.spec,)
    if isinstance(payload, ActualTickPayload):
        return (payload.tick,)
    if isinstance(payload, ActualBarsPayload):
        return payload.bars
    if isinstance(payload, ActualTicksPayload):
        return payload.ticks
    if isinstance(payload, (ActualOrdersPayload, ActualOrderHistoryPayload)):
        return payload.orders
    if isinstance(payload, ActualPositionsPayload):
        return payload.positions
    if isinstance(payload, ActualDealsPayload):
        return payload.deals
    return ()


class ActualReply(Contract):
    request_id: Identifier
    operation: ActualOperation
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
        identity = self.envelope.identity
        for record in _timed_records(self.payload):
            # No provider time is UTC-labelled without the authority-bound basis.
            if identity.time_basis_hash is None:
                raise Ds03Refusal("TIME_BASIS_UNBOUND")
            if (
                record.time_basis_hash != identity.time_basis_hash
                or record.server_offset_seconds != identity.server_offset_seconds
            ):
                raise Ds03Refusal("TIME_BASIS_MISMATCH")
        return self


def catalog_digest(symbols: tuple[str, ...]) -> str:
    return hashlib.sha256(
        json.dumps(symbols, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def decode_actual_request(raw: bytes) -> ActualRequest:
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_FRAME_BYTES:
            raise Ds03Refusal("REQUEST_INVALID")
        json.loads(raw, object_pairs_hook=_unique, parse_constant=_reject_constant)
        return actual_request_adapter.validate_json(raw)
    except (ValueError, TypeError, RecursionError) as error:
        raise refusal(error, "REQUEST_INVALID") from None


def decode_actual_reply(raw: bytes) -> ActualReply:
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_FRAME_BYTES:
            raise Ds03Refusal("REPLY_INVALID")
        json.loads(raw, object_pairs_hook=_unique, parse_constant=_reject_constant)
        return ActualReply.model_validate_json(raw)
    except (ValueError, TypeError, RecursionError) as error:
        raise refusal(error, "REPLY_INVALID") from None
