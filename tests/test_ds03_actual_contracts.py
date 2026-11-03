"""Actual-family pure contracts; provider-shaped values below are synthetic fixtures."""

import inspect
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from auvexo_alpha.application.ds03 import Ds03Reader
from auvexo_alpha.domain.ds03 import Ds03Error, SpecRequest, decode_request
from auvexo_alpha.domain.ds03_actual import (
    PROTOCOL_FAMILY,
    ActualAttestation,
    ActualBar,
    ActualBarsRequest,
    ActualDealFact,
    ActualEnvelope,
    ActualIdentity,
    ActualOrderFact,
    ActualReply,
    ActualRights,
    ActualSpecPayload,
    ActualSpecRequest,
    ActualSymbolsPayload,
    ActualSymbolSpec,
    ActualSymbolsRequest,
    ActualTick,
    ActualTickPayload,
    ActualTickRequest,
    catalog_digest,
    decode_actual_reply,
    decode_actual_request,
)

NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)
SYMBOL = "BTCUSDm"


def identity(**changes):
    values = dict(
        account_ref="ds03.account." + "1" * 64,
        login_hash="1" * 64,
        server="ds03.server." + "2" * 64,
        account_type="Standard",
        currency="USD",
        leverage=100,
        mode="DEMO",
        terminal_build=5000,
        terminal_version="500.5000",
        process_ref="ds03.process." + "3" * 64,
        profile_hash="4" * 64,
        release_hash="5" * 64,
        config_hash="6" * 64,
        rights_hash="7" * 64,
        account_type_source="OWNER_METADATA_ONLY_NOT_EXPOSED_BY_MT5",
        authority_hash="8" * 64,
    )
    return ActualIdentity(**{**values, **changes})


def rights(**changes):
    return ActualRights(
        **{
            **dict(
                review_hash="7" * 64,
                valid_until=NOW + timedelta(days=1),
                protocol_family=PROTOCOL_FAMILY,
                synthetic=False,
            ),
            **changes,
        }
    )


def attest(at=NOW, **changes):
    return ActualAttestation(
        **{
            **dict(
                identity=identity(),
                observed_at=at,
                connected=True,
                credential_readonly=True,
                account_trade_allowed=False,
                terminal_trade_allowed=False,
                credential_authority_hash="8" * 64,
            ),
            **changes,
        }
    )


def req(cls=ActualSpecRequest, at=NOW, **changes):
    args = dict(
        request_id=uuid4(),
        created_at=at,
        expires_at=at + timedelta(seconds=10),
        release_hash="5" * 64,
        config_hash="6" * 64,
    )
    if cls in (ActualSpecRequest, ActualTickRequest, ActualBarsRequest):
        args["symbol"] = SYMBOL
    return cls(**{**args, **changes})


def spec(**changes):
    args = dict(
        symbol=SYMBOL,
        description="Synthetic provider fixture",
        category="crypto",
        digits=2,
        point=Decimal("0.01"),
        tick_size=Decimal("0.01"),
        contract_size=Decimal("1"),
        volume_min=Decimal("0.01"),
        volume_max=Decimal("10"),
        volume_step=Decimal("0.01"),
        source_ref="9" * 64,
        provider_trade_mode=4,
        provider_order_mode=127,
        provider_filling_mode=3,
        provider_trade_calc_mode=2,
    )
    return ActualSymbolSpec(**{**args, **changes})


def tick(at=NOW, first_seen=None, **changes):
    values = dict(
        symbol=SYMBOL,
        provider_at=at,
        bid=Decimal("100"),
        ask=Decimal("101"),
        first_seen_at=first_seen or at,
        source_ref="a" * 64,
        time_msc=int(at.timestamp()) * 1000 + at.microsecond // 1000,
        flags=2,
        volume_real=Decimal("0"),
    )
    return ActualTick(**{**values, **changes})


def bar(at, first_seen=NOW, **changes):
    values = dict(
        symbol=SYMBOL,
        timeframe_seconds=60,
        provider_at=at,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("100"),
        close=Decimal("101"),
        first_seen_at=first_seen,
        source_ref="b" * 64,
    )
    return ActualBar(**{**values, **changes})


def envelope(payload, at=NOW, symbol=None, **changes):
    return ActualEnvelope(
        **{
            **dict(
                identity=identity(),
                provider_at=at,
                first_seen_at=at,
                received_at=at,
                processed_at=at,
                available_at=at,
                raw_hash="c" * 64,
                normalized_hash=payload.content_hash(),
                connector_hash="5" * 64,
                symbol=symbol,
                spec_hash=spec().content_hash() if symbol else None,
                provider_time_kind="SDK_EVENT_TIME",
                protocol_family=PROTOCOL_FAMILY,
                synthetic=False,
            ),
            **changes,
        }
    )


