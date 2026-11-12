"""Synthetic research-only fixtures, never provider/source qualification evidence."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from test_data_gates import observation_fixtures
from test_data_parser import bar

from auvexo_alpha.application.research_simulator import (
    EquityPoint,
    FittedFeatures,
    SimulatedTrade,
    SimulationResult,
)
from auvexo_alpha.domain.market_data import Candle
from auvexo_alpha.domain.research import (
    CostModel,
    PriceAvailability,
    ResearchSplit,
    StrategyConfig,
    StudyManifest,
    classify_manifest,
)
from auvexo_alpha.domain.research_gaps import ProviderEvidence, VenueUnavailable

START = datetime(2024, 1, 1, tzinfo=UTC)


def prices(count=96, start=START):
    result = []
    for i in range(count):
        candle = bar(START + timedelta(hours=i))
        delta = start - START
        if delta:
            shift = max(delta, timedelta(0))
            candle = Candle.model_validate(
                candle.model_dump()
                | {
                    "open_at": candle.open_at + delta,
                    "end_at": candle.end_at + delta,
                    "source": candle.source.model_dump()
                    | {
                        "raw_open": candle.source.raw_open + int(delta.total_seconds() * 1000),
                        "raw_close": candle.source.raw_close + int(delta.total_seconds() * 1000),
                        "received_at": candle.source.received_at + shift,
                    },
                    "availability": candle.availability.model_dump()
                    | {
                        "received_at": candle.availability.received_at + shift,
                        "processed_at": candle.availability.processed_at + shift,
                        "available_at": candle.availability.available_at + shift,
                        "historical_close_bound": candle.end_at + delta,
                    },
                }
            )
        result.append(
            Candle.model_validate(
                candle.model_dump()
                | {
                    "open": "100",
                    "high": "100",
                    "low": "100",
                    "close": "100",
                }
            )
        )
    return result


def reprice(candle, **values):
    return Candle.model_validate(candle.model_dump() | {k: str(v) for k, v in values.items()})


def wave_prices(count=240, start=START, drift=0):
    """Deterministic 40-hour sawtooth from 100, +2 per hour then collapsing, plus hourly drift."""
    bars = prices(count, start)
    for i, candle in enumerate(bars):
        price = 100 + 2 * (i % 40) + drift * i
        bars[i] = reprice(candle, open=price, close=price, high=price + 1, low=price - 1)
    return bars


def closes(*values, highs=None):
    """Hourly candles with literal closes; every high is the close unless given literally."""
    bars = prices(len(values))
    highs = highs or values
    return [
        reprice(candle, open=close, close=close, low=close, high=high)
        for candle, close, high in zip(bars, values, highs, strict=True)
    ]


def synthetic_result(
    equity, trades=(), regimes=("LOW_VOL_UP",), initial="10000", risk="200", final=None
):
    """One literal equity close per UTC day; trades are (exit day index, pnl) literals."""
    points = tuple(
        EquityPoint(
            START + timedelta(days=day, hours=23),
            Decimal(value),
            Decimal(0),
            Decimal(0),
            Decimal(value),
        )
        for day, value in enumerate(equity)
    )
    closed = tuple(
        SimulatedTrade(
            START + timedelta(days=day, hours=1),
            START + timedelta(days=day, hours=12),
            Decimal(1),
            Decimal(pnl),
            Decimal(risk),
            "SYNTHETIC",
            regimes[index % len(regimes)],
            "UTC00-08",
        )
        for index, (day, pnl) in enumerate(trades)
    )
    ending = Decimal(final if final is not None else equity[-1] if equity else initial)
    return SimulationResult(
        "SIMULATED",
        "spot-event.v1",
        "binance.spot.BTCUSDT",
        "0" * 64,
        1229,
        Decimal(initial),
        ending,
        Decimal(0),
        ending - Decimal(initial),
        Decimal(0),
        ending,
        (),
        closed,
        points,
        (),
        (),
    )


def unused_holdout_start():
    """A far-future hour beyond every synthetic development span, unlikely to be reused."""
    return datetime(4000, 1, 1, tzinfo=UTC) + timedelta(hours=uuid4().int % 40_000_000)


def synthetic_study(study_id=None, oos_start=None, configs=None, instrument="binance.spot.BTCUSDT"):
    """Registry control fixture only. Development ends 2025; each holdout is a private week."""
    now = datetime.now(UTC) - timedelta(seconds=1)
    _, _, manifests = observation_fixtures()
    source = next(m for m in manifests if m.coverage.instrument_id == instrument)
    m = source.model_copy(update={"created_at": now, "processed_at": now})
    coverage = m.coverage.model_copy(
        update={
            "requested_start": datetime(2024, 1, 1, tzinfo=UTC),
            "requested_end": datetime(2024, 1, 1, 1, tzinfo=UTC),
            "earliest": datetime(2024, 1, 1, tzinfo=UTC),
            "latest_end": datetime(2024, 1, 1, 1, tzinfo=UTC),
            "interval": "1h",
        }
    )
    m = m.model_copy(update={"coverage": coverage})
    policy = PriceAvailability(lag_microseconds=1_000_000)
    oos_start = oos_start or unused_holdout_start()
    configs = configs or tuple(config(f) for f in ("NO_TRADE", "PASSIVE", "FIXED_RULE", "BREAKOUT"))
    return StudyManifest(
        study_id=study_id or "synthetic." + uuid4().hex,
        version="fixture.v1",
        registered_at=now,
        instrument=instrument,
        hypotheses=("SYNTHETIC_A", "SYNTHETIC_B"),
        mechanism_and_falsification="Synthetic PostgreSQL control fixture; no empirical result.",
        inputs=(classify_manifest(m, now, policy),),
        availability=policy,
        configs=configs,
        costs=CostModel(),
        stress_multipliers=("1", "1.5", "2"),
        split=ResearchSplit(
            train_start=datetime(2022, 1, 1, tzinfo=UTC),
            train_end=datetime(2024, 1, 1, tzinfo=UTC),
            validation_start=datetime(2024, 1, 3, tzinfo=UTC),
            validation_end=datetime(2025, 1, 1, tzinfo=UTC),
            oos_start=oos_start,
            oos_end=oos_start + timedelta(hours=200),
            purge_embargo_seconds=172800,
        ),
        seed=1229,
        code_revision="synthetic-control-only",
        code_hash="0" * 64,
        dependency_hash="0" * 64,
        data_plan_v1_hash="0" * 64,
        data_plan_v2_hash="0" * 64,
        baseline_families=("NO_TRADE", "PASSIVE", "FIXED_RULE"),
        parameter_budget=len(configs),
        trial_budget=64,
        max_drawdown="0.2",
    )


def config(family="PASSIVE", **changes):
    return StrategyConfig.model_validate(
        dict(
            family=family,
            lookback=24,
            holding_bars=48,
            exposure_fraction="1",
            stop_fraction="0.02",
            target_fraction="0.04",
            deviation_fraction="0.015",
            entry_fill_fraction="1",
        )
        | changes
    )


def fitted(start=START):
    return FittedFeatures(start - timedelta(days=365), start, Decimal("0.01"))


def outage(
    start=START + timedelta(hours=36, minutes=27),
    end=START + timedelta(hours=39),
    source_hash="0" * 64,
    source_manifest="0" * 64,
):
    return VenueUnavailable(
        source_id="DS-02",
        instrument="binance.spot.BTCUSDT",
        start=start,
        end=end,
        effective_at=start,
        source_manifest=source_manifest,
        source_hash=source_hash,
        missing_start=start.replace(minute=0) + timedelta(hours=1),
        missing_end=end,
        truncated_openings=(start.replace(minute=0) + timedelta(hours=1),),
        rejected_rows=1,
        source_diagnosis_hash="0" * 64,
        evidence=(
            ProviderEvidence(
                url="https://www.binance.com/en/support/announcement/synthetic-fixture",
                sha256="0" * 64,
                retrieved_at=datetime(2026, 10, 18, tzinfo=UTC),
                representation="VERIFIED_FACT_EXTRACT",
                reviewer_ref="SYNTHETIC_TEST_ONLY",
            ),
        ),
    )
