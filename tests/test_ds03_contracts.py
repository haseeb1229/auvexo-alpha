"""D3 strict malformed-input and causal source-contract negatives; synthetic only."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from auvexo_alpha.domain.ds03 import (
    AttestRequest,
    BarsPayload,
    BarsRequest,
    Ds03Attestation,
    Ds03Bar,
    Ds03Error,
    Ds03Gap,
    Ds03Identity,
    Ds03SourceEnvelope,
    Ds03SymbolSpec,
    Ds03Tick,
    SymbolsPayload,
    decode_request,
)

NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)


def identity():
    return Ds03Identity(
        account_ref="synthetic.ds03",
        login_hash="1" * 64,
        server="synthetic.demo",
        account_type="Standard",
        currency="USD",
        leverage=100,
        mode="DEMO",
        terminal_build=4755,
        terminal_version="5.0.6231",
        process_ref="synthetic.process1",
        profile_hash="2" * 64,
        release_hash="3" * 64,
        config_hash="4" * 64,
        rights_hash="5" * 64,
    )


def attest():
    return Ds03Attestation(
        identity=identity(),
        observed_at=NOW,
        connected=True,
        credential_readonly=True,
        account_trade_allowed=False,
        terminal_trade_allowed=False,
    )


def request():
    return AttestRequest(
        request_id=uuid4(),
        created_at=NOW,
        expires_at=NOW + timedelta(seconds=10),
        release_hash="3" * 64,
        config_hash="4" * 64,
    )


def spec(**changes):
    return Ds03SymbolSpec(
        **{
            "symbol": "synthetic.BTCUSDm",
            "description": "Synthetic BTC CFD",
            "category": "synthetic.crypto",
            "digits": 2,
            "point": Decimal("0.01"),
            "tick_size": Decimal("0.01"),
            "contract_size": Decimal("1"),
            "volume_min": Decimal("0.01"),
            "volume_max": Decimal("10"),
            "volume_step": Decimal("0.01"),
            **changes,
        }
    )


def test_roundtrip_request_and_frozen_models():
    original = request()
    assert decode_request(original.canonical_bytes()) == original
    with pytest.raises(ValidationError):
        original.created_at = NOW


@pytest.mark.parametrize(
    "field",
    [
        "connected",
        "credential_readonly",
        "account_trade_allowed",
        "terminal_trade_allowed",
    ],
)
def test_absent_observed_readonly_or_connection_evidence_refuses(field):
    value = attest().model_dump(mode="json")
    value.pop(field)
    with pytest.raises(ValidationError):
        Ds03Attestation.model_validate_json(json.dumps(value))


@pytest.mark.parametrize(
    "field,value",
    [
        ("connected", False),
        ("credential_readonly", False),
        ("credential_readonly", None),
        ("account_trade_allowed", True),
        ("terminal_trade_allowed", True),
    ],
)
def test_unsafe_or_unknown_observation_refuses(field, value):
    data = attest().model_dump(mode="json")
    data[field] = value
    with pytest.raises(ValidationError):
        Ds03Attestation.model_validate_json(json.dumps(data))


@pytest.mark.parametrize("mode", ["REAL", "CONTEST", "UNKNOWN", None, ""])
def test_real_unknown_mode_refuses(mode):
    data = identity().model_dump(mode="json")
    data["mode"] = mode
    with pytest.raises(ValidationError):
        Ds03Identity.model_validate_json(json.dumps(data))


def test_mode_is_required_observed_fact():
    data = identity().model_dump(mode="json")
    del data["mode"]
    with pytest.raises(ValidationError):
        Ds03Identity.model_validate_json(json.dumps(data))


@pytest.mark.parametrize(
    "operation",
    [
        "order_send",
        "order_check",
        "modify",
        "cancel",
        "login",
        "getattr",
        "__dict__",
        "TRADE",
        "CANCEL",
        "EXECUTE",
        "shutdown",
        "ACCOUNT_SWITCH",
    ],
)
def test_trade_arbitrary_account_switch_methods_fail_before_dispatch(operation):
    data = request().model_dump(mode="json")
    data["operation"] = operation
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE$"):
        decode_request(json.dumps(data).encode())


@pytest.mark.parametrize("extra", ["account", "server", "profile", "module", "path", "shell"])
def test_uncontrolled_bootstrap_knobs_refuse(extra):
    data = request().model_dump(mode="json")
    data[extra] = "synthetic.untrusted"
    with pytest.raises(Ds03Error):
        decode_request(json.dumps(data).encode())


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"null",
        b"[]",
        b"{}",
        b"\xff",
        b"{",
        b"a" * 65537,
        b'{"operation":"ATTEST","operation":"SPEC"}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
    ],
    ids=lambda raw: "bytes-" + str(len(raw)),
)
def test_malformed_oversized_duplicate_or_nonfinite_json_is_generic(raw):
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE$"):
        decode_request(raw)


@pytest.mark.parametrize(
    "value", [1.25, float("nan"), Decimal("Infinity"), "1e-10", "0." + "1" * 19]
)
def test_swap_uses_bounded_exact_decimal(value):
    with pytest.raises((ValidationError, ValueError)):
        spec(swap_long=value)


def test_full_spec_preserves_available_metadata_and_explicit_unknowns():
    full = spec(
        tick_value="1",
        tick_value_profit="1",
        tick_value_loss="1",
        volume_limit="10",
        stops_level=1,
        freeze_level=2,
        trade_mode="READONLY",
        order_modes=("MARKET",),
        fill_modes=("IOC",),
        margin_mode="CFD",
        execution_mode="MARKET",
        base_currency="BTC",
        profit_currency="USD",
        margin_currency="USD",
        sessions=("synthetic.Monday.00:00-23:59",),
        spread="0.1",
        swap_mode="POINTS",
        swap_long="-1",
        swap_short="0",
        quote_at=NOW,
        history_start=NOW - timedelta(days=1),
        history_end=NOW,
    )
    assert full.symbol == "synthetic.BTCUSDm"
    assert full.swap_long == Decimal("-1")
    unknown = spec()
    assert unknown.sessions is None and unknown.history_start is None
    assert Ds03SymbolSpec.model_validate_json(full.canonical_bytes()) == full


@pytest.mark.parametrize(
    "changes",
    [
        {"volume_min": "11"},
        {"volume_step": "11"},
        {"point": "0"},
        {"history_start": NOW, "history_end": NOW - timedelta(seconds=1)},
    ],
)
def test_inconsistent_spec_refuses(changes):
    with pytest.raises((ValueError, ValidationError)):
        spec(**changes)


def test_causal_envelope_order_and_required_bindings():
    data = dict(
        identity=identity(),
        provider_at=NOW,
        first_seen_at=NOW,
        received_at=NOW,
        processed_at=NOW,
        available_at=NOW,
        raw_hash="6" * 64,
        normalized_hash="7" * 64,
        connector_hash="3" * 64,
    )
    envelope = Ds03SourceEnvelope(**data)
    assert envelope.clock_status == "STRUCTURAL_ONLY_CLOCK_BLOCKED"
    for changes in (
        {"provider_at": NOW + timedelta(seconds=1)},
        {"available_at": NOW - timedelta(seconds=1)},
        {"symbol": "synthetic.BTCUSDm"},
        {"spec_hash": "8" * 64},
    ):
        with pytest.raises((ValueError, ValidationError)):
            Ds03SourceEnvelope(**{**data, **changes})


def test_history_complete_never_ignores_explicit_gap():
    with pytest.raises((ValueError, ValidationError)):
        BarsPayload(
            bars=(), gaps=(Ds03Gap(start=NOW - timedelta(minutes=1), end=NOW),), coverage="COMPLETE"
        )
    assert BarsPayload(bars=()).coverage == "UNKNOWN"


@pytest.mark.parametrize(
    "changes",
    [
        {"bid": "2", "ask": "1"},
        {"bid": "-1", "ask": "1"},
    ],
)
def test_bad_quote_semantics(changes):
    with pytest.raises((ValueError, ValidationError)):
        Ds03Tick(symbol="synthetic.BTCUSDm", provider_at=NOW, **changes)


def test_ohlc_bounds_and_required_timeframe():
    with pytest.raises((ValueError, ValidationError)):
        Ds03Bar(symbol="synthetic.BTCUSDm", provider_at=NOW, open="2", high="1", low="1", close="2")
    common = request().model_dump(exclude={"operation"})
    with pytest.raises((ValueError, ValidationError)):
        BarsRequest(
            **common, symbol="synthetic.BTCUSDm", start=NOW - timedelta(minutes=1), end=NOW, limit=1
        )


def test_duplicate_or_oversized_symbols_refuse():
    with pytest.raises((ValueError, ValidationError)):
        SymbolsPayload(symbols=("synthetic.BTCUSDm",) * 2)
    with pytest.raises((ValueError, ValidationError)):
        SymbolsPayload(symbols=tuple(f"synthetic.S{i}" for i in range(129)))


@pytest.mark.parametrize(
    "field", ["connected", "credential_readonly", "account_trade_allowed", "terminal_trade_allowed"]
)
@pytest.mark.parametrize("value", [0, 1, "true", "false", None])
def test_security_flags_require_exact_observed_booleans(field, value):
    data = attest().model_dump(mode="json")
    data[field] = value
    with pytest.raises((ValueError, ValidationError)):
        Ds03Attestation.model_validate_json(json.dumps(data))


@pytest.mark.parametrize(
    "field,value",
    [
        ("account_type", "UNKNOWN"),
        ("currency", "UNKNOWN"),
        ("terminal_version", "UNKNOWN"),
        ("server", "synthetic.UNKNOWN"),
        ("account_ref", "synthetic.UNKNOWN"),
        ("process_ref", "synthetic.UNKNOWN"),
    ],
)
def test_unknown_observed_metadata_refuses_even_if_expected_can_match(field, value):
    data = identity().model_dump(mode="json")
    data[field] = value
    with pytest.raises((ValueError, ValidationError)):
        Ds03Identity.model_validate_json(json.dumps(data))


@pytest.mark.parametrize("value", [0, 1, "true", None])
def test_synthetic_marker_rejects_coercible_flags(value):
    data = dict(review_hash="5" * 64, valid_until=NOW, synthetic=value)
    from auvexo_alpha.domain.ds03 import Ds03Rights

    with pytest.raises((ValueError, ValidationError)):
        Ds03Rights(**data)


@pytest.mark.parametrize("value", [60.0, True, False, "60", None])
def test_timeframe_requires_exact_supported_integer(value):
    common = request().model_dump(exclude={"operation"})
    with pytest.raises((ValueError, ValidationError)):
        BarsRequest(
            **common,
            symbol="synthetic.BTCUSDm",
            start=NOW - timedelta(minutes=1),
            end=NOW,
            limit=1,
            timeframe_seconds=value,
        )


def test_synthetic_envelope_cannot_assert_trusted_clock():
    with pytest.raises((ValueError, ValidationError)):
        Ds03SourceEnvelope(
            identity=identity(),
            provider_at=NOW,
            first_seen_at=NOW,
            received_at=NOW,
            processed_at=NOW,
            available_at=NOW,
            raw_hash="6" * 64,
            normalized_hash="7" * 64,
            connector_hash="3" * 64,
            clock_status="TRUSTED",
        )
