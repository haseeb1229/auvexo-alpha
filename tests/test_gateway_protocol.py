"""Synthetic protocol and inert design tests; no execution or source evidence."""

import json
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st
from paper_fixtures import HASH, NOW, fixture_bundle
from pydantic import ValidationError

from auvexo_alpha.domain.contracts import InstrumentSpec, Mode, Product, Venue
from auvexo_alpha.domain.gateway import (
    MAX_MESSAGE_BYTES,
    AccountAttestation,
    BrokerDealFact,
    BrokerOrderFact,
    BrokerPositionFact,
    GatewayAccountSnapshot,
    GatewayAck,
    GatewayDispatch,
    GatewayError,
    GatewayFact,
    GatewayHealth,
    GatewayHello,
    GatewayInstrumentSnapshot,
    GatewayMessage,
    GatewayReconcile,
    GatewaySnapshot,
    OfflineDemoPermit,
    build_message,
    decode_message,
    require_attestation,
    validate_offline_permit,
)
from auvexo_alpha.domain.paper import PaperReservation, bind_authorization
from auvexo_alpha.domain.paper_risk import assess_paper


def account(**updates: object) -> AccountAttestation:
    data = dict(
        account_ref="synthetic.demo",
        venue=Venue.BINANCE,
        server="synthetic.server",
        account_identifier="synthetic.account",
        account_kind="DEMO",
        currency="USD",
        account_mode="HEDGING",
        observed_at=NOW,
        capability_hash=HASH,
    )
    data.update(updates)
    return AccountAttestation.model_validate(data)


def permit(**updates: object) -> OfflineDemoPermit:
    data = dict(
        permit_id=uuid4(),
        account_ref="synthetic.demo",
        server="synthetic.server",
        venue=Venue.BINANCE,
        product=Product.SPOT,
        instruments=("synthetic.BTCUSD",),
        release_hash=HASH,
        config_hash=HASH,
        max_notional=Decimal("100"),
        max_modeled_loss=Decimal("1"),
        valid_from=NOW,
        valid_until=NOW + timedelta(hours=1),
        revocation_epoch=1,
        allowed_commands=("SUBMIT", "CANCEL", "RECONCILE"),
    )
    data.update(updates)
    return OfflineDemoPermit.model_validate(data)


def check(p: OfflineDemoPermit | None, **updates: object) -> bool:
    data = dict(
        account=account(),
        mode=Mode.DEMO,
        instrument_id="synthetic.BTCUSD",
        venue=Venue.BINANCE,
        product=Product.SPOT,
        release_hash=HASH,
        config_hash=HASH,
        notional=Decimal("100"),
        modeled_loss=Decimal("1"),
        command="SUBMIT",
        now=NOW,
        revocation_epoch=1,
        expected_hash=p.content_hash() if p else HASH,
    )
    data.update(updates)
    return validate_offline_permit(p, **data)


def message(**updates: object) -> GatewayMessage:
    data = dict(
        payload=GatewayHello(gateway_id="synthetic.gateway", session_id=uuid4()),
        command_id=uuid4(),
        correlation_id=uuid4(),
        source_id="synthetic.core",
        account_ref="synthetic.demo",
        mode=Mode.DEMO,
        writer_epoch=1,
        intent_hash=HASH,
        authorization_hash=HASH,
        reservation_hash=HASH,
        release_hash=HASH,
        config_hash=HASH,
        created_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
    )
    data.update(updates)
    return build_message(**data)


def dispatch() -> GatewayDispatch:
    b = fixture_bundle()
    d = assess_paper(b.intent, b.policy, b.market, b.spec, b.account, b.release, (), now=b.now)
    assert d.exposure is not None
    r = PaperReservation(
        reservation_id=uuid4(),
        intent_hash=b.intent.content_hash(),
        logical_key=b.intent.logical_key,
        account_ref=b.intent.account_ref,
        instrument_id=b.intent.instrument_id,
        bucket=d.exposure.bucket,
        action=b.intent.action,
        intent_id=b.intent.intent_id,
        quantity=d.exposure.quantity,
        notional=d.exposure.notional,
        modeled_loss=d.exposure.modeled_loss,
        margin=d.exposure.margin_required,
        created_at=b.now,
        expires_at=b.intent.expires_at,
    )
    a = bind_authorization(d, b.intent, b.account, r.reservation_id, uuid4(), b.now)
    return GatewayDispatch(intent=b.intent, authorization=a, reservation=r)


