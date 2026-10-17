"""Defined research statistics; daily portfolio returns and dependent-block uncertainty."""

import math
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import mean, stdev

from auvexo_alpha.application.research_simulator import SimulationResult


@dataclass(frozen=True)
class Statistic:
    value: Decimal | float | int | None
    reason: str | None = None


def ratio(numerator: Decimal | float, denominator: Decimal | float) -> Statistic:
    if denominator == 0:
        return Statistic(None, "ZERO_DENOMINATOR")
    return Statistic(float(numerator) / float(denominator))


def daily_returns(result: SimulationResult) -> tuple[tuple[date, Decimal], ...]:
    closes = {
        (point.at - timedelta(microseconds=1)).date(): point.equity for point in result.equity
    }
    if not closes:
        return ()
    previous = result.initial_cash
    values = []
    day, final = min(closes), max(closes)
    while day <= final:
        current = closes.get(day, previous)
        values.append((day, current / previous - 1 if previous else Decimal(0)))
        previous = current
        day += timedelta(days=1)
    return tuple(values)


def metrics(result: SimulationResult) -> dict[str, object]:
    trades = result.trades
    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [t.pnl for t in trades if t.pnl < 0]
    returns = [float(r) for _, r in daily_returns(result)]
    peak, drawdown = result.initial_cash, Decimal(0)
    longest = current = 0
    recovery_hours: list[float] = []
    underwater_since = None
    peak_at = result.equity[0].at if result.equity else None
    max_duration_hours = 0.0
    exposure = []
    for point in result.equity:
        if point.equity >= peak:
            peak = point.equity
            if underwater_since is not None:
                recovery_hours.append((point.at - underwater_since).total_seconds() / 3600)
                max_duration_hours = max(max_duration_hours, recovery_hours[-1])
            underwater_since, current = None, 0
            peak_at = point.at
        else:
            if underwater_since is None:
                underwater_since = peak_at
            current += 1
            longest = max(longest, current)
            if underwater_since is not None:
                max_duration_hours = max(
                    max_duration_hours, (point.at - underwater_since).total_seconds() / 3600
                )
        drawdown = max(drawdown, 1 - point.equity / peak)
        exposure.append(point.position_value / point.equity if point.equity else Decimal(0))
    net = result.final_equity / result.initial_cash - 1
    annual_log = (
        math.log(float(result.final_equity / result.initial_cash)) * 365 / len(returns)
        if returns and result.final_equity > 0
        else None
    )
    annual_return = math.expm1(annual_log) if annual_log is not None and annual_log < 700 else None
    downside = math.sqrt(mean(min(0, r) ** 2 for r in returns)) if returns else 0
    groups: dict[str, dict[str, object]] = {}
    for key in sorted(
        {"regime:" + t.regime for t in trades} | {"session:" + t.session for t in trades}
    ):
        subset = [t for t in trades if key in ("regime:" + t.regime, "session:" + t.session)]
        groups[key] = {"count": len(subset), "net_pnl": sum((t.pnl for t in subset), Decimal(0))}
    undefined = Statistic(None, "INSUFFICIENT_OBSERVATIONS")
    return {
        "label": "SIMULATED_PERSONAL_NONPRODUCTION",
        "instrument": result.instrument,
        "closed_trades": len(trades),
        "net_pnl": result.final_equity - result.initial_cash,
        "net_return": net,
        "expectancy": Statistic(sum((t.pnl for t in trades), Decimal(0)) / len(trades))
        if trades
        else undefined,
        "profit_factor": ratio(sum(wins, Decimal(0)), -sum(losses, Decimal(0))),
        "max_drawdown": drawdown,
        "max_underwater_observation_count": longest,
        "max_drawdown_duration_hours": max_duration_hours,
        "recovery_hours": tuple(recovery_hours),
        "unrecovered": underwater_since is not None,
        "sharpe_daily_365_rf0": ratio(mean(returns) * math.sqrt(365), stdev(returns))
        if len(returns) > 1
        else undefined,
        "sortino_daily_365_rf0": ratio(mean(returns) * math.sqrt(365), downside)
        if returns
        else undefined,
        "calmar": ratio(annual_return, drawdown) if annual_return is not None else undefined,
        "win_rate": Statistic(Decimal(len(wins)) / len(trades)) if trades else undefined,
        "average_win": Statistic(sum(wins) / len(wins)) if wins else Statistic(None, "NO_WINNERS"),
        "average_loss": Statistic(sum(losses) / len(losses))
        if losses
        else Statistic(None, "NO_LOSERS"),
        "average_r": Statistic(
            sum((t.pnl / t.initial_risk for t in trades), Decimal(0)) / len(trades)
        )
        if trades
        else undefined,
        "turnover_notional": sum((f.notional for f in result.fills), Decimal(0)),
        "turnover_initial_equity": sum((f.notional for f in result.fills), Decimal(0))
        / result.initial_cash,
        "fees": sum((f.fee for f in result.fills), Decimal(0)),
        "modeled_spread_cost": sum((f.spread_cost for f in result.fills), Decimal(0)),
        "modeled_slippage_cost": sum((f.slippage_cost for f in result.fills), Decimal(0)),
        "mean_gross_and_net_long_spot_exposure": sum(exposure, Decimal(0)) / len(exposure)
        if exposure
        else Decimal(0),
        "expected_shortfall_daily_5pct": Statistic(
            mean(sorted(returns)[: max(1, math.ceil(len(returns) * 0.05))])
        )
        if returns
        else undefined,
        "daily_sample_size": len(returns),
        "segments": groups,
        "outage_exposure": result.outage_exposure,
        "stale_unavailable_marks": sum(p.mark_state == "STALE_UNAVAILABLE" for p in result.equity),
        "definitions": (
            "Trade expectancy in quote currency; long/flat spot; drawdown on recorded equity; "
            "365 daily annualization, zero risk-free rate. Outage marks are explicitly stale. "
            "Costs are assumptions, not historical executable bid/ask."
        ),
    }


