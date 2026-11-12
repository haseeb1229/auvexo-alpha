"""Hand-computed decision fixtures for the frozen baseline rules; synthetic prices only.

Every expected decision below is worked out from the literal numbers in the test, never by
calling the implementation's own helpers.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from research_fixtures import START, closes, config, prices, reprice

from auvexo_alpha.application.research_simulator import (
    FittedFeatures,
    baseline_signal,
    simulate,
)
from auvexo_alpha.domain.research import CostModel, PriceAvailability

POLICY = PriceAvailability(lag_microseconds=1_000_000)
FREE = CostModel(fee_bps="0", spread_bps="0", slippage_bps="0")


def threshold(value):
    return FittedFeatures(START - timedelta(days=365), START, Decimal(value))


OPEN_FILTER = threshold("1")


def test_no_trade_and_passive_ignore_prices():
    one = closes(100)
    assert baseline_signal(one, config("NO_TRADE"), OPEN_FILTER) == (False, None)
    assert baseline_signal(one, config("PASSIVE"), OPEN_FILTER) == (True, None)


@pytest.mark.parametrize(
    "close,expected",
    [
        # Highest high of the three previous bars is max(101, 105, 103) = 105.
        ("104.99", False),
        ("105", False),  # equal to the previous-window high is not "above" it
        ("105.01", True),
    ],
)
def test_breakout_needs_a_close_strictly_above_the_previous_window_high(close, expected):
    history = closes(100, 100, 100, close, highs=(101, 105, 103, 110))
    assert baseline_signal(history, config("BREAKOUT", lookback=3), OPEN_FILTER) == (expected, None)


def test_breakout_window_is_exactly_the_previous_lookback_bars_and_uses_highs():
    cfg = config("BREAKOUT", lookback=3)
    # The 200 high is four bars back, outside a three-bar window: 105.01 > 105 still triggers.
    older = closes(100, 100, 100, 100, "105.01", highs=(200, 101, 105, 103, 110))
    assert baseline_signal(older, cfg, OPEN_FILTER) == (True, None)
    # 104 is above every previous close (100) but below the previous high 105: no breakout.
    wicks = closes(100, 100, 100, 104, highs=(101, 105, 103, 104))
    assert baseline_signal(wicks, cfg, OPEN_FILTER) == (False, None)
    # Three bars cannot supply three previous bars plus the decision bar.
    assert baseline_signal(closes(100, 100, 300), cfg, OPEN_FILTER) == (False, None)


@pytest.mark.parametrize(
    "values,expected",
    [
        # The reference is the close three bars before the decision bar (the first value).
        ((100, 120, 95, "99.99"), False),
        ((100, 120, 95, 100), False),  # equal is not a rise
        ((100, 120, 95, "100.01"), True),  # above 100 although below the intervening 120
        ((100, 80, 85, "99.99"), False),  # above the two latest closes, still below 100
        ((50, 100, 120, 95, 100), False),  # 50 is four bars back and must not be the reference
        ((150, 100, 90, 95, "100.5"), True),  # nor may an older, higher close block it
    ],
)
def test_fixed_rule_compares_the_close_with_the_close_one_lookback_earlier(values, expected):
    cfg = config("FIXED_RULE", lookback=3)
    assert baseline_signal(closes(*values), cfg, OPEN_FILTER) == (expected, None)
    assert baseline_signal(closes(*values[-3:]), cfg, OPEN_FILTER) == (False, None)


@pytest.mark.parametrize(
    "close,expected",
    [
        # Previous four closes 104, 96, 102, 98: mean = 400 / 4 = 100.
        # Trigger level = 100 * (1 - 0.015) = 98.5; "at least 1.5% below" includes 98.5.
        ("98.51", False),
        ("98.5", True),
        ("98.49", True),
    ],
)
def test_mean_reversion_triggers_at_or_below_the_deviation_level(close, expected):
    cfg = config("MEAN_REVERSION", lookback=4)
    history = closes(104, 96, 102, 98, close)
    assert baseline_signal(history, cfg, OPEN_FILTER) == (expected, None)


def test_mean_reversion_mean_excludes_the_decision_bar_and_older_bars():
    cfg = config("MEAN_REVERSION", lookback=4)
    # Correct window (104, 96, 102, 98) has mean 100, so 98.5 triggers. Including the older
    # close 60 instead would give (60 + 104 + 96 + 102 + 98) / 5 = 92 and no trigger at 90.62.
    assert baseline_signal(closes(60, 104, 96, 102, 98, "98.5"), cfg, OPEN_FILTER) == (True, None)
    # Including the decision bar would give (96 + 102 + 98 + 98.5) / 4 = 98.625 and no trigger.
    assert baseline_signal(closes(104, 96, 102, 98, "98.5"), cfg, OPEN_FILTER) == (True, None)
    # Four bars cannot supply four previous closes plus the decision bar.
    assert baseline_signal(closes(96, 102, 98, "90"), cfg, OPEN_FILTER) == (False, None)


@pytest.mark.parametrize(
    "median,reason",
    [
        # Twenty-four closes of 100 then 98.5: twenty-three zero returns and one of
        # |98.5 / 100 - 1| = 0.015, so the 24h mean absolute return is 0.015 / 24 = 0.000625.
        ("0.000626", None),
        ("0.000625", None),  # "at/below the training median" admits equality
        ("0.000624", "VOLATILITY_FILTER"),
    ],
)
def test_mean_reversion_volatility_filter_admits_at_or_below_the_training_median(median, reason):
    cfg = config("MEAN_REVERSION", lookback=24)
    history = closes(*([100] * 24), "98.5")
    assert baseline_signal(history, cfg, threshold(median)) == (True, reason)


def test_volatility_filter_uses_only_the_last_25_bars_and_never_labels_a_non_signal():
    cfg = config("MEAN_REVERSION", lookback=24)
    # The 200 -> 100 collapse is 26 bars back: outside the 24-return window, so the
    # volatility is still 0.000625. Counting it would give (0.5 + 0.015) / 25 = 0.0206.
    history = closes(200, *([100] * 24), "98.5")
    assert baseline_signal(history, cfg, threshold("0.000625")) == (True, None)
    # 99 is only 1% below the mean of 100: no signal, so no filter reason either, even
    # though its volatility 0.01 / 24 exceeds a zero threshold.
    quiet = closes(*([100] * 24), 99)
    assert baseline_signal(quiet, cfg, threshold("0")) == (False, None)


def test_equality_boundary_close_becomes_a_filled_entry_in_the_replay():
    # Bar 24 closes at exactly 98.5 against a 24-bar mean of 100. Its volatility 0.000625
    # is below the 0.01 training threshold, so the proposal is not filtered.
    bars = prices(30)
    bars[24] = reprice(bars[24], close="98.5", low="98.5")
    cfg = config("MEAN_REVERSION", lookback=24)
    result = simulate(bars, cfg, POLICY, FREE, threshold("0.01"))
    # Published one second after the 25:00 close; first open after the 1 s latency is 26:00.
    assert result.decisions[0] == (START + timedelta(hours=25, seconds=1), "LONG_PROPOSAL")
    assert result.fills[0].side == "BUY" and result.fills[0].at == START + timedelta(hours=26)
    assert result.fills[0].price == Decimal(100) and result.fills[0].quantity == Decimal(100)
    off = list(bars)
    off[24] = reprice(off[24], close="98.51", low="98.51")
    assert not simulate(off, cfg, POLICY, FREE, threshold("0.01")).decisions
