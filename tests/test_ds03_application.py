"""D3 application adversaries with deterministic synthetic-only ports."""

import hashlib
from datetime import timedelta
from decimal import Decimal
from threading import Event, Thread
from uuid import uuid4

import pytest
from test_ds03_contracts import NOW, attest, identity, spec

from auvexo_alpha.application.ds03 import Ds03Reader
from auvexo_alpha.domain.ds03 import (
    AttestationPayload,
    AttestRequest,
    BarsPayload,
    BarsRequest,
    DealsPayload,
    DealsRequest,
    DisconnectedPayload,
    DisconnectRequest,
    Ds03Bar,
    Ds03Error,
    Ds03Gap,
    Ds03Reply,
    Ds03Rights,
    Ds03SourceEnvelope,
    Ds03Tick,
    OrdersPayload,
    OrdersRequest,
    SpecPayload,
    SpecRequest,
    SymbolsPayload,
    SymbolsRequest,
    TickPayload,
    TickRequest,
    TicksPayload,
    TicksRequest,
)

SYMBOL = "synthetic.BTCUSDm"


def req(cls=AttestRequest, at=NOW, **kwargs):
    return cls(
        request_id=uuid4(),
        created_at=at,
        expires_at=at + timedelta(seconds=10),
        release_hash=identity().release_hash,
        config_hash=identity().config_hash,
        **kwargs,
    )


def rights(**changes):
    return Ds03Rights(
        **{"review_hash": identity().rights_hash, "valid_until": NOW + timedelta(days=1), **changes}
    )


class Backend:
    def __init__(self):
        self.now = NOW
        self.identity = identity()
        self.observed = NOW
        self.calls = 0
        self.attests = 0
        self.closed = False
        self.payload = None
        self.hook = None
        self.response_hook = None
        self.attest_hook = None
        self.raw = None
        self.first_seen = NOW

    def attest(self):
        self.attests += 1
        if self.attest_hook:
            return self.attest_hook(self)
        return attest().model_copy(update={"identity": self.identity, "observed_at": self.observed})

    def disconnect(self):
        self.closed = True

    def execute(self, request):
        self.calls += 1
        if self.hook:
            self.hook(self)
        if self.payload is not None:
            payload = self.payload
        elif request.operation == "ATTEST":
            payload = AttestationPayload(attestation=self.attest())
        elif request.operation == "SYMBOLS":
            payload = SymbolsPayload(symbols=(SYMBOL,))
        elif request.operation == "SPEC":
            payload = SpecPayload(spec=spec())
        elif request.operation == "TICK":
            payload = TickPayload(
                tick=Ds03Tick(symbol=SYMBOL, provider_at=self.now, bid="1", ask="2")
            )
        elif request.operation == "ORDERS":
            payload = OrdersPayload(orders=())
        elif request.operation == "DEALS":
            payload = DealsPayload(deals=())
        elif request.operation == "DISCONNECT":
            payload = DisconnectedPayload()
        else:
            raise AssertionError("test payload required")
        symbol = getattr(request, "symbol", None)
        envelope = Ds03SourceEnvelope(
            identity=self.identity,
            provider_at=self.now,
            first_seen_at=self.first_seen,
            received_at=self.now,
            processed_at=self.now,
            available_at=self.now,
            raw_hash=self.raw
            or hashlib.sha256(payload.canonical_bytes() + str(self.now).encode()).hexdigest(),
            normalized_hash=payload.content_hash(),
            connector_hash=identity().release_hash,
            symbol=symbol,
            spec_hash=spec().content_hash() if symbol else None,
        )
        response = Ds03Reply(
            request_id=request.request_id,
            operation=request.operation,
            payload=payload,
            envelope=envelope,
        )
        return self.response_hook(response) if self.response_hook else response


def ready():
    backend = Backend()
    reader = Ds03Reader(backend, identity(), rights())
    reader.read(req(SymbolsRequest), now=NOW)
    reader.read(req(SpecRequest, symbol=SYMBOL), now=NOW)
    return backend, reader


def assert_closed(reader, backend):
    assert backend.closed
    calls = backend.calls
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE$"):
        reader.read(req(), now=NOW)
    assert backend.calls == calls


