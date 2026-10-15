import json
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError

from auvexo_alpha.domain.contracts import (
    ExecutionReport,
    FeatureSnapshot,
    InstrumentSpec,
    MarketState,
    Mode,
    PositiveAmount,
    Product,
    RiskAuthorization,
    TradeIntent,
    UTCTime,
    Venue,
)


@pytest.mark.parametrize(
    "value",
    [
        0.1,
        1,
        True,
        None,
        "NaN",
        "Infinity",
        "-Infinity",
        "1e3",
        " 1",
        "+1",
        "01",
        "0",
        "-1",
        "1.0000000000000000001",
        "1000000000000000000",
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("1e999999"),
        Decimal("1e-999999"),
        Decimal("0e999999"),
    ],
)
def test_r014_p1_money_rejects_invalid(value: object) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(PositiveAmount).validate_python(value)


@given(
    st.decimals(
        min_value="0.000001",
        max_value="999999999999.999999",
        places=6,
        allow_nan=False,
        allow_infinity=False,
    )
)
def test_r014_p1_decimal_never_rounds(value: Decimal) -> None:
    with localcontext() as context:
        context.prec = 4
        assert TypeAdapter(PositiveAmount).validate_python(format(value, "f")) == value


@pytest.mark.parametrize(
    "value",
    [
        datetime(2026, 1, 1),
        "2026-01-01",
        "2026-01-01T00:00:00",
        "2026-01-01T00:00:00+05:00",
        0,
        datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=5))),
    ],
)
def test_r014_p1_utc_rejects_invalid(value: object) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(UTCTime).validate_python(value)


def test_canonical_hash_and_json_roundtrip(intent_data: dict[str, object]) -> None:
    intent = TradeIntent.model_validate(intent_data)
    alternate = TradeIntent.model_validate(intent_data | {"quantity": "0.0100"})
    assert intent.canonical_bytes() == alternate.canonical_bytes()
    assert intent.content_hash() == alternate.content_hash()
    assert TradeIntent.model_validate_json(intent.canonical_bytes()) == intent
    assert json.loads(intent.canonical_bytes())["quantity"] == "0.01"
    with pytest.raises(ValidationError):
        intent.quantity = Decimal("1")


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": "2.0"},
        {"broker_payload": {}},
        {"account_ref": "../../real"},
        {"venue": "UNKNOWN"},
        {"mode": "real"},
        {"quantity": float("nan")},
    ],
)
def test_strict_intent_rejects_payloads(
    intent_data: dict[str, object], change: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        TradeIntent.model_validate(intent_data | change)


def test_expiration_is_injected_not_wall_clock(intent_data: dict[str, object]) -> None:
    intent = TradeIntent.model_validate(intent_data)
    assert intent.is_expired(intent.expires_at)
    assert not intent.is_expired(intent.created_at)
    with pytest.raises(ValidationError):
        TradeIntent.model_validate(intent_data | {"expires_at": intent.created_at})


def instrument_data() -> dict[str, object]:
    return dict(
        instrument_id="synthetic-BTC",
        venue=Venue.BINANCE,
        product=Product.SPOT,
        symbol="synthetic-BTCUSD",
        base_currency="BTC",
        quote_currency="USD",
        quantity_unit="BASE_UNIT",
        contract_multiplier="1",
        price_tick="0.01",
        quantity_step="0.01",
        min_quantity="0.01",
        max_quantity="10",
        spec_version="test-v1",
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    "change",
    [
        {"base_currency": "usd"},
        {"quote_currency": "BTC"},
        {"contract_multiplier": "2"},
        {"quantity_unit": "LOT"},
        {"max_quantity": "0.001"},
        {"min_quantity": "0.015"},
        {"venue": Venue.EXNESS},
        {"price_tick": "0"},
    ],
)
def test_instrument_units_bounds(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        InstrumentSpec.model_validate(instrument_data() | change)


def test_instrument_step_is_independent_of_decimal_context() -> None:
    with localcontext() as context:
        context.prec = 3
        assert InstrumentSpec.model_validate(
            instrument_data() | {"max_quantity": "999999999999.99"}
        )


def test_r014_p1_point_in_time() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    data = dict(
        market_state_id=uuid4(),
        instrument_id="synthetic",
        as_of=now,
        available_at=now,
        decision_at=now,
        source_watermark=now,
        dataset_version="0" * 64,
        health="HEALTHY",
    )
    assert MarketState.model_validate(data)
    assert FeatureSnapshot.model_validate(
        data | dict(feature_snapshot_id=uuid4(), feature_version="test", code_hash="1" * 64)
    )
    for field, delta in [("available_at", 1), ("source_watermark", 1), ("decision_at", -1)]:
        with pytest.raises(ValidationError):
            MarketState.model_validate(data | {field: now + timedelta(seconds=delta)})


def test_inert_risk_shape_requires_binding() -> None:
    with pytest.raises(ValidationError):
        RiskAuthorization.model_validate({"approved": True, "mode": Mode.LIVE})


@pytest.mark.parametrize(
    "status,filled,deal",
    [
        ("FILLED", "0", None),
        ("PARTIALLY_FILLED", "1", "test"),
        ("REJECTED", "1", "test"),
        ("FILLED", "2", "test"),
        ("FILLED", "1", None),
    ],
)
def test_report_cannot_claim_inconsistent_fill(status: str, filled: str, deal: str | None) -> None:
    with pytest.raises(ValidationError):
        ExecutionReport.model_validate(
            dict(
                report_id=uuid4(),
                intent_id=uuid4(),
                attempt_id=uuid4(),
                broker_order_ref=None,
                broker_deal_ref=deal,
                received_at=datetime(2026, 1, 1, tzinfo=UTC),
                broker_at=None,
                status=status,
                requested_quantity="1",
                filled_quantity=filled,
                fees="0",
                raw_response_hash="0" * 64,
            )
        )