def test_protocol_canonical_roundtrip_and_expiry() -> None:
    m = message()
    assert decode_message(m.canonical_bytes()) == m
    m.require_current(NOW)
    with pytest.raises(ValueError, match="EXPIRED"):
        m.require_current(m.expires_at)
    with pytest.raises(ValueError, match="EXPIRED"):
        m.require_current(NOW - timedelta(microseconds=1))


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{",
        b"[]",
        b"null",
        b"\xff",
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":1,"x":2}',
        b" " * (MAX_MESSAGE_BYTES + 1),
        b"[" * 2000 + b"]" * 2000,
    ],
    ids=[
        "empty",
        "syntax",
        "array",
        "null",
        "utf8",
        "nan",
        "infinity",
        "duplicate",
        "oversize",
        "depth",
    ],
)
def test_protocol_ambiguous_malformed_or_oversized_json(raw: bytes) -> None:
    with pytest.raises((ValueError, ValidationError)):
        decode_message(raw)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "2.0"),
        ("mode", "LIVE"),
        ("mode", "SHADOW"),
        ("writer_epoch", True),
        ("writer_epoch", -1),
        ("account_ref", "123456"),
        ("payload_hash", "0" * 64),
        ("unexpected", "secret"),
        ("command_id", "bad"),
        ("expires_at", "2026-10-18T12:00:00Z"),
        ("release_hash", "BAD"),
        ("created_at", "2026-10-18T17:00:00+05:00"),
    ],
)
def test_protocol_unknown_version_mode_type_and_hash_rejected(field: str, value: object) -> None:
    data = message().model_dump(mode="json")
    data[field] = value
    with pytest.raises(ValidationError):
        decode_message(json.dumps(data).encode())


def test_duplicate_nested_key_and_large_valid_envelope_are_rejected() -> None:
    raw = message().canonical_bytes().replace(b'"kind":"hello"', b'"kind":"hello","kind":"hello"')
    with pytest.raises(ValueError, match="DUPLICATE"):
        decode_message(raw)
    with pytest.raises(ValidationError):
        message(expires_at=NOW + timedelta(minutes=6))


@given(st.binary(min_size=1, max_size=256))
def test_arbitrary_bytes_never_produce_untyped_protocol_objects(raw: bytes) -> None:
    try:
        result = decode_message(raw)
    except ValueError:
        return
    assert isinstance(result, GatewayMessage)


def test_attestation_current_independent_match_only() -> None:
    a = account()
    require_attestation(a, a, mode=Mode.DEMO, now=NOW)
    require_attestation(a, a, mode=Mode.PAPER, now=NOW)
    with pytest.raises(ValueError, match="STALE"):
        require_attestation(a, a, mode=Mode.DEMO, now=NOW + timedelta(seconds=31))
    with pytest.raises(ValueError, match="STALE"):
        require_attestation(a, a, mode=Mode.DEMO, now=NOW - timedelta(seconds=1))


@pytest.mark.parametrize(
    "mode", [Mode.RESEARCH, Mode.BACKTEST, Mode.SHADOW, Mode.LIVE_LIMITED, Mode.LIVE]
)
def test_live_and_nonexecution_modes_refused(mode: Mode) -> None:
    with pytest.raises(ValueError, match="MODE"):
        require_attestation(account(), account(), mode=mode, now=NOW)


@pytest.mark.parametrize(
    "field,value",
    [
        ("server", "synthetic.changed"),
        ("account_identifier", "synthetic.other"),
        ("account_ref", "synthetic.other"),
        ("currency", "EUR"),
        ("account_mode", "NETTING"),
        ("capability_hash", "2" * 64),
    ],
)
def test_account_drift_refused(field: str, value: object) -> None:
    with pytest.raises(ValueError, match="DRIFT"):
        require_attestation(account(**{field: value}), account(), mode=Mode.DEMO, now=NOW)