def test_discovery_spec_tick_clock_label_and_clean_disconnect():
    backend, reader = ready()
    reply = reader.read(req(TickRequest, symbol=SYMBOL), now=NOW)
    assert reply.envelope.clock_status == "STRUCTURAL_ONLY_CLOCK_BLOCKED"
    assert reply.envelope.identity.mode == "DEMO"
    assert reply.payload.tick.symbol.endswith("m")
    reply = reader.read(req(DisconnectRequest), now=NOW)
    assert reply.operation == "DISCONNECT"
    assert_closed(reader, backend)
    fresh = Ds03Reader(Backend(), identity(), rights())
    assert fresh.read(req(), now=NOW).operation == "ATTEST"


@pytest.mark.parametrize(
    "field,value",
    [
        ("server", "synthetic.other"),
        ("login_hash", "f" * 64),
        ("account_ref", "synthetic.other"),
        ("process_ref", "synthetic.restart"),
        ("profile_hash", "e" * 64),
        ("terminal_build", 5000),
        ("currency", "EUR"),
        ("leverage", 50),
    ],
)
def test_observed_identity_drift_refuses_before_reads(field, value):
    backend = Backend()
    backend.identity = backend.identity.model_copy(update={field: value})
    reader = Ds03Reader(backend, identity(), rights())
    with pytest.raises(Ds03Error):
        reader.read(req(), now=NOW)
    assert backend.calls == 0
    assert_closed(reader, backend)


def test_account_swap_during_read_and_stale_future_attestation():
    backend = Backend()
    reader = Ds03Reader(backend, identity(), rights())
    backend.hook = lambda port: setattr(
        port, "identity", identity().model_copy(update={"server": "synthetic.swap"})
    )
    with pytest.raises(Ds03Error):
        reader.read(req(), now=NOW)
    assert_closed(reader, backend)
    for delta in (-31, 1):
        backend = Backend()
        backend.observed = NOW + timedelta(seconds=delta)
        reader = Ds03Reader(backend, identity(), rights())
        with pytest.raises(Ds03Error):
            reader.read(req(), now=NOW)
        assert backend.calls == 0


@pytest.mark.parametrize("delta", [-1, 0])
def test_expired_rights_refuse_before_effect(delta):
    backend = Backend()
    reader = Ds03Reader(backend, identity(), rights(valid_until=NOW + timedelta(seconds=delta)))
    with pytest.raises(Ds03Error):
        reader.read(req(), now=NOW)
    assert backend.calls == 0


def test_rights_hash_mismatch_refuses_construction():
    with pytest.raises(Ds03Error):
        Ds03Reader(Backend(), identity(), rights(review_hash="f" * 64))


def test_duplicate_request_and_max_session_bound():
    backend = Backend()
    reader = Ds03Reader(backend, identity(), rights())
    request = req()
    reader.read(request, now=NOW)
    with pytest.raises(Ds03Error):
        reader.read(request, now=NOW)
    assert backend.calls == 1
    backend = Backend()
    reader = Ds03Reader(backend, identity(), rights())
    for _ in range(256):
        reader.read(req(OrdersRequest), now=NOW)
    with pytest.raises(Ds03Error):
        reader.read(req(OrdersRequest), now=NOW)
    assert backend.calls == 256


@pytest.mark.parametrize("field", ["release_hash", "config_hash"])
def test_request_wrong_binding_refuses(field):
    backend = Backend()
    reader = Ds03Reader(backend, identity(), rights())
    request = req().model_copy(update={field: "f" * 64})
    with pytest.raises(Ds03Error):
        reader.read(request, now=NOW)
    assert backend.calls == 0


def test_remaining_ttl_uses_monotonic_even_with_static_injected_utc():
    backend = Backend()
    samples = iter((10.0, 12.0))
    reader = Ds03Reader(backend, identity(), rights(), monotonic_clock=lambda: next(samples))
    request = req().model_copy(update={"expires_at": NOW + timedelta(seconds=1)})
    with pytest.raises(Ds03Error):
        reader.read(request, now=NOW)
    assert_closed(reader, backend)


