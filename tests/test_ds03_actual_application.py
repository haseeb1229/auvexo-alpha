"""Actual-family shared-session tests; every provider fact is synthetic test data."""

import hashlib
from datetime import timedelta
from threading import Event, Thread

import pytest
from test_ds03_actual_contracts import (
    NOW,
    PROTOCOL_FAMILY,
    SYMBOL,
    attest,
    bar,
    envelope,
    identity,
    req,
    rights,
    spec,
    tick,
)

from auvexo_alpha.application.ds03_actual import ActualDs03Reader
from auvexo_alpha.domain.ds03 import AttestRequest, DealsRequest, Ds03Error, OrdersRequest
from auvexo_alpha.domain.ds03_actual import (
    ActualAttestationPayload,
    ActualBarsPayload,
    ActualBarsRequest,
    ActualDealFact,
    ActualDealsPayload,
    ActualOrderFact,
    ActualOrdersPayload,
    ActualReply,
    ActualSpecPayload,
    ActualSpecRequest,
    ActualSymbolsPayload,
    ActualSymbolsRequest,
    ActualTickPayload,
    ActualTickRequest,
    catalog_digest,
)


class ActualBackend:
    def __init__(self, catalog=(SYMBOL,)):
        self.catalog = catalog
        self.now = NOW
        self.identity = identity()
        self.payload = None
        self.response_hook = None
        self.execute_hook = None
        self.attest_hook = None
        self.calls = 0
        self.closed = False
        self.raw = None

    def attest(self):
        if self.attest_hook:
            return self.attest_hook(self)
        return attest(at=self.now, identity=self.identity)

    def disconnect(self):
        self.closed = True

    def execute(self, request):
        self.calls += 1
        if self.execute_hook:
            self.execute_hook(self)
        symbol = None
        if self.payload is not None:
            payload = self.payload
            if hasattr(request, "symbol"):
                symbol = request.symbol
        elif request.operation == "SYMBOLS":
            offset = request.offset
            page = self.catalog[offset : offset + 128]
            payload = ActualSymbolsPayload(
                symbols=page,
                catalog_hash=catalog_digest(self.catalog),
                total=len(self.catalog),
                offset=offset,
                complete=offset + len(page) == len(self.catalog),
            )
        elif request.operation == "SPEC":
            symbol = request.symbol
            payload = ActualSpecPayload(spec=spec(symbol=symbol))
        elif request.operation == "TICK":
            symbol = request.symbol
            payload = ActualTickPayload(tick=tick(at=self.now, symbol=symbol))
        elif request.operation == "ORDERS":
            payload = ActualOrdersPayload(orders=())
        elif request.operation == "ATTEST":
            payload = ActualAttestationPayload(attestation=self.attest())
        else:
            raise AssertionError("explicit synthetic test payload required")
        raw = (
            self.raw
            or hashlib.sha256(payload.canonical_bytes() + str(self.now).encode()).hexdigest()
        )
        bound = envelope(payload, at=self.now, symbol=symbol, raw_hash=raw, identity=self.identity)
        result = ActualReply(
            request_id=request.request_id,
            operation=request.operation,
            payload=payload,
            envelope=bound,
            protocol_family=PROTOCOL_FAMILY,
        )
        return self.response_hook(result) if self.response_hook else result


def ready():
    backend = ActualBackend()
    reader = ActualDs03Reader(backend, identity(), rights())
    reader.read(req(ActualSymbolsRequest), now=NOW)
    reader.read(req(ActualSpecRequest), now=NOW)
    return backend, reader


def assert_closed(backend, reader):
    assert backend.closed
    count = backend.calls
    with pytest.raises(Ds03Error):
        reader.read(req(AttestRequest), now=backend.now)
    assert backend.calls == count


def test_actual_broker_symbol_and_digest_identity_pass_shared_guard():
    backend, reader = ready()
    result = reader.read(req(ActualTickRequest), now=NOW)
    assert result.payload.tick.symbol == SYMBOL
    assert result.envelope.synthetic is False
    assert result.envelope.clock_status == "STRUCTURAL_ONLY_CLOCK_BLOCKED"
    assert result.envelope.identity.account_type_source == "OWNER_METADATA_ONLY_NOT_EXPOSED_BY_MT5"