def test_broker_symbol_family_does_not_weaken_accepted_synthetic_decoder():
    request = req()
    assert decode_actual_request(request.canonical_bytes()) == request
    with pytest.raises(Ds03Error):
        decode_request(request.canonical_bytes())
    args = request.model_dump(exclude={"operation"})
    with pytest.raises(ValidationError):
        SpecRequest(**args)
    assert "codec" not in inspect.signature(Ds03Reader).parameters
    assert "profile" not in inspect.signature(Ds03Reader).parameters


@pytest.mark.parametrize(
    "symbol", ["ETHUSDm", "XAUUSD.a", "#SYNTHETIC", "SYNTH+CFD", "SYNTH/CROSS"]
)
def test_exact_provider_names_preserved_without_assumed_suffix(symbol):
    assert req(symbol=symbol).symbol == symbol


@pytest.mark.parametrize(
    "symbol", ["", "a" * 97, "bad\nname", "bad\x00name", "bad name", "unicode\u200b"]
)
def test_unbounded_control_or_ambiguous_symbol_refuses(symbol):
    with pytest.raises((ValueError, ValidationError)):
        req(symbol=symbol)


def test_actual_markers_and_owner_only_account_type_are_explicit():
    assert identity().account_type_source == "OWNER_METADATA_ONLY_NOT_EXPOSED_BY_MT5"
    values = identity().model_dump()
    del values["account_type_source"]
    with pytest.raises(ValidationError):
        ActualIdentity(**values)
    for field in ("protocol_family", "synthetic"):
        values = rights().model_dump()
        del values[field]
        with pytest.raises(ValidationError):
            ActualRights(**values)


@pytest.mark.parametrize("value", [True, 0, 1, "false", None])
def test_actual_synthetic_flag_cannot_be_coerced_or_true(value):
    with pytest.raises((ValueError, ValidationError)):
        rights(synthetic=value)


@pytest.mark.parametrize(
    "changes",
    [
        {"credential_authority_hash": "f" * 64},
        {"credential_readonly": False},
        {"account_trade_allowed": True},
        {"terminal_trade_allowed": True},
        {"connected": False},
        {"connected": 1},
    ],
)
def test_authority_and_observed_security_flags_fail_closed(changes):
    with pytest.raises((ValueError, ValidationError)):
        attest(**changes)


def test_actual_reply_requires_protocol_hash_and_nested_family():
    request = req()
    payload = ActualSpecPayload(spec=spec())
    reply = ActualReply(
        request_id=request.request_id,
        operation="SPEC",
        payload=payload,
        envelope=envelope(payload, symbol=SYMBOL),
        protocol_family=PROTOCOL_FAMILY,
    )
    assert decode_actual_reply(reply.canonical_bytes()) == reply
    value = reply.model_dump(mode="json")
    value.pop("protocol_family")
    with pytest.raises(Ds03Error):
        decode_actual_reply(json.dumps(value).encode())
    value = reply.model_dump(mode="json")
    value["envelope"]["synthetic"] = True
    with pytest.raises(Ds03Error):
        decode_actual_reply(json.dumps(value).encode())
    value = reply.model_dump(mode="json")
    value["envelope"]["normalized_hash"] = "f" * 64
    with pytest.raises(Ds03Error):
        decode_actual_reply(json.dumps(value).encode())


def test_catalog_has_explicit_bounds_cursor_and_completion():
    names = tuple(f"S{i}" for i in range(129))
    digest = catalog_digest(names)
    page = ActualSymbolsPayload(
        symbols=names[:128], catalog_hash=digest, total=129, offset=0, complete=False
    )
    assert not page.complete
    assert ActualSymbolsPayload(
        symbols=names[128:], catalog_hash=digest, total=129, offset=128, complete=True
    ).complete
    for kwargs in (
        dict(offset=1, catalog_hash=None),
        dict(offset=0, catalog_hash=digest),
        dict(offset=4097, catalog_hash=digest),
    ):
        with pytest.raises((ValueError, ValidationError)):
            req(ActualSymbolsRequest, **kwargs)
    for kwargs in (
        dict(symbols=names, catalog_hash=digest, total=129, offset=0, complete=True),
        dict(symbols=names[:1], catalog_hash=digest, total=129, offset=0, complete=False),
        dict(symbols=names[:1], catalog_hash=digest, total=4097, offset=0, complete=False),
        dict(symbols=names[:1], catalog_hash=digest, total=1, offset=0, complete=1),
    ):
        with pytest.raises((ValueError, ValidationError)):
            ActualSymbolsPayload(**kwargs)


