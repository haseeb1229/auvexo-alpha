from datetime import timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from research_fixtures import START, config, fitted, prices

from auvexo_alpha.application.research_simulator import (
    fit_features,
    rejected_candidate,
    resolve_counterfactuals,
    simulate,
)
from auvexo_alpha.domain.market_data import Candle
from auvexo_alpha.domain.research import CostModel, PriceAvailability

POLICY = PriceAvailability(lag_microseconds=1_000_000)
FREE = CostModel(fee_bps="0", spread_bps="0", slippage_bps="0")


def reference_roundtrip(cash, entry, exit_price, allocation, costs, partial=Decimal(1)):
    """Independent arithmetic: no simulator fill, rounding or accounting functions."""
    with localcontext() as ctx:
        ctx.prec = 50
        unit = Decimal("0.00000001")
        fee = costs.fee_bps * costs.multiplier / 10000
        impact = (costs.spread_bps / 2 + costs.slippage_bps) * costs.multiplier / 10000
        buy = (entry * (1 + impact)).quantize(unit, rounding=ROUND_CEILING)
        sell = (exit_price * (1 - impact)).quantize(unit, rounding=ROUND_FLOOR)
        size = (cash * allocation / (buy * (1 + fee))).quantize(unit, rounding=ROUND_FLOOR)
        size = (size * partial).quantize(unit, rounding=ROUND_FLOOR)
        paid = (size * buy).quantize(unit, rounding=ROUND_CEILING)
        received = (size * sell).quantize(unit, rounding=ROUND_FLOOR)
        entry_fee = (paid * fee).quantize(unit, rounding=ROUND_CEILING)
        exit_fee = (received * fee).quantize(unit, rounding=ROUND_CEILING)
        return size, cash - paid - entry_fee + received - exit_fee, entry_fee + exit_fee


def ending_prices(value):
    bars = prices(12)
    bars[-1] = Candle.model_validate(
        bars[-1].model_dump()
        | {
            "open": str(value),
            "close": str(value),
            "high": str(max(101, value)),
            "low": str(min(99, value)),
        }
    )
    return bars


def test_hand_cash_position_profit_and_no_trade():
    result = simulate(ending_prices(110), config(), POLICY, FREE, fitted())
    assert result.fills[0].at == START + timedelta(hours=2)
    assert result.fills[0].decision_at == START + timedelta(hours=1, seconds=1)
    assert result.fills[0].quantity == Decimal(100)
    assert result.fills[1].at == START + timedelta(hours=11)
    assert result.cash == result.final_equity == Decimal(11000)
    assert result.realized_pnl == Decimal(1000)
    assert result.holdings == result.unrealized_pnl == 0
    assert all(fill.label == "SIMULATED" for fill in result.fills)
    inactive = simulate(ending_prices(110), config("NO_TRADE"), POLICY, FREE, fitted())
    assert inactive.final_equity == Decimal(10000) and not inactive.fills


@pytest.mark.parametrize("multiplier", ["1", "1.5", "2"])
@pytest.mark.parametrize("partial", ["1", "0.4"])
def test_cost_stress_and_synthetic_partial_against_independent_reference(multiplier, partial):
    costs = CostModel(multiplier=Decimal(multiplier))
    cfg = config().model_copy(update={"entry_fill_fraction": Decimal(partial)})
    result = simulate(ending_prices(110), cfg, POLICY, costs, fitted())
    size, ending, fees = reference_roundtrip(
        Decimal(10000), Decimal(100), Decimal(110), cfg.exposure_fraction, costs, Decimal(partial)
    )
    assert result.fills[0].quantity == size
    assert result.final_equity == ending
    assert sum(fill.fee for fill in result.fills) == fees
    assert ending == result.initial_cash + result.realized_pnl


def test_intrabar_ambiguity_adverse_and_horizon_open():
    bars = prices(32)
    bars[26] = Candle.model_validate(bars[26].model_dump() | {"high": "105", "low": "95"})

    def signal(history, cfg, fit):
        return len(history) == 25, None

    result = simulate(bars, config("FIXED_RULE"), POLICY, FREE, fitted(), signal=signal)
    assert result.fills[1].reason == "ADVERSE_STOP_FIRST"
    assert result.fills[1].price == Decimal(98)
    assert result.realized_pnl == Decimal(-200)
    cfg = config("FIXED_RULE").model_copy(update={"holding_bars": 1})
    horizon = simulate(prices(32), cfg, POLICY, FREE, fitted(), signal=signal)
    assert horizon.fills[1].at == START + timedelta(hours=27)
    assert horizon.fills[1].reason == "HOLDING_HORIZON"