def test_real_unknown_account_and_credentials_grant_zero_authority() -> None:
    with pytest.raises(ValueError, match="MODE"):
        require_attestation(account(account_kind="REAL"), account(), mode=Mode.DEMO, now=NOW)
    with pytest.raises(ValidationError):
        account(account_identifier="123456789")
    with pytest.raises(ValidationError):
        account(credentials="synthetic.password")
    assert not check(None)


@pytest.mark.parametrize(
    "field,value",
    [
        ("mode", Mode.LIVE),
        ("mode", Mode.PAPER),
        ("release_hash", "2" * 64),
        ("config_hash", "2" * 64),
        ("expected_hash", "2" * 64),
        ("instrument_id", "synthetic.OTHER"),
        ("venue", Venue.EXNESS),
        ("product", Product.CFD),
        ("command", "WITHDRAW"),
        ("command", "TRANSFER"),
        ("revocation_epoch", 2),
        ("notional", Decimal("100.01")),
        ("modeled_loss", Decimal("1.01")),
        ("notional", Decimal("-1")),
        ("modeled_loss", Decimal("NaN")),
        ("now", NOW + timedelta(hours=1)),
        ("now", NOW - timedelta(seconds=1)),
        ("account", account(server="synthetic.other")),
        ("account", account(account_kind="REAL")),
    ],
)
def test_inert_permit_fail_closed(field: str, value: object) -> None:
    p = permit()
    assert check(p)
    assert not check(p, **{field: value})


def test_permit_tampering_real_scope_and_binance_derivative_denied() -> None:
    p = permit()
    changed = p.model_copy(update={"max_notional": Decimal("100000")})
    assert not check(changed, expected_hash=p.content_hash())
    for changes in (
        {"mode": Mode.LIVE},
        {"account_ref": "real.account"},
        {"allowed_commands": ("WITHDRAW",)},
        {"product": Product.PERPETUAL},
    ):
        with pytest.raises(ValidationError):
            permit(**changes)


def test_dispatch_paper_exact_bindings_and_no_demo_authority() -> None:
    d = dispatch()
    m = message(
        payload=d,
        mode=Mode.PAPER,
        account_ref=d.intent.account_ref,
        intent_hash=d.intent.content_hash(),
        authorization_hash=d.authorization.content_hash(),
        reservation_hash=d.reservation.content_hash(),
        release_hash=d.intent.release_hash,
    )
    assert decode_message(m.canonical_bytes()) == m
    for field, value in (
        ("mode", Mode.DEMO),
        ("writer_epoch", 2),
        ("account_ref", "paper.other"),
        ("intent_hash", "2" * 64),
        ("authorization_hash", "2" * 64),
        ("reservation_hash", "2" * 64),
        ("release_hash", "2" * 64),
    ):
        data = m.model_dump()
        data[field] = value
        with pytest.raises(ValidationError):
            GatewayMessage.model_validate(data)


@pytest.mark.parametrize(
    "target,field,value",
    [
        ("reservation", "quantity", "0.02"),
        ("reservation", "state", "RELEASED"),
        ("reservation", "account_ref", "paper.other"),
        ("authorization", "intent_hash", "2" * 64),
        ("authorization", "release_hash", "2" * 64),
        ("authorization", "reservation_id", str(uuid4())),
        ("intent", "mode", "DEMO"),
    ],
)
def test_dispatch_risk_authorization_reservation_tampering(
    target: str, field: str, value: object
) -> None:
    data = dispatch().model_dump(mode="json")
    data[target][field] = value
    with pytest.raises(ValidationError):
        GatewayDispatch.model_validate_json(json.dumps(data))