def test_utc_regression_and_rights_expiring_during_call():
    for final in (NOW - timedelta(seconds=1), NOW + timedelta(seconds=2)):
        backend = Backend()
        times = iter((NOW, NOW, final))
        reader = Ds03Reader(
            backend,
            identity(),
            rights(valid_until=NOW + timedelta(seconds=1)),
            clock=lambda values=times: next(values),
        )
        with pytest.raises(Ds03Error):
            reader.read(req(), now=NOW)
        assert_closed(reader, backend)


def test_concurrent_request_closes_both_and_never_accepts_partial_reply():
    entered = Event()
    release = Event()
    errors = []
    backend = Backend()
    reader = Ds03Reader(backend, identity(), rights())

    def wait(port):
        entered.set()
        assert release.wait(2)

    backend.hook = wait

    def first():
        try:
            reader.read(req(), now=NOW)
        except Ds03Error:
            errors.append("closed")

    worker = Thread(target=first)
    worker.start()
    assert entered.wait(2)
    with pytest.raises(Ds03Error):
        reader.read(req(), now=NOW)
    release.set()
    worker.join(2)
    assert errors == ["closed"] and not worker.is_alive()
    assert backend.calls == 1


def test_reentrant_request_latches_closed():
    backend = Backend()
    reader = Ds03Reader(backend, identity(), rights())

    def recursive(port):
        with pytest.raises(Ds03Error):
            reader.read(req(), now=NOW)

    backend.hook = recursive
    with pytest.raises(Ds03Error):
        reader.read(req(), now=NOW)
    assert_closed(reader, backend)


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("synthetic detail"),
        RuntimeError("synthetic detail"),
        BrokenPipeError("synthetic detail"),
    ],
)
def test_backend_crash_timeout_broken_pipe_generic_and_closed(error):
    backend = Backend()
    reader = Ds03Reader(backend, identity(), rights())

    def fail(port):
        raise error

    backend.hook = fail
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE$") as result:
        reader.read(req(), now=NOW)
    assert result.value.__suppress_context__
    assert_closed(reader, backend)


@pytest.mark.parametrize("symbol", [SYMBOL, "synthetic.XAUUSD", "synthetic.BTCUSD"])
def test_undiscovered_absent_suffix_or_unsupported_xau_refuses_before_read(symbol):
    backend = Backend()
    reader = Ds03Reader(backend, identity(), rights())
    with pytest.raises(Ds03Error):
        reader.read(req(TickRequest, symbol=symbol), now=NOW)
    assert backend.calls == 0


def test_spec_drift_refuses_and_record_without_spec_refuses():
    backend, reader = ready()
    backend.payload = SpecPayload(spec=spec(contract_size="2"))

    def bind(response):
        return response.model_copy(
            update={
                "envelope": response.envelope.model_copy(
                    update={"spec_hash": backend.payload.spec.content_hash()}
                )
            }
        )

    backend.response_hook = bind
    with pytest.raises(Ds03Error):
        reader.read(req(SpecRequest, symbol=SYMBOL), now=NOW)
    assert_closed(reader, backend)


@pytest.mark.parametrize("change", ["request", "release", "normalized", "future", "connector"])
def test_response_lineage_correlation_hash_and_future_leak_refuse(change):
    backend = Backend()
    reader = Ds03Reader(backend, identity(), rights())

    def corrupt(response):
        if change == "request":
            return response.model_copy(update={"request_id": uuid4()})
        envelope = response.envelope
        fields = {
            "release": {"identity": identity().model_copy(update={"release_hash": "f" * 64})},
            "normalized": {"normalized_hash": "f" * 64},
            "future": {"available_at": NOW + timedelta(seconds=1)},
            "connector": {"connector_hash": "f" * 64},
        }[change]
        return response.model_copy(update={"envelope": envelope.model_copy(update=fields)})

    backend.response_hook = corrupt
    with pytest.raises(Ds03Error):
        reader.read(req(), now=NOW)
    assert_closed(reader, backend)


