from dataclasses import asdict, replace
from datetime import date, timedelta
from decimal import Decimal, localcontext

import pytest
from research_fixtures import START, config, fitted, prices, synthetic_result
from test_research_simulator import FREE, POLICY, ending_prices

from auvexo_alpha.application.research_metrics import (
    block_uncertainty,
    daily_returns,
    metrics,
    permutation_sensitivity,
)
from auvexo_alpha.application.research_simulator import EquityPoint, artifact_bytes, simulate
from auvexo_alpha.domain.research import CostModel


def test_no_trade_undefined_statistics_are_explicit():
    result = simulate(prices(48), config("NO_TRADE"), POLICY, FREE, fitted())
    report = metrics(result)
    assert report["net_pnl"] == 0 and report["max_drawdown"] == 0
    for name in ("sharpe_daily_365_rf0", "sortino_daily_365_rf0", "profit_factor", "calmar"):
        assert report[name].value is None and report[name].reason
    assert block_uncertainty(result)["reason"] == "NO_CLOSED_TRADES_OR_DAYS"
    assert len(daily_returns(result)) == 2
    artifact_bytes(asdict(report["sharpe_daily_365_rf0"]))


def test_hand_drawdown_recovery_and_daily_returns():
    result = simulate(ending_prices(110), config(), POLICY, FREE, fitted())
    result = replace(
        result,
        equity=tuple(
            EquityPoint(
                START + timedelta(days=i, hours=23),
                Decimal(value),
                Decimal(0),
                Decimal(0),
                Decimal(value),
            )
            for i, value in enumerate(("10000", "11000", "8800", "11000"))
        ),
    )
    report = metrics(result)
    assert report["expectancy"].value == Decimal(1000)
    assert report["max_drawdown"] == Decimal("0.2")
    assert report["max_drawdown_duration_hours"] == 48
    assert report["recovery_hours"] == (48,)
    assert not report["unrecovered"]
    assert daily_returns(result)[2][1] == Decimal("-0.2")
    uncertainty = block_uncertainty(result, draws=1000, block_days=2)
    assert uncertainty == block_uncertainty(result, draws=1000, block_days=2)
    assert uncertainty["lower_95"] == 1000
    assert uncertainty["adjusted_lower"] <= uncertainty["lower_95"]


def test_literal_risk_statistics_on_a_four_day_series():
    # Daily closes from 10000: x1.03, x0.97, x1.03, x0.99.
    result = synthetic_result(
        ["10300", "9991", "10290.73", "10187.8227"],
        [(0, "300"), (1, "-100"), (1, "150"), (2, "150"), (3, "-140"), (3, "0")],
    )
    assert daily_returns(result) == (
        (date(2024, 1, 1), Decimal("0.03")),
        (date(2024, 1, 2), Decimal("-0.03")),
        (date(2024, 1, 3), Decimal("0.03")),
        (date(2024, 1, 4), Decimal("-0.01")),
    )
    report = metrics(result)
    # Mean return (0.03 - 0.03 + 0.03 - 0.01) / 4 = 0.005. Deviations 0.025, -0.035, 0.025,
    # -0.015; squares sum 0.000625 + 0.001225 + 0.000625 + 0.000225 = 0.0027; sample
    # variance 0.0027 / 3 = 0.0009; deviation 0.03. Sharpe = 0.005 * sqrt(365) / 0.03
    # = 19.1049731745428 / 6.
    assert report["sharpe_daily_365_rf0"].value == pytest.approx(3.18416219575713, rel=1e-12)
    # Downside deviation sqrt((0.03^2 + 0.01^2) / 4) = sqrt(0.00025) = 0.0158113883.
    # Sortino = 0.005 * sqrt(365) / 0.0158113883 = sqrt(36.5).
    assert report["sortino_daily_365_rf0"].value == pytest.approx(6.04152298679729, rel=1e-12)
    # Peak 10300, trough 9991: 1 - 9991 / 10300 = 0.03; later closes stay below the peak.
    assert report["max_drawdown"] == Decimal("0.03")
    assert report["unrecovered"] and report["max_underwater_observation_count"] == 3
    # Wins 300 + 150 + 150 = 600; losses 100 + 140 = 240; the zero trade is neither.
    assert report["profit_factor"].value == 2.5
    assert report["win_rate"].value == Decimal("0.5")  # 3 winners / 6 closed trades
    assert report["expectancy"].value == Decimal(60)  # (600 - 240) / 6
    assert report["average_win"].value == Decimal(200)
    assert report["average_loss"].value == Decimal(-120)
    # Initial risk 200 each: (1.5 - 0.5 + 0.75 + 0.75 - 0.7 + 0) / 6 = 0.3.
    assert report["average_r"].value == Decimal("0.3")
    assert report["net_return"] == Decimal("0.01878227")
    assert report["expected_shortfall_daily_5pct"].value == -0.03  # worst one of four days
    # Four days compounded to a 365-day year, over the 3% drawdown.
    assert report["calmar"].value == pytest.approx((1.01878227**91.25 - 1) / 0.03, rel=1e-9)
    assert report["closed_trades"] == 6 and report["daily_sample_size"] == 4