@pytest.mark.parametrize(
    "variant",
    [
        "health",
        "attestation",
        "instrument",
        "ack",
        "order",
        "deal",
        "position",
        "reconcile",
        "snapshot",
        "error",
    ],
)
def test_all_tagged_protocol_variants_roundtrip(variant: str) -> None:
    spec = InstrumentSpec(
        instrument_id="synthetic.BTCUSD",
        venue=Venue.BINANCE,
        product=Product.SPOT,
        symbol="SYNTHBTCUSD",
        base_currency="BTC",
        quote_currency="USD",
        quantity_unit="BASE_UNIT",
        contract_multiplier=Decimal("1"),
        price_tick=Decimal("0.01"),
        quantity_step=Decimal("0.001"),
        min_quantity=Decimal("0.001"),
        max_quantity=Decimal("1"),
        spec_version="synthetic.v1",
        observed_at=NOW,
    )
    order = BrokerOrderFact(
        order_ref="synthetic.order",
        intent_hash=HASH,
        quantity=Decimal("1"),
        status="ACKNOWLEDGED",
        observed_at=NOW,
    )
    deal = BrokerDealFact(
        deal_ref="synthetic.deal",
        order_ref=order.order_ref,
        intent_hash=HASH,
        quantity=Decimal("0.5"),
        price=Decimal("100"),
        fees=Decimal("0"),
        observed_at=NOW,
    )
    position = BrokerPositionFact(
        position_ref="synthetic.position",
        instrument_id=spec.instrument_id,
        quantity=Decimal("0.5"),
        side="BUY",
        observed_at=NOW,
    )
    payloads = dict(
        health=GatewayHealth(status="RECONCILE_ONLY", observed_at=NOW),
        attestation=account(),
        instrument=GatewayInstrumentSnapshot(spec=spec, supported_fill=("IOC",)),
        ack=GatewayAck(status="UNKNOWN", attempt_id=uuid4()),
        order=GatewayFact(fact=order),
        deal=GatewayFact(fact=deal),
        position=GatewayFact(fact=position),
        reconcile=GatewayReconcile(cursor=1),
        snapshot=GatewaySnapshot(cursor=1, orders=(order,), deals=(deal,), positions=(position,)),
        error=GatewayError(code="RECONCILE_REQUIRED"),
    )
    m = message(payload=payloads[variant])
    assert decode_message(m.canonical_bytes()) == m


def test_fill_modes_decimal_facts_and_unknown_payload_fail_closed() -> None:
    with pytest.raises(ValidationError):
        BrokerDealFact(
            deal_ref="synthetic.deal",
            order_ref="synthetic.order",
            intent_hash=HASH,
            quantity=1.0,
            price=Decimal("100"),
            fees=Decimal("0"),
            observed_at=NOW,
        )
    m = message().model_dump(mode="json")
    m["payload"]["kind"] = "arbitrary.execute"
    with pytest.raises(ValidationError):
        decode_message(json.dumps(m).encode())
    spec = InstrumentSpec(
        instrument_id="synthetic.BTCUSD",
        venue=Venue.BINANCE,
        product=Product.SPOT,
        symbol="SYNTHBTCUSD",
        base_currency="BTC",
        quote_currency="USD",
        quantity_unit="BASE_UNIT",
        contract_multiplier=Decimal("1"),
        price_tick=Decimal("0.01"),
        quantity_step=Decimal("0.001"),
        min_quantity=Decimal("0.001"),
        max_quantity=Decimal("1"),
        spec_version="synthetic.v1",
        observed_at=NOW,
    )
    for fill in (("UNSUPPORTED",), ("IOC", "IOC")):
        with pytest.raises(ValidationError):
            GatewayInstrumentSnapshot(spec=spec, supported_fill=fill)


def test_account_snapshot_is_strict_signed_synthetic_observation() -> None:
    a = GatewayAccountSnapshot(
        account_ref="synthetic.demo",
        currency="USD",
        balance=Decimal("100"),
        equity=Decimal("-1"),
        free_margin=Decimal("-2"),
        observed_at=NOW,
    )
    m = message(payload=a)
    assert decode_message(m.canonical_bytes()) == m
    with pytest.raises(ValidationError):
        message(payload=a, account_ref="synthetic.other")
    with pytest.raises(ValidationError):
        GatewayAccountSnapshot.model_validate(a.model_dump() | {"balance": 1.2})
