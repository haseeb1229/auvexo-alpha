"""R12-5: trade-server time basis is measured, bound by authority, then the only UTC label.

Fake SDK and synthetic samples only; no SDK import, initialize or session.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from mt5_fixtures import fixture, prepared, request
from pydantic import ValidationError
from test_ds03_actual_contracts import NOW, identity, ms, spec, tick
from test_ds03_authority import authority_fixture, failure
from test_ds03_mt5_process import packet, serve
from test_ds03_reason_codes import _Harness

from auvexo_alpha.application.ds03_actual import ActualDs03Reader
from auvexo_alpha.domain.ds03 import Ds03Error, decode_request
from auvexo_alpha.domain.ds03_actual import (
    TIME_BASIS_TOLERANCE_MS,
    ActualEnvelope,
    ActualReply,
    ActualServerTimePayload,
    ActualSpecPayload,
    ActualTickPayload,
    ServerTimeBasis,
    ServerTimeEvidence,
    ServerTimeSample,
    classify_server_time,
    decode_actual_reply,
    decode_actual_request,
    refusal,
    require_server_time_binding,
    server_time,
)
from auvexo_alpha.domain.ds03_authority import admit_authority
from auvexo_alpha.infrastructure import ds03_mt5_process
from auvexo_alpha.infrastructure.ds03_ipc import (
    ProtocolFamily,
    canonical,
    decode_frame,
    encode_frame,
    new_pipe_key,
)
from auvexo_alpha.infrastructure.ds03_mt5 import actual_rights
from auvexo_alpha.infrastructure.ds03_mt5_process import ActualDs03Process

HOUR_MS = 3_600_000
CLOCK = "e" * 64


def samples(lead_ms, *, count=5, step_ms=1000, stale_ms=0, symbol="BTCUSD.demo"):
    """Fresh ticks ``lead_ms`` ahead of local receipt, received 20 ms after the request."""
    base = ms(NOW)
    result = []
    for index in range(count):
        before = base + index * step_ms
        provider = before + lead_ms - stale_ms + 5
        result.append(
            ServerTimeSample(
                symbol=symbol,
                provider_time=provider // 1000,
                provider_time_msc=provider,
                local_before_ms=before,
                local_after_ms=before + 20,
            )
        )
    return tuple(result)


def classify(values):
    return classify_server_time(ServerTimeEvidence(local_clock_evidence_hash=CLOCK, samples=values))


@pytest.mark.parametrize(
    "lead_ms,classification,offset",
    [
        (0, "UTC", 0),
        (-30_000, "UTC", 0),
        (2 * HOUR_MS, "WHOLE_HOUR_OFFSET", 7200),
        (-3 * HOUR_MS + 60_000, "WHOLE_HOUR_OFFSET", -10800),
        (14 * HOUR_MS, "WHOLE_HOUR_OFFSET", 50400),
    ],
)
def test_fresh_samples_classify_utc_or_exact_whole_hour_offset(lead_ms, classification, offset):
    basis = classify(samples(lead_ms))
    assert basis.classification == classification and basis.offset_seconds == offset
    assert basis.local_clock_evidence_hash == CLOCK and basis.sample_count == 5
    evidence = ServerTimeEvidence(local_clock_evidence_hash=CLOCK, samples=samples(lead_ms))
    assert basis.evidence_hash == evidence.content_hash()
    assert basis.measured_at == datetime.fromtimestamp(
        max(s.local_after_ms for s in evidence.samples) / 1000, UTC
    )


@pytest.mark.parametrize(
    "values",
    [
        samples(HOUR_MS // 2),  # A half-hour zone is not a whole-hour basis.
        samples(5 * HOUR_MS + HOUR_MS // 2),
        samples(0, stale_ms=TIME_BASIS_TOLERANCE_MS + 1000),  # Only stale ticks: unbounded.
        samples(0, count=4),  # Too few samples.
        samples(0, step_ms=0),  # Five reads of one tick are one distinct observation.
        samples(15 * HOUR_MS),  # Beyond the largest real zone.
        samples(0)[:4]
        + (
            ServerTimeSample(  # One tick far in the future of every whole-hour candidate.
                symbol="BTCUSD.demo",
                provider_time=(ms(NOW) + 10 * 60_000) // 1000,
                provider_time_msc=ms(NOW) + 10 * 60_000,
                local_before_ms=ms(NOW),
                local_after_ms=ms(NOW) + 20,
            ),
        ),
    ],
)
def test_ambiguous_stale_sparse_or_inconsistent_evidence_is_unknown(values):
    basis = classify(values)
    assert basis.classification == "UNKNOWN" and basis.offset_seconds is None


def market_break(symbols, *, live=(), true_offset_ms=2 * HOUR_MS, age_ms=HOUR_MS):
    """Six reads 500 ms apart; frozen symbols' last ticks are ``age_ms`` old in UTC.

    A ``live`` symbol's tick advances between its reads and is 1 s old when read.
    """
    base, result = ms(NOW), []
    for index in range(6):
        symbol = symbols[index % len(symbols)]
        before = base + index * 500
        event = before - 1000 if symbol in live else base - age_ms - 1000 * (index % 3)
        provider = event + true_offset_ms
        result.append(
            ServerTimeSample(
                symbol=symbol,
                provider_time=provider // 1000,
                provider_time_msc=provider,
                local_before_ms=before,
                local_after_ms=before + 50,
            )
        )
    return tuple(result)


def test_hour_scale_stale_frozen_ticks_cannot_be_absorbed_into_a_smaller_offset():
    # True basis +2 h; every tick is about one hour old and none advances while measured.
    # Freshness alone would read this as +1 h; without proven liveness it is UNKNOWN.
    frozen = market_break(("XAUUSD", "EURUSD", "BTCUSD"))
    assert classify(frozen).classification == "UNKNOWN"
    assert classify(frozen).offset_seconds is None


@pytest.mark.parametrize("live", [("XAUUSD", "EURUSD", "BTCUSD"), ("BTCUSD",)])
def test_one_advancing_live_symbol_proves_the_true_offset(live):
    basis = classify(market_break(("XAUUSD", "EURUSD", "BTCUSD"), live=live))
    assert basis.classification == "WHOLE_HOUR_OFFSET" and basis.offset_seconds == 7200


def test_tick_regression_or_out_of_order_reads_prove_no_liveness():
    values = samples(0, count=6)
    regressed = values[:5] + (
        values[5].model_copy(
            update={
                "provider_time_msc": values[0].provider_time_msc,
                "provider_time": values[0].provider_time,
            }
        ),
    )
    assert classify(regressed).classification == "UNKNOWN"
    reordered = values[:4] + (values[5], values[4])
    assert classify(reordered).classification == "UNKNOWN"


def test_one_changed_sample_changes_the_bound_evidence_hash():
    first = classify(samples(0))
    changed = samples(0)
    changed = changed[:4] + (
        changed[4].model_copy(update={"local_after_ms": changed[4].local_after_ms + 1}),
    )
    assert classify(changed).evidence_hash != first.evidence_hash


@pytest.mark.parametrize(
    "changes",
    [
        {"provider_time": 1},  # Seconds disagree with the millisecond field.
        {"local_after_ms": 0},  # Receipt before request.
        {"local_after_ms": ms(NOW) + 10_001},  # Unbounded receipt bracket.
        {"provider_time_msc": -1},
    ],
)
def test_sample_bracket_and_raw_identity_are_strict(changes):
    values = dict(
        symbol="BTCUSD.demo",
        provider_time=ms(NOW) // 1000,
        provider_time_msc=ms(NOW),
        local_before_ms=ms(NOW),
        local_after_ms=ms(NOW) + 20,
    )
    with pytest.raises((ValueError, ValidationError)):
        ServerTimeSample(**(values | changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"classification": "UTC", "offset_seconds": 3600},
        {"classification": "WHOLE_HOUR_OFFSET", "offset_seconds": 0},
        {"classification": "UNKNOWN", "offset_seconds": 0},
        {"classification": "WHOLE_HOUR_OFFSET", "offset_seconds": None},
        {"classification": "WHOLE_HOUR_OFFSET", "offset_seconds": 1800},
        {"classification": "WHOLE_HOUR_OFFSET", "offset_seconds": 54000},
    ],
)
def test_basis_classification_and_offset_are_coherent(changes):
    values = classify(samples(0)).model_dump() | changes
    with pytest.raises(ValidationError) as captured:
        ServerTimeBasis(**values)
    assert refusal(captured.value, "UNCLASSIFIED").reason in ("TIME_BASIS_MISMATCH", "UNCLASSIFIED")


def test_authority_can_bind_only_a_classified_basis_measured_before_authorization():
    authority, metadata, binding, now = authority_fixture()
    unknown = classify(samples(HOUR_MS // 2))
    late = authority.server_time_basis.model_copy(update={"measured_at": now})
    for basis in (unknown, late):
        changed = authority.model_copy(update={"server_time_basis": basis})
        failure(
            lambda value=changed: admit_authority(
                value, independently_accepted_digest=value.content_hash(), binding=binding, now=now
            ),
            "TIME_BASIS_UNBOUND",
        )
    unbound = authority.model_copy(update={"server_time_basis": None})
    admitted = admit_authority(
        unbound, independently_accepted_digest=unbound.content_hash(), binding=binding, now=now
    )
    assert admitted.authority.time_basis_hash is None
    assert authority.time_basis_hash == authority.server_time_basis.content_hash()
    assert unbound.content_hash() != authority.content_hash()


@pytest.mark.parametrize(
    "operation,fields",
    [
        ("SPEC", {"symbol": "BTCUSD.demo"}),
        ("TICK", {"symbol": "BTCUSD.demo"}),
        ("ORDERS", {}),
        ("POSITIONS", {}),
        ("DEALS", {"limit": 1}),
        ("ORDER_HISTORY", {"limit": 1}),
    ],
)
def test_unbound_session_refuses_every_provider_time_before_any_provider_read(operation, fields):
    f = fixture(basis=None)
    assert f.port.attest().identity.time_basis_hash is None
    f.port.execute(request(f, "SYMBOLS"))
    calls = list(f.sdk.calls)
    if operation in ("DEALS", "ORDER_HISTORY"):
        fields |= {"start": datetime.now(UTC) - timedelta(hours=1), "end": datetime.now(UTC)}
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE:TIME_BASIS_UNBOUND$"):
        f.port.execute(request(f, operation, **fields))
    assert f.sdk.calls[len(calls) :] == [("shutdown",)]


def test_unbound_session_refuses_history_ranges_before_provider_reads():
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    for operation, fields in (
        (
            "BARS",
            {"start": now - timedelta(minutes=2), "end": now, "limit": 2, "timeframe_seconds": 60},
        ),
        ("TICKS", {"start": now - timedelta(minutes=2), "end": now, "limit": 2}),
    ):
        f = fixture(basis=None)
        f.port.execute(request(f, "SYMBOLS"))
        with pytest.raises(Ds03Error, match="TIME_BASIS_UNBOUND"):
            f.port.execute(request(f, operation, symbol="BTCUSD.demo", **fields))
        assert not any(
            c[0] in ("copy_rates_range", "copy_ticks_from", "symbol_info") for c in f.sdk.calls
        )


def moving_tick(lead_ms):
    def update(sdk):
        sdk.counter = getattr(sdk, "counter", 0) + 1
        # About one second old in the provider's basis, distinct across samples.
        provider = int(datetime.now(UTC).timestamp() * 1000) + lead_ms - 1000 + sdk.counter
        sdk.tick.update(time=provider // 1000, time_msc=provider)

    return update


@pytest.mark.parametrize("lead_ms,expected", [(0, 0), (2 * HOUR_MS, 7200), (-5 * HOUR_MS, -18000)])
def test_onboarding_measurement_with_fake_sdk_labels_nothing_and_classifies(lead_ms, expected):
    f = fixture(basis=None)
    f.port.execute(request(f, "SYMBOLS"))
    f.sdk.on_tick = moving_tick(lead_ms)
    pauses = []
    basis = f.port.measure_server_time(
        tuple(f.sdk.symbols),
        samples=6,
        local_clock_evidence_hash=CLOCK,
        clock=lambda: datetime.now(UTC),
        pause=pauses.append,
        interval_seconds=1.5,
    )
    assert basis.offset_seconds == expected and basis.sample_count == 6
    assert pauses == [1.5] * 5
    assert [c[1] for c in f.sdk.calls if c[0] == "symbol_info_tick"] == [
        f.sdk.symbols[i % 2] for i in range(6)
    ]
    assert not any(
        c[0] in ("symbol_info", "copy_rates_range", "copy_ticks_from") for c in f.sdk.calls
    )
    f.port.disconnect()


@pytest.mark.parametrize(
    "symbols,samples_count,interval",
    [
        ((), 6, 0.0),
        (("BTCUSD.demo",), 4, 0.0),
        (("BTCUSD.demo",), 65, 0.0),
        (("BTCUSD.demo",), 6, 61.0),
        (("XAUUSD",), 6, 0.0),
    ],
)
def test_measurement_bounds_and_catalog_admission(symbols, samples_count, interval):
    f = fixture(basis=None)
    f.port.execute(request(f, "SYMBOLS"))
    with pytest.raises(Ds03Error) as captured:
        f.port.measure_server_time(
            symbols,
            samples=samples_count,
            local_clock_evidence_hash=CLOCK,
            clock=lambda: datetime.now(UTC),
            pause=lambda seconds: None,
            interval_seconds=interval,
        )
    assert captured.value.reason in ("REQUEST_INVALID", "SYMBOL_NOT_ADMITTED")
    assert f.sdk.shutdown_count == 1


def test_measurement_requires_completed_catalog_first():
    f = fixture(basis=None)
    with pytest.raises(Ds03Error, match="SYMBOL_NOT_ADMITTED"):
        f.port.measure_server_time(
            ("BTCUSD.demo",),
            samples=5,
            local_clock_evidence_hash=CLOCK,
            clock=lambda: datetime.now(UTC),
            pause=lambda seconds: None,
            interval_seconds=0,
        )


def test_bound_whole_hour_basis_corrects_labels_and_retains_raw_provider_times():
    f = fixture(basis=None)
    f.port.execute(request(f, "SYMBOLS"))
    f.sdk.on_tick = moving_tick(2 * HOUR_MS)
    basis = f.port.measure_server_time(
        tuple(f.sdk.symbols),
        samples=5,
        local_clock_evidence_hash=CLOCK,
        clock=lambda: datetime.now(UTC),
        pause=lambda seconds: None,
        interval_seconds=0,
    )
    f.port.disconnect()
    bound = prepared(fixture(basis=basis))
    bound.sdk.on_tick = moving_tick(2 * HOUR_MS)
    reply = bound.port.execute(request(bound, "TICK", symbol=bound.sdk.symbols[0]))
    tick_fact = reply.payload.tick
    assert (
        tick_fact.server_offset_seconds == 7200
        and tick_fact.time_basis_hash == basis.content_hash()
    )
    assert tick_fact.provider_at == server_time(tick_fact.time_msc, 7200)
    assert tick_fact.provider_at <= reply.envelope.received_at  # Not a future UTC label.
    assert reply.envelope.identity.time_basis_hash == basis.content_hash()
    spec_fact = bound.port.execute(request(bound, "SPEC", symbol=bound.sdk.symbols[0])).payload.spec
    assert spec_fact.provider_quote_time_raw == bound.sdk.specs[bound.sdk.symbols[0]]["time"]
    assert spec_fact.quote_at == server_time(spec_fact.provider_quote_time_raw * 1000, 7200)
    end = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=1)
    start = end - timedelta(minutes=2)
    bound.port.execute(
        request(
            bound,
            "BARS",
            symbol=bound.sdk.symbols[0],
            start=start,
            end=end,
            limit=2,
            timeframe_seconds=60,
        )
    )
    query = [c for c in bound.sdk.calls if c[0] == "copy_rates_range"][-1]
    # UTC request instants are passed in the bound trade-server basis.
    assert query[3:] == (
        start + timedelta(hours=2),
        end - timedelta(seconds=1) + timedelta(hours=2),
    )
    bound.port.disconnect()


def measured_basis(lead_ms):
    f = fixture(basis=None)
    f.port.execute(request(f, "SYMBOLS"))
    f.sdk.on_tick = moving_tick(lead_ms)
    basis = f.port.measure_server_time(
        tuple(f.sdk.symbols),
        samples=5,
        local_clock_evidence_hash=CLOCK,
        clock=lambda: datetime.now(UTC),
        pause=lambda seconds: None,
        interval_seconds=0,
    )
    f.port.disconnect()
    return basis


def daily_bar(server_midnight):
    return {
        "time": int(server_midnight.timestamp()),
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "tick_volume": 10,
        "spread": 2,
        "real_volume": 0,
    }


@pytest.mark.parametrize("offset_hours", [0, 2])
def test_daily_bars_open_at_server_midnight_and_keep_true_utc_labels(offset_hours):
    f = fixture() if not offset_hours else fixture(basis=measured_basis(offset_hours * HOUR_MS))
    reader = reader_for(f)
    reader.read(request(f, "SYMBOLS"), now=datetime.now(UTC))
    symbol = f.sdk.symbols[0]
    reader.read(request(f, "SPEC", symbol=symbol), now=datetime.now(UTC))
    # Raw MT5 D1 times are trade-server midnights; UTC labels are those minus the offset.
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    server_days = (today - timedelta(days=3), today - timedelta(days=2))
    f.sdk.rate_rows = [daily_bar(day) for day in server_days]
    shift = timedelta(hours=offset_hours)
    start, end = server_days[0] - shift, server_days[1] + timedelta(days=1) - shift
    reply = reader.read(
        request(f, "BARS", symbol=symbol, start=start, end=end, limit=2, timeframe_seconds=86400),
        now=datetime.now(UTC),
    )
    bars = reply.payload.bars
    assert [bar.provider_at for bar in bars] == [day - shift for day in server_days]
    assert [bar.provider_time_raw for bar in bars] == [int(d.timestamp()) for d in server_days]
    assert not reply.payload.gaps
    query = [c for c in f.sdk.calls if c[0] == "copy_rates_range"][-1]
    assert query[3] == server_days[0] and query[2] == 16408
    if offset_hours:
        # A UTC-midnight D1 window is not a trade-server day under a +2 h basis.
        calls = len(f.sdk.calls)
        with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE:REQUEST_INVALID$"):
            reader.read(
                request(
                    f,
                    "BARS",
                    symbol=symbol,
                    start=server_days[0],
                    end=server_days[1],
                    limit=1,
                    timeframe_seconds=86400,
                ),
                now=datetime.now(UTC),
            )
        assert not any(c[0] == "copy_rates_range" for c in f.sdk.calls[calls:])
    f.port.disconnect()


def test_unshifted_server_time_under_a_utc_basis_would_be_a_future_label_and_refuses():
    f = prepared(fixture())
    f.sdk.on_tick = moving_tick(2 * HOUR_MS)
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE:PROVIDER_FUTURE_TIME$"):
        f.port.execute(request(f, "TICK", symbol=f.sdk.symbols[0]))


def test_dto_refuses_utc_labels_without_or_against_the_identity_basis():
    unbound = identity(time_basis_hash=None, server_offset_seconds=None)
    payload = ActualTickPayload(tick=tick())
    base = dict(
        provider_at=NOW,
        first_seen_at=NOW,
        received_at=NOW,
        processed_at=NOW,
        available_at=NOW,
        raw_hash="c" * 64,
        normalized_hash=payload.content_hash(),
        connector_hash="5" * 64,
        symbol="BTCUSDm",
        spec_hash=spec().content_hash(),
        protocol_family="DS03_MT5_READONLY_V1",
        synthetic=False,
    )
    with pytest.raises(ValidationError) as captured:
        ActualEnvelope(identity=unbound, provider_time_kind="SDK_EVENT_TIME", **base)
    assert refusal(captured.value, "UNCLASSIFIED").reason == "TIME_BASIS_UNBOUND"
    local = ActualEnvelope(
        identity=unbound, provider_time_kind="LOCAL_OBSERVATION_NO_PROVIDER_TIMESTAMP", **base
    )
    with pytest.raises(ValidationError) as captured:
        ActualReply(
            request_id="00000000-0000-4000-8000-000000000000",
            operation="TICK",
            payload=payload,
            envelope=local,
            protocol_family="DS03_MT5_READONLY_V1",
        )
    assert refusal(captured.value, "UNCLASSIFIED").reason == "TIME_BASIS_UNBOUND"
    other = ActualSpecPayload(spec=spec(time_basis_hash="9" * 64))
    bound = ActualEnvelope(
        identity=identity(),
        provider_time_kind="SDK_EVENT_TIME",
        **(base | {"normalized_hash": other.content_hash()}),
    )
    with pytest.raises(ValidationError) as captured:
        ActualReply(
            request_id="00000000-0000-4000-8000-000000000000",
            operation="SPEC",
            payload=other,
            envelope=bound,
            protocol_family="DS03_MT5_READONLY_V1",
        )
    assert refusal(captured.value, "UNCLASSIFIED").reason == "TIME_BASIS_MISMATCH"


@pytest.mark.parametrize(
    "changes",
    [
        {"server_offset_seconds": 3600},  # Label no longer equals raw minus offset.
        {"time_msc": ms(NOW) + 1},
        {"server_offset_seconds": 1800},
        {"time_basis_hash": "nothex"},
    ],
)
def test_record_label_must_equal_raw_time_minus_bound_offset(changes):
    with pytest.raises((ValueError, ValidationError)):
        tick(**changes)
    shifted = tick(at=NOW - timedelta(hours=1), time_msc=ms(NOW), server_offset_seconds=3600)
    assert shifted.provider_at == NOW - timedelta(hours=1) and shifted.time_msc == ms(NOW)


def test_identity_basis_fields_are_paired():
    for changes in ({"time_basis_hash": None}, {"server_offset_seconds": None}):
        with pytest.raises(ValidationError):
            identity(**changes)


def test_parent_pin_refuses_identity_basis_that_differs_from_the_authority(monkeypatch):
    f = fixture()
    observed = f.port.attest()
    monkeypatch.setattr(
        ds03_mt5_process.measured, "probe_terminal_process", lambda bound: f.observer.evidence
    )
    assert ds03_mt5_process._pin_identity(observed, f.static) == observed.identity
    drifted = observed.model_copy(
        update={"identity": observed.identity.model_copy(update={"server_offset_seconds": 3600})}
    )
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE:TIME_BASIS_MISMATCH$"):
        ds03_mt5_process._pin_identity(drifted, f.static)
    f.port.disconnect()


# --- SERVER_TIME: the measurement as one read-only parent/child operation ----------------

FAMILY = ProtocolFamily.MT5_READONLY


def measurement_request(f, **fields):
    values = {
        "symbols": tuple(f.sdk.symbols),
        "samples": 6,
        "interval_ms": 0,
        "local_clock_evidence_hash": CLOCK,
    }
    return request(f, "SERVER_TIME", **(values | fields))


def tick_calls(f, since=0):
    return [c for c in f.sdk.calls[since:] if c[0] == "symbol_info_tick"]


def reader_for(f):
    return ActualDs03Reader(
        f.port,
        f.port.attest().identity,
        actual_rights(f.admission),
        clock=lambda: datetime.now(UTC),
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"symbols": ()},
        {"symbols": ("BTCUSD.demo", "BTCUSD.demo")},
        {"symbols": ("bad symbol",)},
        {"samples": 4},
        {"samples": 65},
        {"samples": True},
        {"interval_ms": -1},
        {"interval_ms": 0.5},
        {"interval_ms": 1001},  # Five pauses would exceed the in-deadline pause budget.
        {"local_clock_evidence_hash": "nothex"},
    ],
)
def test_measurement_request_is_closed_and_fits_one_request_deadline(changes):
    f = fixture(basis=None, initialize=False)
    assert measurement_request(f, interval_ms=1000).samples == 6  # Exactly the budget.
    with pytest.raises(ValueError):
        measurement_request(f, **changes)


def test_synthetic_request_family_stays_without_a_measurement_operation():
    f = fixture(basis=None, initialize=False)
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE$"):
        decode_request(measurement_request(f).canonical_bytes())


@pytest.mark.parametrize("lead_ms,expected", [(0, 0), (2 * HOUR_MS, 7200)])
def test_server_time_operation_reads_only_allowlisted_ticks_and_labels_nothing(lead_ms, expected):
    f = fixture(basis=None)
    f.port.execute(request(f, "SYMBOLS"))
    f.sdk.on_tick = moving_tick(lead_ms)
    before = len(f.sdk.calls)
    message = measurement_request(f, interval_ms=1)
    reply = f.port.execute(message)
    # No initialize, login, spec, history or any non-allowlisted call: six tick reads only.
    assert f.sdk.calls[before:] == [("symbol_info_tick", f.sdk.symbols[i % 2]) for i in range(6)]
    payload, envelope = reply.payload, reply.envelope
    assert reply.operation == "SERVER_TIME" and payload.basis.offset_seconds == expected
    assert payload.basis == classify_server_time(payload.evidence)
    assert payload.basis.local_clock_evidence_hash == CLOCK
    assert envelope.provider_time_kind == "LOCAL_OBSERVATION_NO_PROVIDER_TIMESTAMP"
    assert envelope.identity.time_basis_hash is None and envelope.symbol is None
    require_server_time_binding(message, payload, envelope)
    f.port.disconnect()


def test_server_time_operation_requires_completed_catalog_and_admitted_symbols():
    f = fixture(basis=None)
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE:SYMBOL_NOT_ADMITTED$"):
        f.port.execute(measurement_request(f))
    assert not tick_calls(f) and f.sdk.shutdown_count == 1
    g = fixture(basis=None)
    g.port.execute(request(g, "SYMBOLS"))
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE:SYMBOL_NOT_ADMITTED$"):
        g.port.execute(measurement_request(g, symbols=("XAUUSD",)))
    assert not tick_calls(g) and g.sdk.shutdown_count == 1


def test_measurement_payload_basis_must_be_rederived_from_its_samples():
    evidence = ServerTimeEvidence(local_clock_evidence_hash=CLOCK, samples=samples(0))
    honest = classify_server_time(evidence)
    assert ActualServerTimePayload(evidence=evidence, basis=honest).basis == honest
    with pytest.raises(ValidationError) as captured:
        ActualServerTimePayload(evidence=evidence, basis=classify(samples(2 * HOUR_MS)))
    assert refusal(captured.value, "UNCLASSIFIED").reason == "TIME_BASIS_MISMATCH"


@pytest.mark.parametrize("change", ["clock", "count", "order", "early", "late", "labelled"])
def test_measurement_reply_must_answer_exactly_its_request(change):
    f = fixture(basis=None)
    f.port.execute(request(f, "SYMBOLS"))
    f.sdk.on_tick = moving_tick(0)
    message = measurement_request(f)
    reply = f.port.execute(message)
    payload, envelope = reply.payload, reply.envelope
    if change == "clock":
        message = message.model_copy(update={"local_clock_evidence_hash": "f" * 64})
    elif change == "count":
        message = message.model_copy(update={"samples": 5})
    elif change == "order":
        message = message.model_copy(update={"symbols": tuple(reversed(message.symbols))})
    elif change == "early":
        later = envelope.received_at + timedelta(seconds=1)
        message = message.model_copy(update={"created_at": later})
    elif change == "late":
        earlier = message.created_at - timedelta(seconds=1)
        envelope = envelope.model_copy(update={"received_at": earlier})
    else:
        envelope = envelope.model_copy(update={"provider_time_kind": "SDK_EVENT_TIME"})
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE:REPLY_INVALID$"):
        require_server_time_binding(message, payload, envelope)
    f.port.disconnect()


def test_reader_admits_measurement_only_after_the_completed_catalog():
    f = fixture(basis=None)
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE:SYMBOL_NOT_ADMITTED$"):
        reader_for(f).read(measurement_request(f), now=datetime.now(UTC))
    assert not tick_calls(f) and f.sdk.shutdown_count == 1
    g = fixture(basis=None)
    reader = reader_for(g)
    reader.read(request(g, "SYMBOLS"), now=datetime.now(UTC))
    g.sdk.on_tick = moving_tick(2 * HOUR_MS)
    reply = reader.read(measurement_request(g), now=datetime.now(UTC))
    assert reply.payload.basis.offset_seconds == 7200 and len(tick_calls(g)) == 6
    g.port.disconnect()


def test_child_session_serves_measurement_frames_without_floats_or_labels():
    f = fixture(basis=None)
    f.sdk.on_tick = moving_tick(0)
    key, session = new_pipe_key(), uuid4()
    messages = [request(f, "SYMBOLS"), measurement_request(f), request(f, "DISCONNECT")]
    incoming = b"".join(
        packet(m, key=key, session=session, sequence=i) for i, m in enumerate(messages, 1)
    )
    code, frames = serve(f, incoming, key, session)
    assert code == 0 and len(frames) == 4
    frame = decode_frame(
        frames[2], key=key, session=session, sequence=2, kind="REPLY", family=FAMILY
    )
    reply = decode_actual_reply(canonical(frame.payload))
    assert reply.payload.kind == "SERVER_TIME" and reply.payload.basis.classification == "UTC"
    require_server_time_binding(messages[1], reply.payload, reply.envelope)
    assert len(tick_calls(f)) == 6 and f.sdk.shutdown_count == 1


def _measuring_child(monkeypatch, f, *, forge=False):
    """Parent harness whose fake child answers through the real reader over the fake SDK."""
    reader = reader_for(f)
    hello = {
        "binding": f.admission.binding.connector_source_hash,
        "attestation": f.port.attest().model_dump(mode="json"),
        "rights": actual_rights(f.admission).model_dump(mode="json"),
    }

    def answer(key, session, sequence, request_id):
        return encode_frame(
            "HELLO", hello, key=key, session=session, sequence=0, request_id=None, family=FAMILY
        )

    harness = _Harness(monkeypatch, f, answer)
    bootstrap = ds03_mt5_process._exchange
    state = harness.state

    def exchange(reader_pipe, writer_pipe, raw):
        if len(raw.splitlines()) == 2:
            return bootstrap(reader_pipe, writer_pipe, raw)
        sequence = state.setdefault("sequence", 1)
        state["sequence"] += 1
        incoming = decode_frame(
            raw,
            key=state["key"],
            session=state["session"],
            sequence=sequence,
            kind="REQUEST",
            family=FAMILY,
        )
        message = decode_actual_request(canonical(incoming.payload))
        if forge and message.operation == "SERVER_TIME":
            # A valid answer to a different question: one sample fewer than requested.
            message = message.model_copy(update={"samples": message.samples - 1})
        reply = reader.read(message, now=datetime.now(UTC))
        return encode_frame(
            "REPLY",
            reply.model_dump(mode="json"),
            key=state["key"],
            session=state["session"],
            sequence=sequence,
            request_id=message.request_id,
            family=FAMILY,
        )

    monkeypatch.setattr(ds03_mt5_process, "_exchange", exchange)
    return harness


def test_parent_measurement_round_trip_returns_the_rederived_basis(monkeypatch):
    f = fixture(basis=None)
    harness = _measuring_child(monkeypatch, f)
    process = ActualDs03Process(f.static).start()
    process.read(request(f, "SYMBOLS"))
    f.sdk.on_tick = moving_tick(2 * HOUR_MS)
    basis = process.measure_server_time(
        tuple(f.sdk.symbols), samples=6, interval_ms=1, local_clock_evidence_hash=CLOCK
    )
    assert basis.classification == "WHOLE_HOUR_OFFSET" and basis.offset_seconds == 7200
    assert basis.sample_count == 6 and basis.local_clock_evidence_hash == CLOCK
    assert len(tick_calls(f)) == 6 and not harness.state["closed"]
    process.disconnect()
    assert harness.state["closed"] and f.sdk.shutdown_count == 1


def test_parent_refuses_a_measurement_answering_another_request_and_closes(monkeypatch):
    f = fixture(basis=None)
    harness = _measuring_child(monkeypatch, f, forge=True)
    process = ActualDs03Process(f.static).start()
    process.read(request(f, "SYMBOLS"))
    f.sdk.on_tick = moving_tick(0)
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE:REPLY_INVALID$"):
        process.measure_server_time(
            tuple(f.sdk.symbols), samples=6, interval_ms=0, local_clock_evidence_hash=CLOCK
        )
    assert harness.state["closed"]
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE:SESSION_CLOSED$"):
        process.measure_server_time(
            tuple(f.sdk.symbols), samples=6, interval_ms=0, local_clock_evidence_hash=CLOCK
        )
    f.port.disconnect()


def test_parent_refuses_an_invalid_measurement_request_before_any_frame(monkeypatch):
    f = fixture(basis=None)
    harness = _measuring_child(monkeypatch, f)
    process = ActualDs03Process(f.static).start()
    sent = harness.state.get("sequence")
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE:REQUEST_INVALID$"):
        process.measure_server_time(
            tuple(f.sdk.symbols), samples=4, interval_ms=0, local_clock_evidence_hash=CLOCK
        )
    assert harness.state.get("sequence") == sent and harness.state["closed"]
    assert not tick_calls(f)
    f.port.disconnect()