def test_catalog_incomplete_never_admits_symbols_and_completion_binds_all_pages():
    names = (SYMBOL,) + tuple(f"FX{i}" for i in range(128))
    backend = ActualBackend(names)
    reader = ActualDs03Reader(backend, identity(), rights())
    first = reader.read(req(ActualSymbolsRequest), now=NOW)
    assert not first.payload.complete
    count = backend.calls
    with pytest.raises(Ds03Error):
        reader.read(req(ActualSpecRequest), now=NOW)
    assert backend.calls == count
    backend = ActualBackend(names)
    reader = ActualDs03Reader(backend, identity(), rights())
    reader.read(req(ActualSymbolsRequest), now=NOW)
    final = reader.read(
        req(ActualSymbolsRequest, offset=128, catalog_hash=catalog_digest(names)), now=NOW
    )
    assert final.payload.complete
    assert reader.read(req(ActualSpecRequest), now=NOW).payload.spec.symbol == SYMBOL


@pytest.mark.parametrize("case", ["skip", "wronghash", "totaldrift", "duplicate", "falsedigest"])
def test_catalog_cursor_digest_drift_and_duplicate_fail_whole_session(case):
    names = (SYMBOL,) + tuple(f"FX{i}" for i in range(128))
    backend = ActualBackend(names)
    reader = ActualDs03Reader(backend, identity(), rights())
    if case == "falsedigest":
        backend = ActualBackend((SYMBOL,))
        reader = ActualDs03Reader(backend, identity(), rights())
        backend.payload = ActualSymbolsPayload(
            symbols=(SYMBOL,), catalog_hash="f" * 64, total=1, offset=0, complete=True
        )
        request = req(ActualSymbolsRequest)
    else:
        reader.read(req(ActualSymbolsRequest), now=NOW)
        request = req(ActualSymbolsRequest, offset=128, catalog_hash=catalog_digest(names))
        if case == "skip":
            request = request.model_copy(update={"offset": 127})
        elif case == "wronghash":
            request = request.model_copy(update={"catalog_hash": "f" * 64})
        elif case == "totaldrift":
            backend.catalog = names + ("EXTRA",)
        elif case == "duplicate":
            backend.payload = ActualSymbolsPayload(
                symbols=(SYMBOL,),
                catalog_hash=catalog_digest(names),
                total=129,
                offset=128,
                complete=True,
            )
    with pytest.raises(Ds03Error):
        reader.read(request, now=NOW)
    assert_closed(backend, reader)


def test_full_4096_catalog_fits_bounded_pages_without_truncation():
    names = tuple(f"FX{i}" for i in range(4096))
    backend = ActualBackend(names)
    reader = ActualDs03Reader(backend, identity(), rights())
    for offset in range(0, len(names), 128):
        result = reader.read(
            req(
                ActualSymbolsRequest,
                offset=offset,
                catalog_hash=catalog_digest(names) if offset else None,
            ),
            now=NOW,
        )
        assert len(result.payload.symbols) == 128
    assert result.payload.complete and result.payload.total == 4096


def test_actual_overlapping_bars_preserve_individual_first_seen_not_batch_time():
    backend, reader = ready()
    start = NOW - timedelta(minutes=2)
    old = bar(start, first_seen=NOW)
    backend.payload = ActualBarsPayload(bars=(old,), coverage="COMPLETE")
    first = req(
        ActualBarsRequest,
        start=start,
        end=start + timedelta(minutes=1),
        limit=1,
        timeframe_seconds=60,
    )
    reader.read(first, now=NOW)
    backend.now = NOW + timedelta(seconds=1)
    new = bar(start + timedelta(minutes=1), first_seen=backend.now, source_ref="d" * 64)
    backend.payload = ActualBarsPayload(bars=(old, new), coverage="COMPLETE")
    second = req(
        ActualBarsRequest, at=backend.now, start=start, end=NOW, limit=2, timeframe_seconds=60
    )
    result = reader.read(second, now=backend.now)
    assert result.payload.bars[0].first_seen_at == NOW
    assert result.envelope.first_seen_at == backend.now
    assert result.payload.bars[1].first_seen_at == backend.now


