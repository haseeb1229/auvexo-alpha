"""Fail-closed synthetic DS-03 inspection; immutable facts confer no authority."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import Lock
from time import monotonic
from typing import Protocol

from auvexo_alpha.application.ds03_ports import Ds03ReadPort
from auvexo_alpha.domain.contracts import utc_time
from auvexo_alpha.domain.ds03 import (
    MAX_ATTESTATION_AGE_SECONDS,
    MAX_REQUEST_SECONDS,
    MAX_REQUESTS,
    AttestationPayload,
    BarsPayload,
    BarsRequest,
    DealsPayload,
    DealsRequest,
    DisconnectRequest,
    Ds03Attestation,
    Ds03Bar,
    Ds03DealFact,
    Ds03Error,
    Ds03Gap,
    Ds03Identity,
    Ds03OrderFact,
    Ds03PositionFact,
    Ds03Reply,
    Ds03Request,
    Ds03Rights,
    Ds03Tick,
    OrderHistoryPayload,
    OrderHistoryRequest,
    OrdersPayload,
    PositionsPayload,
    SpecPayload,
    SpecRequest,
    SymbolsPayload,
    TickPayload,
    TickRequest,
    TicksPayload,
    TicksRequest,
    decode_reply,
    decode_request,
)
from auvexo_alpha.domain.ds03_actual import (
    ActualAttestation,
    ActualAttestationPayload,
    ActualBar,
    ActualDealFact,
    ActualDealsPayload,
    ActualIdentity,
    ActualOrderFact,
    ActualOrderHistoryPayload,
    ActualOrdersPayload,
    ActualPositionFact,
    ActualPositionsPayload,
    ActualReply,
    ActualRequest,
    ActualRights,
    ActualSymbolsPayload,
    ActualSymbolsRequest,
    ActualTick,
    catalog_digest,
    decode_actual_reply,
    decode_actual_request,
)

type Record = (
    Ds03Bar
    | Ds03Tick
    | Ds03OrderFact
    | Ds03PositionFact
    | Ds03DealFact
    | ActualBar
    | ActualTick
    | ActualOrderFact
    | ActualPositionFact
    | ActualDealFact
)


class _ReadPort[
    RequestT: Ds03Request,
    ReplyT: (Ds03Reply, ActualReply),
    AttestationT: (Ds03Attestation, ActualAttestation),
](Protocol):
    def attest(self) -> AttestationT: ...
    def execute(self, request: RequestT) -> ReplyT: ...
    def disconnect(self) -> None: ...


class _Codec[
    RequestT: Ds03Request,
    ReplyT: (Ds03Reply, ActualReply),
    IdentityT: (Ds03Identity, ActualIdentity),
    AttestationT: (Ds03Attestation, ActualAttestation),
    RightsT: (Ds03Rights, ActualRights),
](Protocol):
    def request(self, raw: bytes) -> RequestT: ...
    def reply(self, raw: bytes) -> ReplyT: ...
    def identity(self, raw: bytes) -> IdentityT: ...
    def attestation(self, raw: bytes) -> AttestationT: ...
    def rights(self, raw: bytes) -> RightsT: ...


class _SyntheticCodec:
    def request(self, raw: bytes) -> Ds03Request:
        return decode_request(raw)

    def reply(self, raw: bytes) -> Ds03Reply:
        return decode_reply(raw)

    def identity(self, raw: bytes) -> Ds03Identity:
        return Ds03Identity.model_validate_json(raw)

    def attestation(self, raw: bytes) -> Ds03Attestation:
        return Ds03Attestation.model_validate_json(raw)

    def rights(self, raw: bytes) -> Ds03Rights:
        return Ds03Rights.model_validate_json(raw)


class _ActualCodec:
    def request(self, raw: bytes) -> ActualRequest:
        return decode_actual_request(raw)

    def reply(self, raw: bytes) -> ActualReply:
        return decode_actual_reply(raw)

    def identity(self, raw: bytes) -> ActualIdentity:
        return ActualIdentity.model_validate_json(raw)

    def attestation(self, raw: bytes) -> ActualAttestation:
        return ActualAttestation.model_validate_json(raw)

    def rights(self, raw: bytes) -> ActualRights:
        return ActualRights.model_validate_json(raw)


class _ReadSession[
    RequestT: Ds03Request,
    ReplyT: (Ds03Reply, ActualReply),
    IdentityT: (Ds03Identity, ActualIdentity),
    AttestationT: (Ds03Attestation, ActualAttestation),
    RightsT: (Ds03Rights, ActualRights),
]:
    """One bounded session. Any failure closes it; recovery creates a new reader."""

    def __init__(
        self,
        port: _ReadPort[RequestT, ReplyT, AttestationT],
        expected: IdentityT,
        rights: RightsT,
        codec: _Codec[RequestT, ReplyT, IdentityT, AttestationT, RightsT],
        *,
        clock: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        self._port: _ReadPort[RequestT, ReplyT, AttestationT] = port
        self._codec: _Codec[RequestT, ReplyT, IdentityT, AttestationT, RightsT] = codec
        self._expected: IdentityT = codec.identity(expected.canonical_bytes())
        self._rights: RightsT = codec.rights(rights.canonical_bytes())
        if self._rights.review_hash != self._expected.rights_hash:
            raise Ds03Error()
        self._clock, self._monotonic = clock, monotonic_clock
        self._closed = False
        self._lock = Lock()
        self._requests: set[object] = set()
        self._symbols: tuple[str, ...] | None = None
        self._catalog: list[str] = []
        self._catalog_hash: str | None = None
        self._catalog_total: int | None = None
        self._specs: dict[str, str] = {}
        self._first_seen: dict[str, tuple[str, datetime]] = {}
        self._record_seen: dict[tuple[str, str | None, object, datetime], tuple[str, datetime]] = {}
        self._progress: dict[tuple[object, ...], tuple[datetime, datetime]] = {}

    def _now(self, fallback: datetime) -> datetime:
        return utc_time(self._clock() if self._clock is not None else fallback)

    def _attest(self, observed: AttestationT, now: datetime) -> AttestationT:
        actual = self._codec.attestation(observed.canonical_bytes())
        if actual.identity != self._expected or not timedelta(0) <= now - actual.observed_at <= (
            timedelta(seconds=MAX_ATTESTATION_AGE_SECONDS)
        ):
            raise Ds03Error()
        return actual

    def _rights_current(self, now: datetime) -> None:
        if now >= self._rights.valid_until:
            raise Ds03Error()

    def _close(self) -> None:
        self._closed = True
        self._port.disconnect()

    def read(self, request: RequestT, *, now: datetime) -> ReplyT:
        acquired = False
        try:
            acquired = self._lock.acquire(blocking=False)
            if not acquired or self._closed or len(self._requests) >= MAX_REQUESTS:
                raise Ds03Error()
            started = self._monotonic()
            request = self._codec.request(request.canonical_bytes())
            now = self._now(utc_time(now))
            if (
                request.request_id in self._requests
                or not request.created_at <= now < request.expires_at
                or request.release_hash != self._expected.release_hash
                or request.config_hash != self._expected.config_hash
            ):
                raise Ds03Error()
            self._requests.add(request.request_id)
            self._rights_current(now)
            self._attest(self._port.attest(), self._now(now))
            if isinstance(request, (SpecRequest, TickRequest, BarsRequest, TicksRequest)):
                if self._symbols is None or request.symbol not in self._symbols:
                    raise Ds03Error()
                if not isinstance(request, SpecRequest) and request.symbol not in self._specs:
                    raise Ds03Error()
            reply = self._codec.reply(self._port.execute(request).canonical_bytes())
            post_attestation = self._port.attest()
            final_now = self._now(now)
            self._attest(post_attestation, final_now)
            self._rights_current(final_now)
            elapsed = self._monotonic() - started
            if (
                self._closed
                or not 0 <= elapsed <= MAX_REQUEST_SECONDS
                or elapsed >= (request.expires_at - now).total_seconds()
                or elapsed >= (self._rights.valid_until - now).total_seconds()
                or final_now < now
                or final_now >= request.expires_at
            ):
                raise Ds03Error()
            self._validate_reply(request, reply, final_now)
            admitted_at = self._now(final_now)
            final_elapsed = self._monotonic() - started
            if (
                self._closed
                or not 0 <= final_elapsed <= MAX_REQUEST_SECONDS
                or final_elapsed >= (request.expires_at - now).total_seconds()
                or final_elapsed >= (self._rights.valid_until - now).total_seconds()
                or admitted_at < final_now
                or admitted_at >= request.expires_at
            ):
                raise Ds03Error()
            self._rights_current(admitted_at)
            if isinstance(request, DisconnectRequest):
                self._close()
            return reply
        except Exception:
            # Single redaction boundary: unknown backend/contract failures close the session.
            try:
                self._close()
            except Exception:
                raise Ds03Error() from None
            raise Ds03Error() from None
        finally:
            if acquired:
                self._lock.release()

    def _validate_reply(self, request: RequestT, reply: ReplyT, now: datetime) -> None:
        envelope, payload = reply.envelope, reply.payload
        if (
            reply.request_id != request.request_id
            or reply.operation != request.operation
            or envelope.identity != self._expected
            or envelope.connector_hash != self._expected.release_hash
            or not request.created_at <= envelope.received_at <= envelope.available_at <= now
        ):
            raise Ds03Error()
        symbol = (
            request.symbol
            if isinstance(request, (SpecRequest, TickRequest, BarsRequest, TicksRequest))
            else None
        )
        if envelope.symbol != symbol:
            raise Ds03Error()
        if isinstance(payload, ActualAttestationPayload):
            actual = self._codec.attestation(payload.attestation.canonical_bytes())
            self._attest(actual, now)
        elif isinstance(payload, AttestationPayload):
            actual = self._codec.attestation(payload.attestation.canonical_bytes())
            self._attest(actual, now)
        if isinstance(payload, ActualSymbolsPayload):
            if not isinstance(request, ActualSymbolsRequest):
                raise Ds03Error()
            self._catalog_page(request, payload)
        elif isinstance(payload, SymbolsPayload):
            if self._symbols is not None and self._symbols != payload.symbols:
                raise Ds03Error()
            self._symbols = payload.symbols
        if isinstance(payload, SpecPayload):
            spec = payload.spec
            if spec.symbol != symbol or spec.content_hash() != envelope.spec_hash:
                raise Ds03Error()
            if spec.symbol in self._specs and self._specs[spec.symbol] != spec.content_hash():
                raise Ds03Error()
            if any(
                t is not None and t > now
                for t in (spec.quote_at, spec.history_start, spec.history_end)
            ):
                raise Ds03Error()
            self._specs[spec.symbol] = spec.content_hash()
        elif symbol is not None and envelope.spec_hash != self._specs.get(symbol):
            raise Ds03Error()
        if isinstance(payload, TickPayload):
            self._records((payload.tick,), request, reply)
        elif isinstance(payload, BarsPayload):
            if not isinstance(request, BarsRequest):
                raise Ds03Error()
            self._records(payload.bars, request, reply)
            self._bar_coverage(request, payload)
        elif isinstance(payload, TicksPayload):
            if not isinstance(request, TicksRequest) or payload.coverage == "COMPLETE":
                # A finite tick sample has no cadence proving complete interval coverage.
                raise Ds03Error()
            self._records(payload.ticks, request, reply)
            self._gaps(payload.gaps, request.start, request.end)
            if payload.coverage == "PARTIAL" and not payload.gaps:
                raise Ds03Error()
        elif isinstance(
            payload,
            (OrdersPayload, OrderHistoryPayload, ActualOrdersPayload, ActualOrderHistoryPayload),
        ):
            self._records(payload.orders, request, reply)
        elif isinstance(payload, (PositionsPayload, ActualPositionsPayload)):
            self._records(payload.positions, request, reply)
        elif isinstance(payload, (DealsPayload, ActualDealsPayload)):
            self._records(payload.deals, request, reply)
        prior_seen = self._first_seen.get(envelope.raw_hash)
        binding = (envelope.normalized_hash, envelope.first_seen_at)
        if prior_seen is not None and prior_seen != binding:
            raise Ds03Error()
        self._first_seen[envelope.raw_hash] = binding
        key: tuple[object, ...] = (request.operation, symbol)
        if isinstance(reply, ActualReply):
            scope: tuple[object, ...] = ()
            if isinstance(request, (BarsRequest, TicksRequest, DealsRequest, OrderHistoryRequest)):
                scope = (request.start, request.end, request.limit)
                if isinstance(request, BarsRequest):
                    scope += (request.timeframe_seconds,)
            elif isinstance(request, ActualSymbolsRequest):
                scope = (request.offset, request.catalog_hash)
            key = (request.operation, symbol, scope, reply.envelope.provider_time_kind)
        prior = self._progress.get(key)
        if prior is not None and (
            envelope.provider_at < prior[0] or envelope.received_at < prior[1]
        ):
            raise Ds03Error()
        self._progress[key] = (envelope.provider_at, envelope.received_at)

    def _records(self, records: tuple[Record, ...], request: RequestT, reply: ReplyT) -> None:
        if isinstance(request, (BarsRequest, TicksRequest, DealsRequest, OrderHistoryRequest)):
            if len(records) > request.limit:
                raise Ds03Error()
        identities: set[tuple[str | None, object]] = set()
        previous: datetime | None = None
        for record in records:
            non_market = isinstance(record, ActualDealFact) and record.kind == "NON_MARKET"
            if not non_market and (self._symbols is None or record.symbol not in self._symbols):
                raise Ds03Error()
            if record.provider_at > reply.envelope.provider_at:
                raise Ds03Error()
            if (
                isinstance(
                    record,
                    (
                        Ds03OrderFact,
                        Ds03PositionFact,
                        Ds03DealFact,
                        ActualOrderFact,
                        ActualPositionFact,
                        ActualDealFact,
                    ),
                )
                and not non_market
            ):
                if record.symbol is None or record.spec_hash != self._specs.get(record.symbol):
                    raise Ds03Error()
            if isinstance(request, (TickRequest, BarsRequest, TicksRequest)):
                if record.symbol != request.symbol:
                    raise Ds03Error()
            if isinstance(request, (BarsRequest, TicksRequest, DealsRequest, OrderHistoryRequest)):
                if not request.start <= record.provider_at < request.end:
                    raise Ds03Error()
            if isinstance(record, (Ds03OrderFact, ActualOrderFact)):
                identity: object = record.order_ref
            elif isinstance(record, (Ds03PositionFact, ActualPositionFact)):
                identity = record.position_ref
            elif isinstance(record, (Ds03DealFact, ActualDealFact)):
                identity = record.deal_ref
            elif isinstance(record, ActualBar):
                identity = (record.provider_at, record.timeframe_seconds)
            else:
                identity = record.provider_at
            key = (record.symbol, identity)
            if key in identities or previous is not None and record.provider_at < previous:
                raise Ds03Error()
            identities.add(key)
            fact_key = (type(record).__name__, record.symbol, identity, record.provider_at)
            first_seen = reply.envelope.first_seen_at
            if isinstance(
                record, (ActualBar, ActualTick, ActualOrderFact, ActualPositionFact, ActualDealFact)
            ):
                first_seen = record.first_seen_at
                if not record.provider_at <= first_seen <= reply.envelope.received_at:
                    raise Ds03Error()
            fact_binding = (record.content_hash(), first_seen)
            old_fact = self._record_seen.get(fact_key)
            if old_fact is not None and old_fact != fact_binding:
                raise Ds03Error()
            self._record_seen[fact_key] = fact_binding
            previous = record.provider_at

    def _catalog_page(self, request: ActualSymbolsRequest, payload: ActualSymbolsPayload) -> None:
        if (
            self._symbols is not None
            or request.offset != len(self._catalog)
            or payload.offset != request.offset
        ):
            raise Ds03Error()
        if request.offset == 0:
            self._catalog_hash, self._catalog_total = payload.catalog_hash, payload.total
        elif request.catalog_hash != self._catalog_hash:
            raise Ds03Error()
        if payload.catalog_hash != self._catalog_hash or payload.total != self._catalog_total:
            raise Ds03Error()
        if set(self._catalog).intersection(payload.symbols):
            raise Ds03Error()
        self._catalog.extend(payload.symbols)
        if payload.complete:
            symbols = tuple(self._catalog)
            if len(symbols) != payload.total or catalog_digest(symbols) != payload.catalog_hash:
                raise Ds03Error()
            self._symbols = symbols

    @staticmethod
    def _gaps(gaps: tuple[Ds03Gap, ...], start: datetime, end: datetime) -> None:
        prior_end = start
        for gap in gaps:
            if not start <= gap.start < gap.end <= end or gap.start < prior_end:
                raise Ds03Error()
            prior_end = gap.end

    def _bar_coverage(self, request: BarsRequest, payload: BarsPayload) -> None:
        seconds = request.timeframe_seconds
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        if any((t - epoch).total_seconds() % seconds for t in (request.start, request.end)):
            raise Ds03Error()
        self._gaps(payload.gaps, request.start, request.end)
        interval = timedelta(seconds=seconds)
        for bar in payload.bars:
            if isinstance(bar, ActualBar) and bar.timeframe_seconds != seconds:
                raise Ds03Error()
            if (bar.provider_at - epoch).total_seconds() % seconds or (
                bar.provider_at + interval > request.end
            ):
                raise Ds03Error()
        if payload.coverage == "UNKNOWN":
            return
        if payload.coverage == "PARTIAL" and not payload.gaps:
            raise Ds03Error()
        segments = [(bar.provider_at, bar.provider_at + interval) for bar in payload.bars]
        segments.extend((gap.start, gap.end) for gap in payload.gaps)
        cursor = request.start
        for start, end in sorted(segments):
            if start != cursor:
                raise Ds03Error()
            cursor = end
        if cursor != request.end:
            raise Ds03Error()


class Ds03Reader(_ReadSession[Ds03Request, Ds03Reply, Ds03Identity, Ds03Attestation, Ds03Rights]):
    """The accepted public synthetic API binds only the original synthetic codec."""

    def __init__(
        self,
        port: Ds03ReadPort,
        expected: Ds03Identity,
        rights: Ds03Rights,
        *,
        clock: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        super().__init__(
            port, expected, rights, _SyntheticCodec(), clock=clock, monotonic_clock=monotonic_clock
        )