def test_raw_hash_cannot_bind_different_payload_and_refreshed_record_denied():
    backend = Backend()
    reader = Ds03Reader(backend, identity(), rights())
    backend.raw = "a" * 64
    reader.read(req(OrdersRequest), now=NOW)
    with pytest.raises(Ds03Error):
        reader.read(req(SymbolsRequest), now=NOW)
    backend, reader = ready()
    backend.raw = "b" * 64
    reader.read(req(TickRequest, symbol=SYMBOL), now=NOW)
    tick = Ds03Tick(symbol=SYMBOL, provider_at=NOW, bid="1", ask="2")
    backend.payload = TickPayload(tick=tick)
    backend.raw = "c" * 64
    backend.now = NOW + timedelta(seconds=1)
    backend.first_seen = backend.now
    backend.observed = backend.now
    with pytest.raises(Ds03Error):
        reader.read(req(TickRequest, at=backend.now, symbol=SYMBOL), now=backend.now)


def test_conflicting_duplicate_fact_and_time_regression_refuse():
    backend, reader = ready()
    reader.read(req(TickRequest, symbol=SYMBOL), now=NOW)
    backend.payload = TickPayload(tick=Ds03Tick(symbol=SYMBOL, provider_at=NOW, bid="2", ask="3"))
    with pytest.raises(Ds03Error):
        reader.read(req(TickRequest, symbol=SYMBOL), now=NOW)
    backend, reader = ready()
    reader.read(req(TickRequest, symbol=SYMBOL), now=NOW)
    backend.payload = TickPayload(
        tick=Ds03Tick(symbol=SYMBOL, provider_at=NOW - timedelta(seconds=1), bid="1", ask="2")
    )
    backend.response_hook = lambda r: r.model_copy(
        update={
            "envelope": r.envelope.model_copy(
                update={
                    "provider_at": NOW - timedelta(seconds=1),
                    "first_seen_at": NOW - timedelta(seconds=1),
                }
            )
        }
    )
    with pytest.raises(Ds03Error):
        reader.read(req(TickRequest, symbol=SYMBOL), now=NOW)


def test_new_empty_snapshot_can_have_new_first_seen():
    backend = Backend()
    reader = Ds03Reader(backend, identity(), rights())
    reader.read(req(OrdersRequest), now=NOW)
    backend.now = NOW + timedelta(seconds=1)
    backend.first_seen = backend.now
    backend.observed = backend.now
    assert reader.read(req(OrdersRequest, at=backend.now), now=backend.now).payload.orders == ()


def bar(at):
    return Ds03Bar(symbol=SYMBOL, provider_at=at, open="1", high="2", low="1", close="2")


def test_complete_closed_bars_and_partial_gap_evidence():
    start = NOW - timedelta(minutes=2)
    for payload in (
        BarsPayload(bars=(bar(start), bar(start + timedelta(minutes=1))), coverage="COMPLETE"),
        BarsPayload(
            bars=(bar(start),),
            coverage="PARTIAL",
            gaps=(Ds03Gap(start=start + timedelta(minutes=1), end=NOW),),
        ),
        BarsPayload(bars=(), coverage="UNKNOWN"),
    ):
        backend, reader = ready()
        backend.payload = payload
        request = req(
            BarsRequest, symbol=SYMBOL, start=start, end=NOW, limit=2, timeframe_seconds=60
        )
        assert reader.read(request, now=NOW).payload.coverage == payload.coverage


@pytest.mark.parametrize(
    "case",
    [
        "emptycomplete",
        "missingcomplete",
        "duplicate",
        "unfinished",
        "outside",
        "partialnogap",
        "gaphole",
        "gapoverlap",
    ],
)
def test_bar_missing_duplicate_future_and_fabricated_coverage_refuse(case):
    start = NOW - timedelta(minutes=2)
    payloads = {
        "emptycomplete": BarsPayload(bars=(), coverage="COMPLETE"),
        "missingcomplete": BarsPayload(bars=(bar(start),), coverage="COMPLETE"),
        "duplicate": BarsPayload(bars=(bar(start), bar(start))),
        "unfinished": BarsPayload(bars=(bar(NOW - timedelta(seconds=30)),)),
        "outside": BarsPayload(bars=(bar(start - timedelta(minutes=1)),)),
        "partialnogap": BarsPayload(bars=(bar(start),), coverage="PARTIAL"),
        "gaphole": BarsPayload(
            bars=(),
            coverage="PARTIAL",
            gaps=(Ds03Gap(start=start, end=start + timedelta(minutes=1)),),
        ),
        "gapoverlap": BarsPayload(
            bars=(bar(start),), coverage="PARTIAL", gaps=(Ds03Gap(start=start, end=NOW),)
        ),
    }
    backend, reader = ready()
    backend.payload = payloads[case]
    request = req(BarsRequest, symbol=SYMBOL, start=start, end=NOW, limit=2, timeframe_seconds=60)
    with pytest.raises(Ds03Error):
        reader.read(request, now=NOW)