def block_uncertainty(
    result: SimulationResult,
    *,
    seed: int = 1229,
    draws: int = 2000,
    block_days: int = 14,
    comparisons: int = 4,
) -> dict[str, object]:
    days = [day for day, _ in daily_returns(result)]
    if not days or not result.trades:
        return {
            "lower_95": None,
            "upper_95": None,
            "adjusted_lower": None,
            "reason": "NO_CLOSED_TRADES_OR_DAYS",
            "draws": draws,
        }
    if draws < 1000 or block_days < 1 or comparisons < 1:
        raise ValueError("INVALID_UNCERTAINTY_CONFIGURATION")
    pnl: dict[date, Decimal] = defaultdict(Decimal)
    counts: dict[date, int] = defaultdict(int)
    for trade in result.trades:
        pnl[trade.exit_at.date()] += trade.pnl
        counts[trade.exit_at.date()] += 1
    pairs = [(float(pnl[d]), counts[d]) for d in days]
    rng = random.Random(seed)
    estimates = []
    for _ in range(draws):
        total, count, sampled = 0.0, 0, 0
        while sampled < len(days):
            start = rng.randrange(len(days))
            take = min(block_days, len(days) - sampled)
            for offset in range(take):
                value, number = pairs[(start + offset) % len(days)]
                total += value
                count += number
            sampled += take
        if count:
            estimates.append(total / count)
    estimates.sort()

    def quantile(p: float) -> float | None:
        return estimates[min(len(estimates) - 1, int(p * len(estimates)))] if estimates else None

    return {
        "method": "CIRCULAR_DAILY_BLOCK_TRADE_PNL_AND_COUNT_RATIO",
        "draws": draws,
        "valid_draws": len(estimates),
        "block_days": block_days,
        "comparisons": comparisons,
        "lower_95": quantile(0.025),
        "upper_95": quantile(0.975),
        "adjusted_lower": quantile(0.025 / comparisons),
        "adjustment": "BONFERRONI_TWO_SIDED_FAMILYWISE_95_PERCENT",
        "limitation": "Finite bootstrap and overlapping trades do not establish live alpha",
    }


def permutation_sensitivity(result: SimulationResult, seed: int = 1229) -> dict[str, object]:
    values = [trade.pnl for trade in result.trades]
    rng = random.Random(seed)
    worst = Decimal(0)
    for _ in range(200):
        rng.shuffle(values)
        equity = peak = result.initial_cash
        for pnl in values:
            equity += pnl
            peak = max(peak, equity)
            worst = max(worst, 1 - equity / peak)
    return {
        "worst_drawdown_200_permutations": worst,
        "limitation": "Sensitivity only; ordering destroys serial dependence",
    }