def test_future_truncation_and_decimal_context_do_not_change_past():
    bars = prices(60)
    short = simulate(bars[:30], config(), POLICY, FREE, fitted(), liquidate_at_end=False)
    long = simulate(bars, config(), POLICY, FREE, fitted(), liquidate_at_end=False)
    assert short.decisions == tuple(d for d in long.decisions if d[0] <= short.equity[-1].at)
    assert short.fills == tuple(f for f in long.fills if f.at <= short.equity[-1].at)
    assert short.equity == long.equity[: len(short.equity)]
    with localcontext() as ctx:
        ctx.prec = 9
        alternate = simulate(bars[:30], config(), POLICY, FREE, fitted(), liquidate_at_end=False)
    assert alternate.bytes() == short.bytes()
    with pytest.raises(ValueError, match="TRAIN_ONLY"):
        fit_features(bars, START, bars[-1].end_at, phase="OOS")


@settings(max_examples=20, deadline=None)
@given(exit_price=st.integers(min_value=1, max_value=1000))
def test_conservation_against_independent_accounting_property(exit_price):
    costs = CostModel()
    result = simulate(ending_prices(exit_price), config(), POLICY, costs, fitted())
    _, ending, _ = reference_roundtrip(
        Decimal(10000), Decimal(100), Decimal(exit_price), Decimal(1), costs
    )
    assert result.final_equity == ending
    assert result.cash >= 0 and result.holdings == 0


def test_rejection_book_uses_observable_forward_paths_and_keeps_missing_unobservable():
    bars = prices(80)
    cfg = config("MEAN_REVERSION")

    def rejected(history, config, fitted):
        return len(history) in (25, 55), "VOLATILITY_FILTER"

    result = simulate(bars, cfg, POLICY, FREE, fitted(), signal=rejected)
    book = resolve_counterfactuals(result, bars, cfg, POLICY, FREE, fitted())
    assert not result.fills and len(book) == 2
    assert book[0].outcome == "SIMULATED" and book[0].forward_net_return == 0
    assert book[1].outcome == "UNOBSERVABLE" and book[1].forward_net_return is None
    assert dict(book[0].features)["config_hash"] == cfg.content_hash()
    assert "overlapping" in book[0].limitation
    missing = rejected_candidate(START, bars[0].instrument_id, "0" * 64, "RIGHTS_BLOCKED", None, 24)
    assert missing.outcome == "UNOBSERVABLE" and missing.available_price is None


@pytest.mark.parametrize(
    "amount", [1.0, True, Decimal("NaN"), Decimal("Infinity"), Decimal("-1"), Decimal(0)]
)
def test_simulator_rejects_inexact_nonfinite_or_nonpositive_initial_cash(amount):
    with pytest.raises(ValueError):
        simulate(prices(5), config(), POLICY, FREE, fitted(), initial_cash=amount)


@pytest.mark.parametrize("family", ["BREAKOUT", "MEAN_REVERSION", "FIXED_RULE"])
def test_strategy_features_decisions_and_rejections_obey_future_truncation(family):
    bars = prices(240)
    for i, bar in enumerate(bars):
        price = 100 + 2 * (i % 40)
        bars[i] = Candle.model_validate(
            bar.model_dump()
            | {
                "open": str(price),
                "close": str(price),
                "high": str(price + 1),
                "low": str(price - 1),
            }
        )
    cutoff = bars[120].open_at
    short = simulate(bars[:120], config(family), POLICY, FREE, fitted(), liquidate_at_end=False)
    long = simulate(bars, config(family), POLICY, FREE, fitted(), liquidate_at_end=False)
    assert tuple(d for d in short.decisions if d[0] < cutoff) == tuple(
        d for d in long.decisions if d[0] < cutoff
    )
    assert tuple(f for f in short.fills if f.at < cutoff) == tuple(
        f for f in long.fills if f.at < cutoff
    )
    assert tuple(r for r in short.rejections if r.decision_at < cutoff) == tuple(
        r for r in long.rejections if r.decision_at < cutoff
    )
    assert tuple(p for p in short.equity if p.at < cutoff) == tuple(
        p for p in long.equity if p.at < cutoff
    )