@pytest.mark.parametrize("change", ["refresh", "conflict", "future"])
def test_overlap_first_seen_refresh_conflicting_values_and_future_refuse(change):
    backend, reader = ready()
    start = NOW - timedelta(minutes=1)
    old = bar(start, first_seen=NOW)
    backend.payload = ActualBarsPayload(bars=(old,), coverage="COMPLETE")
    reader.read(
        req(ActualBarsRequest, start=start, end=NOW, limit=1, timeframe_seconds=60), now=NOW
    )
    backend.now = NOW + timedelta(seconds=1)
    if change == "refresh":
        modified = old.model_copy(update={"first_seen_at": backend.now})
    elif change == "conflict":
        modified = old.model_copy(update={"close": old.open, "source_ref": "f" * 64})
    else:
        modified = old.model_copy(update={"first_seen_at": backend.now + timedelta(seconds=1)})
    backend.payload = ActualBarsPayload(bars=(modified,), coverage="COMPLETE")
    with pytest.raises(Ds03Error):
        reader.read(
            req(
                ActualBarsRequest,
                at=backend.now,
                start=start,
                end=NOW,
                limit=1,
                timeframe_seconds=60,
            ),
            now=backend.now,
        )
    assert_closed(backend, reader)


def test_nonmarket_balance_fact_is_preserved_without_invented_symbol_or_trade():
    backend = ActualBackend()
    reader = ActualDs03Reader(backend, identity(), rights())
    fact = ActualDealFact(
        deal_ref="ds03.deal." + "a" * 64,
        kind="NON_MARKET",
        symbol=None,
        spec_hash=None,
        provider_type=2,
        entry=0,
        quantity="0",
        price="0",
        profit="100",
        commission="0",
        swap="0",
        fee="0",
        provider_at=NOW - timedelta(seconds=1),
        first_seen_at=NOW,
        source_ref="e" * 64,
    )
    backend.payload = ActualDealsPayload(deals=(fact,))
    result = reader.read(
        req(DealsRequest, start=NOW - timedelta(minutes=1), end=NOW, limit=1), now=NOW
    )
    assert result.payload.deals[0].provider_type == 2
    assert result.payload.deals[0].symbol is None
    assert result.payload.deals[0].quantity == 0


def test_actual_partial_order_enum_and_known_spec_bindings_survive_guard():
    backend, reader = ready()
    fact = ActualOrderFact(
        order_ref="ds03.order." + "f" * 64,
        symbol=SYMBOL,
        spec_hash=spec().content_hash(),
        provider_state=3,
        provider_type=2,
        volume_initial="1",
        volume_current="0.5",
        price_open="100",
        setup_at=NOW - timedelta(seconds=1),
        done_at=None,
        provider_at=NOW,
        first_seen_at=NOW,
        source_ref="e" * 64,
    )
    backend.payload = ActualOrdersPayload(orders=(fact,))
    result = reader.read(req(OrdersRequest), now=NOW)
    assert result.payload.orders[0].provider_state == 3
    assert result.payload.orders[0].volume_current.as_tuple().exponent == -1


def test_wrong_spec_or_unsupported_enum_cannot_be_dropped_from_history():
    for field, value in (("spec_hash", "f" * 64), ("provider_type", 99)):
        backend, reader = ready()
        fact = ActualOrderFact(
            order_ref="ds03.order." + "f" * 64,
            symbol=SYMBOL,
            spec_hash=spec().content_hash(),
            provider_state=1,
            provider_type=0,
            volume_initial="1",
            volume_current="1",
            price_open="100",
            setup_at=NOW,
            done_at=None,
            provider_at=NOW,
            first_seen_at=NOW,
            source_ref="e" * 64,
        )
        backend.payload = ActualOrdersPayload(orders=(fact,))

        def corrupt(reply, fact=fact, field=field, value=value):
            bad_fact = fact.model_copy(update={field: value})
            payload = reply.payload.model_copy(update={"orders": (fact, bad_fact)})
            bound = reply.envelope.model_copy(update={"normalized_hash": payload.content_hash()})
            return reply.model_copy(update={"payload": payload, "envelope": bound})

        backend.response_hook = corrupt
        with pytest.raises(Ds03Error):
            reader.read(req(OrdersRequest), now=NOW)
        assert_closed(backend, reader)


