"""Fail-closed synthetic DS-03 inspection; immutable facts confer no authority."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import Lock
from time import monotonic

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

type Record = Ds03Bar | Ds03Tick | Ds03OrderFact | Ds03PositionFact | Ds03DealFact


class Ds03Reader:
    """One bounded session. Any failure closes it; recovery creates a new reader."""

    def __init__(
        self,
        port: Ds03ReadPort,
        expected: Ds03Identity,
        rights: Ds03Rights,
        *,
        clock: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        self._port = port
        self._expected = Ds03Identity.model_validate_json(expected.canonical_bytes())
        self._rights = Ds03Rights.model_validate_json(rights.canonical_bytes())
        if self._rights.review_hash != self._expected.rights_hash:
            raise Ds03Error()
        self._clock, self._monotonic = clock, monotonic_clock
        self._closed = False
        self._lock = Lock()
        self._requests: set[object] = set()
        self._symbols: tuple[str, ...] | None = None
        self._specs: dict[str, str] = {}
        self._first_seen: dict[str, tuple[str, datetime]] = {}
        self._record_seen: dict[tuple[str, str, object, datetime], tuple[str, datetime]] = {}
        self._progress: dict[tuple[str, str | None], tuple[datetime, datetime]] = {}

    def _now(self, fallback: datetime) -> datetime:
        return utc_time(self._clock() if self._clock is not None else fallback)

    def _attest(self, observed: Ds03Attestation, now: datetime) -> Ds03Attestation:
        actual = Ds03Attestation.model_validate_json(observed.canonical_bytes())
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

    def read(self, request: Ds03Request, *, now: datetime) -> Ds03Reply:
        acquired = False
        try:
            acquired = self._lock.acquire(blocking=False)
            if not acquired or self._closed or len(self._requests) >= MAX_REQUESTS:
                raise Ds03Error()
            started = self._monotonic()
            request = decode_request(request.canonical_bytes())
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
            reply = decode_reply(self._port.execute(request).canonical_bytes())
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

    def _validate_reply(self, request: Ds03Request, reply: Ds03Reply, now: datetime) -> None:
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
        if isinstance(payload, AttestationPayload):
            self._attest(payload.attestation, now)
        if isinstance(payload, SymbolsPayload):
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
        elif isinstance(payload, (OrdersPayload, OrderHistoryPayload)):
            self._records(payload.orders, request, reply)
        elif isinstance(payload, PositionsPayload):
            self._records(payload.positions, request, reply)
        elif isinstance(payload, DealsPayload):
            self._records(payload.deals, request, reply)
        prior_seen = self._first_seen.get(envelope.raw_hash)
        binding = (envelope.normalized_hash, envelope.first_seen_at)
        if prior_seen is not None and prior_seen != binding:
            raise Ds03Error()
        self._first_seen[envelope.raw_hash] = binding
        key = (request.operation, symbol)
        prior = self._progress.get(key)
        if prior is not None and (
            envelope.provider_at < prior[0] or envelope.received_at < prior[1]
        ):
            raise Ds03Error()
        self._progress[key] = (envelope.provider_at, envelope.received_at)

    def _records(self, records: tuple[Record, ...], request: Ds03Request, reply: Ds03Reply) -> None:
        if isinstance(request, (BarsRequest, TicksRequest, DealsRequest, OrderHistoryRequest)):
            if len(records) > request.limit:
                raise Ds03Error()
        identities: set[tuple[str, object]] = set()
        previous: datetime | None = None
        for record in records:
            if self._symbols is None or record.symbol not in self._symbols:
                raise Ds03Error()
            if record.provider_at > reply.envelope.provider_at:
                raise Ds03Error()
            if isinstance(record, (Ds03OrderFact, Ds03PositionFact, Ds03DealFact)):
                if record.spec_hash != self._specs.get(record.symbol):
                    raise Ds03Error()
            if isinstance(request, (TickRequest, BarsRequest, TicksRequest)):
                if record.symbol != request.symbol:
                    raise Ds03Error()
            if isinstance(request, (BarsRequest, TicksRequest, DealsRequest, OrderHistoryRequest)):
                if not request.start <= record.provider_at < request.end:
                    raise Ds03Error()
            if isinstance(record, Ds03OrderFact):
                identity: object = record.order_ref
            elif isinstance(record, Ds03PositionFact):
                identity = record.position_ref
            elif isinstance(record, Ds03DealFact):
                identity = record.deal_ref
            else:
                identity = record.provider_at
            key = (record.symbol, identity)
            if key in identities or previous is not None and record.provider_at < previous:
                raise Ds03Error()
            identities.add(key)
            fact_key = (type(record).__name__, record.symbol, identity, record.provider_at)
            fact_binding = (record.content_hash(), reply.envelope.first_seen_at)
            old_fact = self._record_seen.get(fact_key)
            if old_fact is not None and old_fact != fact_binding:
                raise Ds03Error()
            self._record_seen[fact_key] = fact_binding
            previous = record.provider_at

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