@pytest.mark.parametrize(
    "changes",
    [
        {"first_seen_at": NOW - timedelta(seconds=1)},
        {"time_msc": 1},
        {"flags": -1},
        {"flags": 256},
        {"volume_real": "-1"},
    ],
)
def test_tick_timestamp_flags_and_float_source_identity(changes):
    with pytest.raises((ValueError, ValidationError)):
        tick(**changes)


def test_records_require_individual_first_seen_and_raw_source_identity():
    for cls, record in ((ActualTick, tick()), (ActualBar, bar(NOW - timedelta(minutes=1)))):
        for field in ("first_seen_at", "source_ref"):
            value = record.model_dump()
            del value[field]
            with pytest.raises(ValidationError):
                cls(**value)


@pytest.mark.parametrize("state", range(10))
def test_order_state_enums_preserved_without_lossy_open_closed_mapping(state):
    record = ActualOrderFact(
        order_ref="ds03.order." + "d" * 64,
        symbol=SYMBOL,
        spec_hash=spec().content_hash(),
        provider_state=state,
        provider_type=2,
        volume_initial="1",
        volume_current="0",
        price_open="100",
        setup_at=NOW - timedelta(hours=1),
        done_at=NOW,
        provider_at=NOW,
        first_seen_at=NOW,
        source_ref="e" * 64,
    )
    assert record.provider_state == state and record.volume_current == 0
    assert "state" not in record.model_dump()


def deal(**changes):
    values = dict(
        deal_ref="ds03.deal." + "f" * 64,
        kind="NON_MARKET",
        symbol=None,
        spec_hash=None,
        provider_type=2,
        entry=0,
        quantity="0",
        price="0",
        profit="100",
        commission="-1",
        swap="0",
        fee="0",
        provider_at=NOW,
        first_seen_at=NOW,
        source_ref="a" * 64,
    )
    return ActualDealFact(**{**values, **changes})


def test_nonmarket_zero_volume_balance_and_trade_deal_are_distinct():
    record = deal()
    assert record.quantity == 0 and record.symbol is None and record.profit == 100
    trade = deal(
        kind="TRADE",
        provider_type=0,
        symbol=SYMBOL,
        spec_hash=spec().content_hash(),
        quantity="1",
        price="100",
    )
    assert trade.provider_type == 0
    for changes in (
        {"symbol": SYMBOL},
        {"provider_type": 0},
        {"provider_type": 18},
        {"entry": 4},
        {"kind": "TRADE"},
        {"provider_type": True},
    ):
        with pytest.raises((ValueError, ValidationError)):
            deal(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"provider_filling_mode": 8},
        {"provider_order_mode": 128},
        {"provider_trade_calc_mode": 6},
        {"provider_trade_mode": True},
        {"provider_trade_mode": 5},
    ],
)
def test_unknown_spec_enum_and_bitmask_fail_instead_of_guessing(changes):
    with pytest.raises((ValueError, ValidationError)):
        spec(**changes)


def test_actual_missing_provider_event_time_is_explicit_not_silent_receipt_substitution():
    payload = ActualTickPayload(tick=tick())
    value = envelope(payload).model_dump()
    del value["provider_time_kind"]
    with pytest.raises(ValidationError):
        ActualEnvelope(**value)
    local = envelope(payload, provider_time_kind="LOCAL_OBSERVATION_NO_PROVIDER_TIMESTAMP")
    assert local.provider_time_kind == "LOCAL_OBSERVATION_NO_PROVIDER_TIMESTAMP"


def test_actual_bar_requires_explicit_exact_timeframe_lineage():
    value = bar(NOW - timedelta(minutes=1)).model_dump()
    del value["timeframe_seconds"]
    with pytest.raises(ValidationError):
        ActualBar(**value)
    for bad in (60.0, True, "60", 59, None):
        with pytest.raises((ValueError, ValidationError)):
            bar(NOW - timedelta(minutes=1), timeframe_seconds=bad)


def test_actual_spec_spread_is_explicitly_provider_points_not_price_units():
    value = spec()
    assert value.spread_unit == "MT5_POINTS"
    bad = value.model_dump()
    bad["spread_unit"] = "PRICE"
    with pytest.raises(ValidationError):
        ActualSymbolSpec.model_validate(bad)
