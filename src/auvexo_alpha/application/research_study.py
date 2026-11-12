"""Frozen generic Phase 3 grids, selection and conservative nonproduction screens."""

from decimal import Decimal

from auvexo_alpha.application.research_metrics import metrics, pinned
from auvexo_alpha.application.research_simulator import SimulationResult
from auvexo_alpha.domain.research import StrategyConfig


def frozen_configs() -> tuple[StrategyConfig, ...]:
    definitions = (
        ("NO_TRADE", 24, 24),
        ("PASSIVE", 24, 24),
        ("FIXED_RULE", 24, 24),
        ("BREAKOUT", 72, 48),
        ("BREAKOUT", 168, 48),
        ("MEAN_REVERSION", 24, 24),
        ("MEAN_REVERSION", 72, 24),
    )
    return tuple(
        StrategyConfig.model_validate(
            dict(
                family=family,
                lookback=lookback,
                holding_bars=holding,
                exposure_fraction="0.25",
                stop_fraction="0.02",
                target_fraction="0.04",
                deviation_fraction="0.015",
                entry_fill_fraction="1",
            )
        )
        for family, lookback, holding in definitions
    )


@pinned
def select_validation(
    configs: tuple[StrategyConfig, ...],
    validation: dict[str, SimulationResult],
) -> tuple[str, ...]:
    if set(validation) != {c.content_hash() for c in configs}:
        raise ValueError("INCOMPLETE_VALIDATION_SELECTION")
    chosen = []
    for family in ("NO_TRADE", "PASSIVE", "FIXED_RULE", "BREAKOUT", "MEAN_REVERSION"):
        candidates = sorted(
            (c.content_hash() for c in configs if c.family == family),
            key=lambda h: (-validation[h].final_equity, h),
        )
        if not candidates:
            raise ValueError("MISSING_PREREGISTERED_FAMILY")
        chosen.append(candidates[0])
    return tuple(chosen)


@pinned
def screen(
    result: SimulationResult,
    uncertainty: dict[str, object],
    stress_results: tuple[SimulationResult, ...],
    stable_neighbors: bool,
    *,
    max_drawdown: Decimal,
) -> dict[str, object]:
    """Apply the preregistered screens; the caller supplies the study's registered limits."""
    stats = metrics(result)
    points = result.equity
    months = ((points[-1].at - points[0].at).days / 30.4375) if points else 0
    lower = uncertainty.get("adjusted_lower")
    unadjusted = uncertainty.get("lower_95")
    drawdown = stats["max_drawdown"]
    assert isinstance(drawdown, Decimal)
    regimes = tuple(sorted({t.regime for t in result.trades}))
    net_trade_pnl = sum((t.pnl for t in result.trades), Decimal(0))
    reasons = []
    if len(result.trades) < 100:
        reasons.append("FEWER_THAN_100_CLOSED_OOS_TRADES")
    if months < 6:
        reasons.append("FEWER_THAN_SIX_OOS_MONTHS")
    if len(regimes) < 2:
        reasons.append("SINGLE_OR_NO_OBSERVED_REGIME")
    if net_trade_pnl <= 0:
        reasons.append("NONPOSITIVE_NET_EXPECTANCY")
    if not isinstance(lower, (int, float)) or lower <= 0:
        reasons.append("BONFERRONI_BLOCK_LOWER_NOT_POSITIVE")
    if not isinstance(unadjusted, (int, float)) or unadjusted <= 0:
        reasons.append("DEPENDENCE_AWARE_95_LOWER_NOT_POSITIVE")
    if not stress_results or any(r.final_equity <= r.initial_cash for r in stress_results):
        reasons.append("COST_STRESS_NOT_SURVIVED")
    if not stable_neighbors:
        reasons.append("PREREGISTERED_VALIDATION_NEIGHBORS_UNSTABLE")
    if drawdown > max_drawdown:
        percent = format((max_drawdown * 100).normalize(), "f")
        reasons.append(f"DRAWDOWN_EXCEEDS_{percent}_PERCENT")
    insufficient = any(r.startswith(("FEWER_", "SINGLE_")) for r in reasons)
    return {
        "verdict": "INCONCLUSIVE" if insufficient else "NO_EDGE" if reasons else "CANDIDATE",
        "reasons": tuple(reasons),
        "oos_months_approx": months,
        "data_use": "PERSONAL_RESEARCH_NONPRODUCTION_ONLY",
        "promotion_eligible": False,
        # Exactly what was evaluated, so a recorded verdict can be re-derived without a rerun.
        "inputs": {
            "closed_trades": len(result.trades),
            "observed_regimes": regimes,
            "net_trade_pnl": net_trade_pnl,
            "uncertainty": uncertainty,
            "stress_equity": tuple((r.initial_cash, r.final_equity) for r in stress_results),
            "stable_neighbors": stable_neighbors,
            "max_drawdown": drawdown,
            "max_drawdown_limit": max_drawdown,
        },
    }
