from dataclasses import asdict, replace
from datetime import timedelta
from decimal import Decimal

from research_fixtures import START, config, fitted, prices
from test_research_simulator import FREE, POLICY, ending_prices

from auvexo_alpha.application.research_metrics import block_uncertainty, daily_returns, metrics
from auvexo_alpha.application.research_simulator import EquityPoint, artifact_bytes, simulate


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
