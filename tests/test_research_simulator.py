import hashlib
from dataclasses import asdict
from datetime import timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from research_fixtures import START, config, fitted, outage, prices, reprice, wave_prices

from auvexo_alpha.application.research_simulator import (
    artifact_bytes,
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


def test_literal_fill_with_spread_slippage_and_fee_on_entry_and_exit():
    # 25% of 10000 cash; reference 100 in, 110 out; 10 bps fee, 5 bps full spread (2.5 bps
    # per side) and 2 bps slippage per side: 4.5 bps adverse price impact each way.
    cfg = config(exposure_fraction="0.25")
    result = simulate(ending_prices(110), cfg, POLICY, CostModel(), fitted())
    buy, sell = result.fills
    # Entry price 100 * 1.00045 = 100.045. Size = 2500 / (100.045 * 1.001)
    # = 2500 / 100.145045 = 24.963791268..., floored to 24.96379126.
    assert (buy.side, buy.reference_price, buy.price) == ("BUY", Decimal(100), Decimal("100.045"))
    assert buy.quantity == Decimal("24.96379126")
    # Notional 24.96379126 * 100.045 = 2497.5024966067, ceiling 2497.50249661.
    # Fee 2497.50249661 * 0.001 = 2.49750249661, ceiling 2.49750250.
    assert buy.notional == Decimal("2497.50249661") and buy.fee == Decimal("2.49750250")
    # Half spread 24.96379126 * 100 * 0.00025 = 0.6240947815, ceiling 0.62409479.
    # Slippage 24.96379126 * 100 * 0.0002 = 0.4992758252, ceiling 0.49927583.
    assert buy.spread_cost == Decimal("0.62409479")
    assert buy.slippage_cost == Decimal("0.49927583")
    # Exit price 110 * 0.99955 = 109.9505. Proceeds 24.96379126 * 109.9505
    # = 2744.78133093263, floor 2744.78133093. Fee 2.74478133093, ceiling 2.74478134.
    assert (sell.side, sell.reference_price, sell.price) == (
        "SELL",
        Decimal(110),
        Decimal("109.9505"),
    )
    assert sell.quantity == Decimal("24.96379126")
    assert sell.notional == Decimal("2744.78133093") and sell.fee == Decimal("2.74478134")
    # Half spread 24.96379126 * 110 * 0.00025 = 0.68650425965, ceiling 0.68650426.
    # Slippage 24.96379126 * 110 * 0.0002 = 0.54920340772, ceiling 0.54920341.
    assert sell.spread_cost == Decimal("0.68650426")
    assert sell.slippage_cost == Decimal("0.54920341")
    # Cash 10000 - 2497.50249661 - 2.49750250 = 7500.00000089, then
    # + 2744.78133093 - 2.74478134 = 10242.03655048.
    assert result.final_equity == result.cash == Decimal("10242.03655048")
    assert result.realized_pnl == result.trades[0].pnl == Decimal("242.03655048")


def test_literal_fill_under_the_doubled_cost_stress():
    # Every rate doubles: fee 20 bps, impact 9 bps per side.
    cfg = config(exposure_fraction="0.25")
    result = simulate(ending_prices(110), cfg, POLICY, CostModel(multiplier="2"), fitted())
    buy, sell = result.fills
    # Entry 100 * 1.0009 = 100.09; size = 2500 / (100.09 * 1.002) = 2500 / 100.29018
    # = 24.927664901..., floored to 24.92766490.
    assert buy.price == Decimal("100.09") and buy.quantity == Decimal("24.92766490")
    # Notional 24.92766490 * 100.09 = 2495.009979841, ceiling 2495.00997985; fee at 0.002
    # = 4.9900199597, ceiling 4.99001996.
    assert buy.notional == Decimal("2495.00997985") and buy.fee == Decimal("4.99001996")
    # Half spread 24.92766490 * 100 * 0.0005 = 1.246383245, ceiling 1.24638325.
    assert buy.spread_cost == Decimal("1.24638325")
    # Slippage 24.92766490 * 100 * 0.0004 = 0.997106596, ceiling 0.99710660.
    assert buy.slippage_cost == Decimal("0.99710660")
    # Exit 110 * 0.9991 = 109.901; proceeds 24.92766490 * 109.901 = 2739.5753001749,
    # floor 2739.57530017; fee 5.47915060034, ceiling 5.47915061.
    assert sell.price == Decimal("109.901")
    assert sell.notional == Decimal("2739.57530017") and sell.fee == Decimal("5.47915061")
    # 10000 - 2495.00997985 - 4.99001996 + 2739.57530017 - 5.47915061 = 10234.09614975.
    assert result.final_equity == Decimal("10234.09614975")


def at_25(history, cfg, fit):
    return len(history) == 25, None


def filtered(history, cfg, fit):
    return len(history) in (25, 55), "VOLATILITY_FILTER"


def before_halt(history, cfg, fit):
    return len(history) == 25 and history[0].open_at == START, None


def into_halt(history, cfg, fit):
    return history[-1].open_at == START + timedelta(hours=35), None


def halted_prices(proof):
    return [b for b in prices() if not proof.missing_start <= b.open_at < proof.missing_end]


def unaffordable_prices():
    bars = prices(12)
    bars[2] = reprice(bars[2], open="101.25", high="101.25")
    return bars


SLOW = FREE.model_copy(update={"latency_microseconds": 7_200_000_000})


def accounting_scenarios():
    """Existing fixtures plus the three previously silent rejection paths."""
    proof = outage()
    halted = halted_prices(proof)
    resumed = next(i for i, b in enumerate(halted) if b.open_at == proof.end)
    gapped = list(halted)
    gapped[resumed] = reprice(gapped[resumed], open=80, low=80, high=100, close=100)
    ambiguous = prices(32)
    ambiguous[26] = reprice(ambiguous[26], high=105, low=95)
    fixed = config("FIXED_RULE")
    results = [
        simulate(ending_prices(110), config(), POLICY, FREE, fitted()),
        simulate(ambiguous, fixed, POLICY, FREE, fitted(), signal=at_25),
        simulate(
            prices(32),
            fixed.model_copy(update={"holding_bars": 1}),
            POLICY,
            FREE,
            fitted(),
            signal=at_25,
        ),
        simulate(prices(80), config("MEAN_REVERSION"), POLICY, FREE, fitted(), signal=filtered),
        simulate(gapped, fixed, POLICY, FREE, fitted(), signal=before_halt, outages=(proof,)),
        simulate(halted, fixed, POLICY, FREE, fitted(), signal=into_halt, outages=(proof,)),
        simulate(prices(12), config(), POLICY, FREE, fitted(), initial_cash=Decimal("0.0000001")),
        simulate(unaffordable_prices(), config(), POLICY, CostModel(), fitted()),
        simulate(prices(12), config(), POLICY, SLOW, fitted()),
    ]
    for multiplier in ("1", "1.5", "2"):
        for partial in ("1", "0.4"):
            cfg = config().model_copy(update={"entry_fill_fraction": Decimal(partial)})
            costs = CostModel(multiplier=Decimal(multiplier))
            results.append(simulate(ending_prices(110), cfg, POLICY, costs, fitted()))
    for family in ("BREAKOUT", "MEAN_REVERSION", "FIXED_RULE", "PASSIVE", "NO_TRADE"):
        results.append(simulate(wave_prices(), config(family), POLICY, CostModel(), fitted()))
    return results


def test_rejection_book_completion_left_fills_trades_and_equity_byte_identical():
    # Both digests were computed from the simulator as it stood before any rejection was
    # added (commit b743fc6) over exactly these scenarios; only the rejections may differ.
    payload = []
    for result in accounting_scenarios():
        fields = asdict(result)
        del fields["rejections"]
        payload.append(fields)
    assert hashlib.sha256(artifact_bytes(payload)).hexdigest() == (
        "5c0b218c61b43b58e826c2bc4b53e7800fd86a903452547b0ee242f236bac825"
    )
    # A book holding only volatility-filter candidates is itself unchanged, byte for byte.
    only_filtered = simulate(wave_prices(), config("MEAN_REVERSION"), POLICY, CostModel(), fitted())
    assert len(only_filtered.rejections) == 80
    assert hashlib.sha256(artifact_bytes(only_filtered.rejections)).hexdigest() == (
        "3a35e1335c0f0f8bd3af674d46571f8cc9c74933f16ba5589f624b43cce97608"
    )


def test_every_proposal_is_filled_rejected_or_the_single_still_pending_entry():
    for result in accounting_scenarios():
        proposals = [at for at, label in result.decisions if label == "LONG_PROPOSAL"]
        filled = {f.decision_at for f in result.fills if f.side == "BUY"}
        rejected = {r.decision_at for r in result.rejections}
        open_ended = [at for at in proposals if at not in filled and at not in rejected]
        assert open_ended in ([], proposals[-1:])
        assert len({r.candidate_hash for r in result.rejections}) == len(result.rejections)


def test_entry_that_cannot_be_sized_is_booked_instead_of_vanishing():
    # 0.0000001 cash at a price of 100 buys 0.000000001 units, below the 1e-8 lot floor.
    cfg = config()
    result = simulate(prices(12), cfg, POLICY, FREE, fitted(), initial_cash=Decimal("0.0000001"))
    assert not result.fills and result.final_equity == Decimal("0.0000001")
    first = result.rejections[0]
    assert first.reason_order == ("ENTRY_SIZE_NOT_POSITIVE",)
    assert first.decision_at == result.decisions[0][0] == START + timedelta(hours=1, seconds=1)
    assert first.available_price == Decimal(100)
    assert first.outcome == "NOT_SIMULATED" and first.forward_net_return is None
    assert first.features == (
        ("config_hash", cfg.content_hash()),
        ("simulator_version", "spot-event.v1"),
        ("refused_at", (START + timedelta(hours=2)).isoformat()),
        ("reference_open", "100"),
        ("cash", "0.0000001"),
    )
    # Nine refused proposals, then the last two publications find the tenth still pending.
    assert [r.reason_order[0] for r in result.rejections] == (
        ["ENTRY_SIZE_NOT_POSITIVE"] * 9 + ["ENTRY_ALREADY_PENDING"] * 2
    )


def test_entry_whose_rounded_cost_exceeds_cash_is_booked_and_the_next_one_fills():
    # Open 101.25: price 101.25 * 1.00045 = 101.2955625; size = 10000 / (101.2955625 * 1.001)
    # floored to 98.62238526; notional rounds up to 9990.00999001 and the fee to 9.99001000,
    # together 10000.00000001, one unit more than the 10000 cash.
    result = simulate(unaffordable_prices(), config(), POLICY, CostModel(), fitted())
    refused = result.rejections[0]
    assert refused.reason_order == ("ENTRY_COST_EXCEEDS_CASH",)
    assert refused.decision_at == START + timedelta(hours=1, seconds=1)
    assert dict(refused.features)["refused_at"] == (START + timedelta(hours=2)).isoformat()
    assert dict(refused.features)["reference_open"] == "101.25"
    assert dict(refused.features)["cash"] == "10000"
    assert refused.outcome == "NOT_SIMULATED"
    assert result.fills[0].at == START + timedelta(hours=3)
    assert result.fills[0].decision_at == START + timedelta(hours=2, seconds=1)


def test_signals_blocked_by_an_open_position_or_a_pending_entry_are_booked():
    cfg = config()
    held = simulate(ending_prices(110), cfg, POLICY, FREE, fitted())
    # Entry at 02:00; publications 02:00:01 .. 10:00:01 find the position open. After the
    # terminal exit the 11:00:01 proposal can never fill, and 12:00:01 finds it pending.
    assert [r.reason_order for r in held.rejections] == (
        [("POSITION_ALREADY_OPEN",)] * 9 + [("ENTRY_ALREADY_PENDING",)]
    )
    first = held.rejections[0]
    assert first.decision_at == START + timedelta(hours=2, seconds=1)
    assert first.available_price == Decimal(100)
    assert first.outcome == "NOT_SIMULATED" and first.forward_net_return is None
    assert first.features == (
        ("config_hash", cfg.content_hash()),
        ("simulator_version", "spot-event.v1"),
    )
    assert len(held.decisions) == 2 and len(held.fills) == 2
    # Two-hour latency: the 01:00:01 proposal is eligible at 03:00:01 and fills at 04:00,
    # so the 02:00:01 and 03:00:01 publications are blocked by the pending entry.
    waiting = simulate(prices(12), cfg, POLICY, SLOW, fitted())
    assert waiting.fills[0].at == START + timedelta(hours=4)
    assert [(r.decision_at, r.reason_order) for r in waiting.rejections[:3]] == [
        (START + timedelta(hours=2, seconds=1), ("ENTRY_ALREADY_PENDING",)),
        (START + timedelta(hours=3, seconds=1), ("ENTRY_ALREADY_PENDING",)),
        (START + timedelta(hours=4, seconds=1), ("POSITION_ALREADY_OPEN",)),
    ]


def test_blocked_signal_keeps_both_reasons_in_evaluation_order_and_is_not_resolved():
    def then_filtered(history, cfg, fit):
        return len(history) >= 25, None if len(history) == 25 else "VOLATILITY_FILTER"

    bars = prices(40)
    cfg = config("FIXED_RULE")
    result = simulate(bars, cfg, POLICY, FREE, fitted(), signal=then_filtered)
    assert result.fills[0].at == START + timedelta(hours=26)
    assert result.rejections[0].reason_order == ("POSITION_ALREADY_OPEN", "VOLATILITY_FILTER")
    book = resolve_counterfactuals(result, bars, cfg, POLICY, FREE, fitted())
    # Thirteen publications (26:00:01 .. 38:00:01) meet the open position; the two after the
    # terminal exit are plain filter rejections too close to the end to resolve.
    assert book == result.rejections
    assert [r.outcome for r in book] == ["NOT_SIMULATED"] * 13 + ["UNOBSERVABLE"] * 2


def test_pending_entry_expired_by_an_outage_is_booked_as_that_candidate():
    proof = outage()
    cfg = config("FIXED_RULE")
    result = simulate(
        halted_prices(proof), cfg, POLICY, FREE, fitted(), signal=into_halt, outages=(proof,)
    )
    # Proposed at 36:00:01 for the 37:00 open; the venue halts at 36:27 before it can fill.
    proposed = START + timedelta(hours=36, seconds=1)
    assert result.decisions == ((proposed, "LONG_PROPOSAL"),) and not result.fills
    expired, unavailable = result.rejections
    assert expired.reason_order == ("PENDING_ENTRY_EXPIRED_VENUE_UNAVAILABLE",)
    assert expired.decision_at == proposed and expired.available_price == Decimal(100)
    assert expired.outcome == "UNOBSERVABLE" and expired.forward_net_return is None
    assert dict(expired.features)["expired_at"] == proof.start.isoformat()
    assert unavailable.reason_order == ("DATA_UNAVAILABLE_FEATURES_UNOBSERVABLE",)
    assert unavailable.decision_at == proof.start and unavailable.available_price is None