@pytest.mark.parametrize(
    "field,value",
    [
        ("server", "ds03.server." + "f" * 64),
        ("login_hash", "f" * 64),
        ("process_ref", "ds03.process." + "f" * 64),
        ("profile_hash", "f" * 64),
        ("currency", "EUR"),
        ("leverage", 200),
    ],
)
def test_actual_pre_observation_identity_mismatch_refuses_before_provider_read(field, value):
    backend = ActualBackend()
    backend.identity = identity(**{field: value})
    reader = ActualDs03Reader(backend, identity(), rights())
    with pytest.raises(Ds03Error):
        reader.read(req(AttestRequest), now=NOW)
    assert backend.calls == 0
    assert_closed(backend, reader)


def test_actual_post_read_swap_closes_session_and_discards_reply():
    backend = ActualBackend()
    reader = ActualDs03Reader(backend, identity(), rights())
    backend.execute_hook = lambda port: setattr(
        port, "identity", identity(server="ds03.server." + "f" * 64)
    )
    with pytest.raises(Ds03Error):
        reader.read(req(AttestRequest), now=NOW)
    assert_closed(backend, reader)


def test_actual_monotonic_rights_and_request_deadline_use_same_engine():
    backend = ActualBackend()
    samples = iter((1.0, 3.0))
    reader = ActualDs03Reader(
        backend,
        identity(),
        rights(valid_until=NOW + timedelta(seconds=1)),
        monotonic_clock=lambda: next(samples),
    )
    with pytest.raises(Ds03Error):
        reader.read(req(AttestRequest), now=NOW)
    assert_closed(backend, reader)


def test_actual_reentrant_session_closes_before_any_response_admission():
    backend = ActualBackend()
    reader = ActualDs03Reader(backend, identity(), rights())

    def recursive(port):
        with pytest.raises(Ds03Error):
            reader.read(req(AttestRequest), now=NOW)

    backend.execute_hook = recursive
    with pytest.raises(Ds03Error):
        reader.read(req(AttestRequest), now=NOW)
    assert_closed(backend, reader)


def test_actual_concurrent_session_refuses_both_and_accepts_no_partial_data():
    backend = ActualBackend()
    reader = ActualDs03Reader(backend, identity(), rights())
    entered = Event()
    release = Event()
    errors = []

    def block(port):
        entered.set()
        assert release.wait(3)

    backend.execute_hook = block

    def run():
        try:
            reader.read(req(AttestRequest), now=NOW)
        except Ds03Error:
            errors.append("denied")

    worker = Thread(target=run)
    worker.start()
    assert entered.wait(3)
    with pytest.raises(Ds03Error):
        reader.read(req(AttestRequest), now=NOW)
    release.set()
    worker.join(3)
    assert errors == ["denied"] and not worker.is_alive()
    assert backend.calls == 1


def test_actual_older_history_query_is_distinct_from_event_stream_regression():
    backend, reader = ready()
    recent = NOW - timedelta(minutes=2)
    backend.payload = ActualBarsPayload(bars=(bar(recent),), coverage="COMPLETE")
    backend.response_hook = lambda reply: reply.model_copy(
        update={
            "envelope": reply.envelope.model_copy(
                update={"provider_at": reply.payload.bars[-1].provider_at}
            )
        }
    )
    reader.read(
        req(
            ActualBarsRequest,
            start=recent,
            end=recent + timedelta(minutes=1),
            limit=1,
            timeframe_seconds=60,
        ),
        now=NOW,
    )
    old = NOW - timedelta(days=100)
    backend.payload = ActualBarsPayload(bars=(bar(old),), coverage="COMPLETE")
    result = reader.read(
        req(
            ActualBarsRequest,
            start=old,
            end=old + timedelta(minutes=1),
            limit=1,
            timeframe_seconds=60,
        ),
        now=NOW,
    )
    assert result.payload.bars[0].provider_at == old


