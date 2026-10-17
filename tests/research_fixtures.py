"""Synthetic research-only fixtures, never provider/source qualification evidence."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from test_data_parser import bar

from auvexo_alpha.application.research_simulator import FittedFeatures
from auvexo_alpha.domain.market_data import Candle
from auvexo_alpha.domain.research import StrategyConfig
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