def alternating(days=30):
    """One closed trade per day: +300 on even days, -280 on odd days; expectancy exactly 10."""
    trades = [(day, "300" if day % 2 == 0 else "-280") for day in range(days)]
    return synthetic_result(["10000"] * days, trades)


def bounds(block_days, comparisons=4):
    report = block_uncertainty(alternating(), block_days=block_days, comparisons=comparisons)
    return report["adjusted_lower"], report["lower_95"], report["upper_95"]


def test_block_bootstrap_preserves_alternating_dependence_that_daily_resampling_destroys():
    # Any even circular block holds as many +300 as -280 days, so every resample totals
    # 15 * 300 - 15 * 280 = 300 over 30 trades: a degenerate interval at exactly 10.
    for block_days in (2, 14, 30):
        assert bounds(block_days) == (10.0, 10.0, 10.0)
    # Three-day blocks total +320 (even start) or -260 (odd start). With a of ten blocks
    # starting even the estimate is (320a - 260(10 - a)) / 30. Binomial(10, 1/2) puts 1.07%
    # at a <= 1 and 5.47% at a <= 2, so the 2.5% point is a = 2: (640 - 2080) / 30 = -48;
    # by symmetry the 97.5% point is a = 8: (2560 - 520) / 30 = 68.
    adjusted_3, lower_3, upper_3 = bounds(3)
    assert (lower_3, upper_3) == (-48.0, 68.0)
    # The Bonferroni point 0.625% sits further out, at a <= 1: at most (320 - 2340) / 30.
    assert adjusted_3 <= -2020 / 30 < lower_3
    # Independent daily draws: k winning days give (300k - 280(30 - k)) / 30, deviation
    # 290 / sqrt(30) = 52.9, so the interval straddles zero and is wider still.
    adjusted_1, lower_1, upper_1 = bounds(1)
    assert adjusted_1 < lower_1 < 0 < 10 < upper_1
    assert upper_1 - lower_1 > upper_3 - lower_3 > 0
    for estimate in (adjusted_1, lower_1, upper_1):
        winners = (estimate * 30 + 8400) / 580
        assert winners == pytest.approx(round(winners), abs=1e-9)
    # A single comparison needs no adjustment.
    assert bounds(1, comparisons=1)[0] == bounds(1, comparisons=1)[1] == lower_1


def test_statistics_do_not_depend_on_the_ambient_decimal_context():
    result = simulate(ending_prices(110), config(), POLICY, CostModel(), fitted())
    expected = (
        artifact_bytes(metrics(result)),
        daily_returns(result),
        block_uncertainty(result, draws=1000, block_days=2),
        permutation_sensitivity(result),
    )
    with localcontext() as context:
        context.prec = 9
        observed = (
            artifact_bytes(metrics(result)),
            daily_returns(result),
            block_uncertainty(result, draws=1000, block_days=2),
            permutation_sensitivity(result),
        )
    assert observed == expected
    assert metrics(result)["net_return"] == Decimal("0.096814620227")
    # One third of the peak left: 1 - 10000 / 30000 carried to the pinned 50 digits.
    third = synthetic_result(["10000"], initial="30000")
    assert metrics(third)["max_drawdown"] == Decimal("0." + "6" * 49 + "7")