def test_actual_same_query_event_time_regression_still_denies():
    backend, reader = ready()
    start = NOW - timedelta(minutes=2)
    backend.payload = ActualBarsPayload(
        bars=(bar(start + timedelta(minutes=1)),), coverage="UNKNOWN"
    )
    backend.response_hook = lambda reply: reply.model_copy(
        update={
            "envelope": reply.envelope.model_copy(
                update={"provider_at": reply.payload.bars[-1].provider_at}
            )
        }
    )
    reader.read(
        req(ActualBarsRequest, start=start, end=NOW, limit=2, timeframe_seconds=60), now=NOW
    )
    backend.payload = ActualBarsPayload(bars=(bar(start),), coverage="UNKNOWN")
    with pytest.raises(Ds03Error):
        reader.read(
            req(ActualBarsRequest, start=start, end=NOW, limit=2, timeframe_seconds=60), now=NOW
        )
    assert_closed(backend, reader)


def test_distinct_bar_timeframes_at_same_open_are_distinct_immutable_facts():
    backend, reader = ready()
    start = NOW - timedelta(hours=1)
    minute = bar(start, timeframe_seconds=60)
    backend.payload = ActualBarsPayload(bars=(minute,), coverage="COMPLETE")
    reader.read(
        req(
            ActualBarsRequest,
            start=start,
            end=start + timedelta(minutes=1),
            limit=1,
            timeframe_seconds=60,
        ),
        now=NOW,
    )
    hourly = bar(start, timeframe_seconds=3600, close=minute.open, source_ref="f" * 64)
    backend.payload = ActualBarsPayload(bars=(hourly,), coverage="COMPLETE")
    result = reader.read(
        req(ActualBarsRequest, start=start, end=NOW, limit=1, timeframe_seconds=3600), now=NOW
    )
    assert result.payload.bars[0].timeframe_seconds == 3600
    assert result.payload.bars[0].close == minute.open


def test_actual_bar_interval_must_match_requested_interval():
    backend, reader = ready()
    start = NOW - timedelta(minutes=5)
    backend.payload = ActualBarsPayload(
        bars=(bar(start, timeframe_seconds=300),), coverage="UNKNOWN"
    )
    with pytest.raises(Ds03Error):
        reader.read(
            req(
                ActualBarsRequest,
                start=start,
                end=start + timedelta(minutes=1),
                limit=1,
                timeframe_seconds=60,
            ),
            now=NOW,
        )
    assert_closed(backend, reader)


def test_close_during_post_validation_cannot_admit_late_reply():
    backend, reader = ready()
    original = reader._validate_reply

    def validate_then_close(request, reply, now):
        original(request, reply, now)
        reader._close()

    reader._validate_reply = validate_then_close
    with pytest.raises(Ds03Error):
        reader.read(req(ActualTickRequest), now=NOW)
    assert_closed(backend, reader)


@pytest.mark.parametrize("kind", ["request_ttl", "rights_ttl", "utc_regression"])
def test_validation_work_cannot_cross_deadline_or_rewind_clock(kind):
    backend = ActualBackend()
    elapsed = [0.0]
    utc = [NOW]
    bound_rights = (
        rights(valid_until=NOW + timedelta(seconds=1)) if kind == "rights_ttl" else rights()
    )
    reader = ActualDs03Reader(
        backend, identity(), bound_rights, clock=lambda: utc[0], monotonic_clock=lambda: elapsed[0]
    )
    original = reader._validate_reply

    def validate_then_advance(request, reply, now):
        original(request, reply, now)
        if kind == "utc_regression":
            utc[0] = NOW - timedelta(microseconds=1)
        else:
            elapsed[0] = 2.0

    reader._validate_reply = validate_then_advance
    request = req(AttestRequest)
    if kind == "request_ttl":
        request = request.model_copy(update={"expires_at": NOW + timedelta(seconds=1)})
    with pytest.raises(Ds03Error):
        reader.read(request, now=NOW)
    assert_closed(backend, reader)