def test_complete_tick_claim_and_duplicate_ticks_refuse():
    for payload in (
        TicksPayload(ticks=(), coverage="COMPLETE"),
        TicksPayload(
            ticks=(
                Ds03Tick(symbol=SYMBOL, provider_at=NOW - timedelta(seconds=1), bid="1", ask="2"),
            )
            * 2
        ),
    ):
        backend, reader = ready()
        backend.payload = payload
        request = req(
            TicksRequest, symbol=SYMBOL, start=NOW - timedelta(minutes=1), end=NOW, limit=2
        )
        with pytest.raises(Ds03Error):
            reader.read(request, now=NOW)


def test_post_attestation_captured_before_observation_clock():
    backend = Backend()
    clock_state = [NOW]

    def observed(port):
        value = attest().model_copy(update={"observed_at": clock_state[0]})
        clock_state[0] += timedelta(microseconds=1)
        return value

    backend.attest_hook = observed
    reader = Ds03Reader(backend, identity(), rights(), clock=lambda: clock_state[0])
    assert reader.read(req(), now=NOW).operation == "ATTEST"


def test_rights_remaining_lifetime_uses_monotonic_with_static_utc():
    backend = Backend()
    samples = iter((10.0, 12.0))
    reader = Ds03Reader(
        backend,
        identity(),
        rights(valid_until=NOW + timedelta(seconds=1)),
        monotonic_clock=lambda: next(samples),
    )
    with pytest.raises(Ds03Error):
        reader.read(req(), now=NOW)
    assert_closed(reader, backend)


@pytest.mark.parametrize("kind", ["order", "position", "deal"])
def test_account_facts_require_known_exact_symbol_spec_lineage(kind):
    from auvexo_alpha.domain.ds03 import (
        Ds03DealFact,
        Ds03OrderFact,
        Ds03PositionFact,
        PositionsPayload,
        PositionsRequest,
    )

    for correct in (True, False):
        backend, reader = ready()
        fields = dict(
            symbol=SYMBOL,
            spec_hash=spec().content_hash() if correct else "f" * 64,
            quantity=Decimal("1"),
            provider_at=NOW - timedelta(seconds=1),
        )
        if kind == "order":
            backend.payload = OrdersPayload(
                orders=(Ds03OrderFact(order_ref="synthetic.order1", state="OPEN", **fields),)
            )
            request = req(OrdersRequest)
        elif kind == "position":
            backend.payload = PositionsPayload(
                positions=(
                    Ds03PositionFact(
                        position_ref="synthetic.position1", side="BUY", price=Decimal("1"), **fields
                    ),
                )
            )
            request = req(PositionsRequest)
        else:
            backend.payload = DealsPayload(
                deals=(
                    Ds03DealFact(
                        deal_ref="synthetic.deal1", side="BUY", price=Decimal("1"), **fields
                    ),
                )
            )
            request = req(DealsRequest, start=NOW - timedelta(minutes=1), end=NOW, limit=1)
        if correct:
            assert reader.read(request, now=NOW).operation == request.operation
        else:
            with pytest.raises(Ds03Error):
                reader.read(request, now=NOW)
            assert_closed(reader, backend)


def test_history_account_fact_without_discovered_spec_refuses():
    from auvexo_alpha.domain.ds03 import Ds03OrderFact

    backend = Backend()
    reader = Ds03Reader(backend, identity(), rights())
    reader.read(req(SymbolsRequest), now=NOW)
    backend.payload = OrdersPayload(
        orders=(
            Ds03OrderFact(
                order_ref="synthetic.order1",
                symbol=SYMBOL,
                spec_hash=spec().content_hash(),
                state="OPEN",
                quantity="1",
                provider_at=NOW,
            ),
        )
    )
    with pytest.raises(Ds03Error):
        reader.read(req(OrdersRequest), now=NOW)
