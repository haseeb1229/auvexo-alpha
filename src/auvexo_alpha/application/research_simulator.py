"""Deterministic OHLC research replay, explicitly SIMULATED and never broker facts."""

import hashlib
import json
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext
from statistics import median
from typing import Literal, Protocol

from auvexo_alpha.domain.contracts import exact_decimal
from auvexo_alpha.domain.market_data import Candle
from auvexo_alpha.domain.research import CostModel, PriceAvailability, StrategyConfig
from auvexo_alpha.domain.research_gaps import VenueUnavailable

Q = Decimal("0.00000001")
ZERO = Decimal(0)


def money(value: Decimal, up: bool = False) -> Decimal:
    return value.quantize(Q, rounding=ROUND_CEILING if up else ROUND_FLOOR)


def artifact_bytes(value: object) -> bytes:
    def encode(item: object) -> object:
        if is_dataclass(item) and not isinstance(item, type):
            return asdict(item)
        if isinstance(item, Decimal):
            return format(item, "f")
        if isinstance(item, datetime):
            return item.isoformat()
        raise TypeError("unsupported research artifact value")

    return json.dumps(
        value, default=encode, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


@dataclass(frozen=True)
class FittedFeatures:
    train_start: datetime
    train_end: datetime
    volatility_threshold: Decimal
    version: str = "causal-price.v1"


def volatility(history: Sequence[Candle]) -> Decimal:
    tail = history[-25:]
    returns = [abs(b.close / a.close - 1) for a, b in zip(tail, tail[1:], strict=False)]
    return sum(returns, ZERO) / len(returns) if returns else ZERO


def fit_features(
    bars: Sequence[Candle],
    start: datetime,
    end: datetime,
    phase: str = "TRAIN",
    outages: tuple[VenueUnavailable, ...] = (),
) -> FittedFeatures:
    if phase != "TRAIN" or not bars or any(not start <= b.open_at < end for b in bars):
        raise ValueError("FEATURE_FIT_REQUIRES_TRAIN_ONLY")
    with localcontext() as context:
        context.prec = 50
        values = [
            volatility(bars[i - 24 : i + 1])
            for i in range(24, len(bars))
            if feature_window_available(bars[i - 24 : i + 1], 25, outages)
        ]
        if not values:
            raise ValueError("INSUFFICIENT_TRAINING_HISTORY")
        return FittedFeatures(start, end, median(values))


class SignalRule(Protocol):
    def __call__(
        self, history: Sequence[Candle], config: StrategyConfig, fitted: FittedFeatures
    ) -> tuple[bool, str | None]: ...


def baseline_signal(
    history: Sequence[Candle], config: StrategyConfig, fitted: FittedFeatures
) -> tuple[bool, str | None]:
    if config.family == "NO_TRADE":
        return False, None
    if config.family == "PASSIVE":
        return True, None
    if len(history) < config.lookback + 1:
        return False, None
    previous = history[-config.lookback - 1 : -1]
    close = history[-1].close
    if config.family == "BREAKOUT":
        return close > max(b.high for b in previous), None
    if config.family == "FIXED_RULE":
        return close > previous[0].close, None
    mean = sum((b.close for b in previous), ZERO) / len(previous)
    raw = close < mean * (1 - config.deviation_fraction)
    return raw, "VOLATILITY_FILTER" if raw and volatility(
        history
    ) > fitted.volatility_threshold else None


@dataclass(frozen=True)
class SimulatedFill:
    label: Literal["SIMULATED"]
    side: Literal["BUY", "SELL"]
    at: datetime
    decision_at: datetime
    quantity: Decimal
    reference_price: Decimal
    price: Decimal
    notional: Decimal
    fee: Decimal
    spread_cost: Decimal
    slippage_cost: Decimal
    reason: str
    intent_hash: str


@dataclass(frozen=True)
class SimulatedTrade:
    entry_at: datetime
    exit_at: datetime
    quantity: Decimal
    pnl: Decimal
    initial_risk: Decimal
    reason: str
    regime: str
    session: str


@dataclass(frozen=True)
class EquityPoint:
    at: datetime
    cash: Decimal
    holdings: Decimal
    position_value: Decimal
    equity: Decimal
    mark_state: Literal["OBSERVED", "STALE_UNAVAILABLE"] = "OBSERVED"


@dataclass(frozen=True)
class OutageExposure:
    start: datetime
    end: datetime
    holdings: Decimal
    last_observable_mark: Decimal


@dataclass(frozen=True)
class RejectedCandidate:
    candidate_hash: str
    decision_at: datetime
    instrument: str
    evidence_hash: str
    available_price: Decimal | None
    features: tuple[tuple[str, str], ...]
    reason_order: tuple[str, ...]
    horizon_bars: int
    outcome: Literal["UNOBSERVABLE", "SIMULATED"]
    forward_net_return: Decimal | None
    limitation: str = "Individual overlapping counterfactuals are never portfolio profit"


def rejected_candidate(
    at: datetime,
    instrument: str,
    evidence_hash: str,
    reason: str,
    price: Decimal | None,
    horizon: int,
) -> RejectedCandidate:
    digest = hashlib.sha256(artifact_bytes([at, instrument, evidence_hash, reason])).hexdigest()
    return RejectedCandidate(
        digest, at, instrument, evidence_hash, price, (), (reason,), horizon, "UNOBSERVABLE", None
    )


@dataclass(frozen=True)
class SimulationResult:
    label: Literal["SIMULATED"]
    simulator_version: str
    instrument: str
    config_hash: str
    seed: int
    initial_cash: Decimal
    cash: Decimal
    holdings: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    final_equity: Decimal
    fills: tuple[SimulatedFill, ...]
    trades: tuple[SimulatedTrade, ...]
    equity: tuple[EquityPoint, ...]
    rejections: tuple[RejectedCandidate, ...]
    decisions: tuple[tuple[datetime, str], ...]
    outage_exposure: tuple[OutageExposure, ...] = ()

    def bytes(self) -> bytes:
        return artifact_bytes(asdict(self))


def feature_window_available(
    history: Sequence[Candle], count: int, outages: tuple[VenueUnavailable, ...] = ()
) -> bool:
    if count < 1 or len(history) < count:
        return False
    window = history[-count:]
    return all(a.end_at == b.open_at for a, b in zip(window, window[1:], strict=False)) and not any(
        outage.overlaps(bar.open_at, bar.end_at) for outage in outages for bar in window
    )


def validate_prices(bars: Sequence[Candle], outages: tuple[VenueUnavailable, ...] = ()) -> None:
    if not bars or len(bars) > 100_000:
        raise ValueError("RESEARCH_ROW_BUDGET")
    for a, b in zip(bars, bars[1:], strict=False):
        gap_explained = a.end_at < b.open_at and any(
            o.instrument == a.instrument_id and o.start <= a.end_at < b.open_at <= o.end
            for o in outages
        )
        if (
            (a.end_at != b.open_at and not gap_explained)
            or a.instrument_id != b.instrument_id
            or a.interval != b.interval
        ):
            raise ValueError("GAPPED_OR_MIXED_RESEARCH_INPUT")


def simulate(
    bars: Sequence[Candle],
    config: StrategyConfig,
    policy: PriceAvailability,
    costs: CostModel,
    fitted: FittedFeatures,
    *,
    seed: int = 1229,
    initial_cash: Decimal = Decimal("10000"),
    evidence_hash: str = "0" * 64,
    signal: SignalRule = baseline_signal,
    liquidate_at_end: bool = True,
    deadline_seconds: int = 1800,
    outages: tuple[VenueUnavailable, ...] = (),
) -> SimulationResult:
    validate_prices(bars, outages)
    if any(o.instrument != bars[0].instrument_id for o in outages):
        raise ValueError("OUTAGE_INSTRUMENT_MISMATCH")
    initial_cash = exact_decimal(initial_cash)
    if initial_cash <= 0 or not 0 < deadline_seconds <= 1800 or not 0 <= seed < 2**32:
        raise ValueError("RESEARCH_CONFIGURATION")
    if fitted.train_end > bars[0].open_at:
        raise ValueError("FEATURE_FIT_OVERLAPS_EVALUATION")
    with localcontext() as context:
        context.prec = 50
        return _replay(
            bars,
            config,
            policy,
            costs,
            fitted,
            seed,
            initial_cash,
            evidence_hash,
            signal,
            liquidate_at_end,
            deadline_seconds,
            outages,
        )


def _replay(
    bars: Sequence[Candle],
    config: StrategyConfig,
    policy: PriceAvailability,
    costs: CostModel,
    fitted: FittedFeatures,
    seed: int,
    initial_cash: Decimal,
    evidence_hash: str,
    signal: SignalRule,
    liquidate: bool,
    deadline: int,
    outages: tuple[VenueUnavailable, ...],
) -> SimulationResult:
    cash, quantity, basis, realized = initial_cash, ZERO, ZERO, ZERO
    fills: list[SimulatedFill] = []
    trades: list[SimulatedTrade] = []
    equity: list[EquityPoint] = []
    rejections: list[RejectedCandidate] = []
    decisions: list[tuple[datetime, str]] = []
    exposures: list[OutageExposure] = []
    reconciled: set[int] = set()
    gap_stop_pending = False
    last_mark = bars[0].open
    history: deque[Candle] = deque(maxlen=169)
    pending: tuple[datetime, datetime] | None = None
    entry_at, entry_price, initial_risk = bars[0].open_at, ZERO, ZERO
    entry_regime = "UNKNOWN"
    step = bars[0].end_at - bars[0].open_at
    started = time.monotonic()
    fee_rate = costs.fee_bps * costs.multiplier / 10000
    spread_rate = costs.spread_bps * costs.multiplier / 20000
    slip_rate = costs.slippage_bps * costs.multiplier / 10000

    def fill(
        side: Literal["BUY", "SELL"],
        reference: Decimal,
        at: datetime,
        decision: datetime,
        reason: str,
    ) -> None:
        nonlocal cash, quantity, basis, realized, entry_at, entry_price, initial_risk, entry_regime
        if any(o.contains(at) for o in outages):
            raise ValueError("FILL_DURING_VENUE_UNAVAILABLE")
        buy = side == "BUY"
        price = money(
            reference * (1 + spread_rate + slip_rate if buy else 1 - spread_rate - slip_rate), buy
        )
        size = (
            money(cash * config.exposure_fraction / (price * (1 + fee_rate))) if buy else quantity
        )
        if buy:
            size = money(size * config.entry_fill_fraction)
        notional = money(size * price, buy)
        fee = money(notional * fee_rate, True)
        if size <= 0 or (buy and notional + fee > cash):
            return
        digest = hashlib.sha256(
            artifact_bytes(
                [
                    "BACKTEST",
                    bars[0].instrument_id,
                    decision,
                    at,
                    side,
                    size,
                    config.content_hash(),
                    evidence_hash,
                ]
            )
        ).hexdigest()
        fills.append(
            SimulatedFill(
                "SIMULATED",
                side,
                at,
                decision,
                size,
                reference,
                price,
                notional,
                fee,
                money(size * reference * spread_rate, True),
                money(size * reference * slip_rate, True),
                reason,
                digest,
            )
        )
        if buy:
            cash -= notional + fee
            quantity, basis, entry_at, entry_price = size, notional + fee, at, price
            stop_value = money(
                size * price * (1 - config.stop_fraction) * (1 - spread_rate - slip_rate)
            )
            initial_risk = basis - stop_value + money(stop_value * fee_rate, True)
            vol_regime = (
                "HIGH_VOL"
                if volatility(tuple(history)) > fitted.volatility_threshold
                else "LOW_VOL"
            )
            trend = (
                "UP"
                if history[-1].close > history[0].close
                else "DOWN"
                if history[-1].close < history[0].close
                else "FLAT"
            )
            entry_regime = vol_regime + "_" + trend
        else:
            cash += notional - fee
            pnl = notional - fee - basis
            realized += pnl
            trades.append(
                SimulatedTrade(
                    entry_at,
                    at,
                    quantity,
                    pnl,
                    initial_risk,
                    reason,
                    entry_regime,
                    ("UTC00-08", "UTC08-16", "UTC16-24")[entry_at.hour // 8],
                )
            )
            quantity, basis = ZERO, ZERO

    # At equal timestamps a completed bar is settled BEFORE the next open, then publications.
    events = sorted(
        [(b.open_at, 1, i) for i, b in enumerate(bars)]
        + [(b.end_at, 0, i) for i, b in enumerate(bars)]
        + [(policy.available_at(b), 2, i) for i, b in enumerate(bars)]
        + [
            (o.effective_at, -1, i)
            for i, o in enumerate(outages)
            if bars[0].open_at <= o.effective_at < bars[-1].end_at
        ]
    )
    for at, kind, i in events:
        if time.monotonic() - started > deadline:
            raise ValueError("RESEARCH_CHECKPOINT_DEADLINE")
        if kind == -1:
            outage = outages[i]
            pending = None
            history.clear()
            rejections.append(
                rejected_candidate(
                    at,
                    bars[0].instrument_id,
                    evidence_hash,
                    "DATA_UNAVAILABLE_FEATURES_UNOBSERVABLE",
                    None,
                    config.holding_bars,
                )
            )
            if quantity:
                exposures.append(OutageExposure(outage.start, outage.end, quantity, last_mark))
            value = money(quantity * last_mark)
            equity.append(EquityPoint(at, cash, quantity, value, cash + value, "STALE_UNAVAILABLE"))
            continue
        bar = bars[i]
        unavailable = any(o.contains(at) for o in outages)
        if kind == 1:
            if unavailable:
                continue
            resumed = [j for j, o in enumerate(outages) if o.end <= at and j not in reconciled]
            if resumed:
                if quantity and config.family != "PASSIVE":
                    stop = entry_price * (1 - config.stop_fraction)
                    if gap_stop_pending or bar.open <= stop:
                        fill("SELL", min(bar.open, stop), at, entry_at, "OUTAGE_ADVERSE_GAP_STOP")
                reconciled.update(resumed)
                gap_stop_pending = False
            last_mark = bar.open
            terminal = liquidate and i == len(bars) - 1
            if quantity and (
                terminal
                or (config.family != "PASSIVE" and at >= entry_at + config.holding_bars * step)
            ):
                fill(
                    "SELL",
                    bar.open,
                    at,
                    entry_at,
                    "TERMINAL_OPEN" if terminal else "HOLDING_HORIZON",
                )
            if pending is not None and not quantity and not terminal:
                decision, eligible = pending
                if at >= eligible and at > decision:
                    fill("BUY", bar.open, at, decision, "NEXT_ELIGIBLE_OPEN")
                    pending = None
        elif kind == 0:
            if unavailable or any(o.overlaps(bar.open_at, bar.end_at) for o in outages):
                if quantity and config.family != "PASSIVE":
                    gap_stop_pending = gap_stop_pending or (
                        bar.low <= entry_price * (1 - config.stop_fraction)
                    )
                value = money(quantity * last_mark)
                equity.append(
                    EquityPoint(at, cash, quantity, value, cash + value, "STALE_UNAVAILABLE")
                )
                continue
            if quantity and config.family != "PASSIVE":
                stop = entry_price * (1 - config.stop_fraction)
                target = entry_price * (1 + config.target_fraction)
                if bar.low <= stop:
                    fill("SELL", min(bar.open, stop), at, entry_at, "ADVERSE_STOP_FIRST")
                elif bar.high >= target:
                    fill("SELL", target, at, entry_at, "CONSERVATIVE_TARGET")
            value = money(quantity * bar.close)
            last_mark = bar.close
            equity.append(EquityPoint(at, cash, quantity, value, cash + value))
        else:
            policy.require(bar, at)
            if unavailable or any(o.overlaps(bar.open_at, bar.end_at) for o in outages):
                continue
            history.append(bar)
            needed = 1 if config.family in ("PASSIVE", "NO_TRADE") else max(config.lookback + 1, 25)
            if not feature_window_available(tuple(history), needed, outages):
                continue
            raw, reason = signal(tuple(history), config, fitted)
            if raw and not quantity and pending is None:
                decisions.append((at, reason or "LONG_PROPOSAL"))
                if reason:
                    candidate = rejected_candidate(
                        at, bar.instrument_id, evidence_hash, reason, bar.close, config.holding_bars
                    )
                    rejections.append(
                        replace(
                            candidate,
                            features=(
                                ("config_hash", config.content_hash()),
                                ("simulator_version", "spot-event.v1"),
                                ("volatility", str(volatility(tuple(history)))),
                                ("training_threshold", str(fitted.volatility_threshold)),
                            ),
                        )
                    )
                else:
                    pending = (at, at + timedelta(microseconds=costs.latency_microseconds))
    last_value = money(quantity * last_mark)
    unrealized = last_value - basis
    final = cash + last_value
    assert final == initial_cash + realized + unrealized
    assert cash >= 0 and quantity >= 0
    return SimulationResult(
        "SIMULATED",
        "spot-event.v1",
        bars[0].instrument_id,
        config.content_hash(),
        seed,
        initial_cash,
        cash,
        quantity,
        realized,
        unrealized,
        final,
        tuple(fills),
        tuple(trades),
        tuple(equity),
        tuple(rejections),
        tuple(decisions),
        tuple(exposures),
    )


def resolve_counterfactuals(
    result: SimulationResult,
    bars: Sequence[Candle],
    config: StrategyConfig,
    policy: PriceAvailability,
    costs: CostModel,
    fitted: FittedFeatures,
    outages: tuple[VenueUnavailable, ...] = (),
) -> tuple[RejectedCandidate, ...]:
    """Isolated simulated paths only; deliberately exposes no summed portfolio metric."""
    indexes = {policy.available_at(bar): i for i, bar in enumerate(bars)}
    resolved = []
    for candidate in result.rejections:
        if candidate.reason_order != ("VOLATILITY_FILTER",):
            resolved.append(candidate)
            continue
        i = indexes[candidate.decision_at]
        count = candidate.horizon_bars + 3
        if i + count > len(bars):
            resolved.append(candidate)
            continue

        def only_candidate(
            history: Sequence[Candle],
            config: StrategyConfig,
            fitted: FittedFeatures,
            decision_at: datetime = candidate.decision_at,
        ) -> tuple[bool, str | None]:
            return policy.available_at(history[-1]) == decision_at, None

        hypothetical = simulate(
            bars[max(0, i - max(config.lookback, 24)) : i + count],
            config,
            policy,
            costs,
            fitted,
            signal=only_candidate,
            outages=outages,
        )
        resolved.append(
            replace(
                candidate,
                outcome="SIMULATED",
                forward_net_return=hypothetical.final_equity / hypothetical.initial_cash - 1,
            )
        )
    return tuple(resolved)
