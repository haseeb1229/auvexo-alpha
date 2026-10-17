from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from research_fixtures import START, config, fitted, outage, prices
from test_data_gates import observation_fixtures
from test_data_parser import row

from auvexo_alpha.application.research_simulator import feature_window_available, simulate
from auvexo_alpha.domain.market_data import Candle, DataQualityFinding
from auvexo_alpha.domain.research import (
    CostModel,
    DataUseClass,
    PriceAvailability,
    classify_manifest,
)
from auvexo_alpha.domain.research_gaps import ProviderEvidence, coverage_disposition
from auvexo_alpha.infrastructure.spot_parser import parse_row

POLICY = PriceAvailability(lag_microseconds=1_000_000)
FREE = CostModel(fee_bps="0", spread_bps="0", slippage_bps="0")


def test_semantic_interval_code_and_legacy_replay_contract():
    with pytest.raises(ValueError, match="UNSUPPORTED_PARSER_VERSION"):
        parse_row(
            row(START),
            "BTCUSDT",
            "1h",
            "MILLISECOND",
            "DS-02",
            "x",
            "0" * 64,
            datetime(2026, 10, 18, tzinfo=UTC),
            "spot.v3",
        )
    start = datetime(2023, 3, 24, 12, tzinfo=UTC)
    raw = row(start)
    raw[6] = "1679661581646"
    for version, expected in (("spot.v1", "TIMESTAMP_UNIT"), ("spot.v2", "TRUNCATED_INTERVAL")):
        with pytest.raises(ValueError, match=expected):
            parse_row(
                raw,
                "BTCUSDT",
                "1h",
                "MILLISECOND",
                "DS-01",
                "https://fixture.invalid",
                "0" * 64,
                datetime(2026, 10, 18, tzinfo=UTC),
                version,
            )
    raw = row(start + timedelta(seconds=1))
    with pytest.raises(ValueError, match="TIMESTAMP_UNIT"):
        parse_row(
            raw,
            "BTCUSDT",
            "1h",
            "MILLISECOND",
            "DS-01",
            "https://fixture.invalid",
            "0" * 64,
            datetime(2026, 10, 18, tzinfo=UTC),
        )


def test_source_bound_outage_is_not_pass_or_a_candle_and_unknown_stays_blocked():
    _, _, manifests = observation_fixtures()
    m = manifests[0]
    proof = outage(source_hash=m.source_hash, source_manifest=m.dataset_version)
    findings = (
        DataQualityFinding(code="TRUNCATED_INTERVAL", count=1, detail="synthetic"),
        DataQualityFinding(
            code="GAP",
            count=2,
            detail="synthetic",
            first_at=proof.missing_start,
            last_at=proof.missing_end - timedelta(hours=1),
        ),
    )
    m = m.model_copy(
        update={
            "coverage": m.coverage.model_copy(
                update={
                    "interval": "1h",
                    "status": "DEGRADED",
                    "findings": findings,
                    "rejected_rows": 1,
                    "expected_rows": 744,
                    "observed_rows": 742,
                }
            )
        }
    )
    assert coverage_disposition(m) == "UNKNOWN_GAP_BLOCKED"
    assert coverage_disposition(m, (proof,)) == "PROVIDER_OUTAGE_CONFIRMED"
    now = datetime(2026, 10, 25, tzinfo=UTC)
    assert (
        classify_manifest(m, now, POLICY, outages=(proof,)).classification
        == DataUseClass.PERSONAL_RESEARCH
    )
    assert m.coverage.status == "DEGRADED"
    with pytest.raises(ValueError):
        m.coverage.require_complete()
    for wrong in (
        proof.model_copy(update={"source_hash": "f" * 64}),
        proof.model_copy(update={"instrument": "binance.spot.ETHUSDT"}),
    ):
        assert coverage_disposition(m, (wrong,)) == "UNKNOWN_GAP_BLOCKED"
    extra = DataQualityFinding(
        code="GAP", count=1, detail="unexplained", first_at=START, last_at=START
    )
    bad = m.model_copy(
        update={
            "coverage": m.coverage.model_copy(
                update={
                    "findings": (*findings, extra),
                    "observed_rows": 741,
                }
            )
        }
    )
    assert coverage_disposition(bad, (proof,)) == "UNKNOWN_GAP_BLOCKED"
    with pytest.raises(ValueError):
        ProviderEvidence(
            url="https://another-venue.invalid/outage",
            sha256="0" * 64,
            retrieved_at=now,
            representation="SOURCE_BYTES",
            reviewer_ref="synthetic",
        )


def test_no_outage_fill_position_carries_and_gap_stop_is_adverse():
    proof = outage()
    all_bars = prices()
    bars = [b for b in all_bars if not proof.missing_start <= b.open_at < proof.missing_end]

    # Entry is before the unplanned halt, with no anticipation of future availability.
    def signal(h, c, f):
        return len(h) == 25 and h[0].open_at == START, None

    resumed = next(i for i, b in enumerate(bars) if b.open_at == proof.end)
    bars[resumed] = Candle.model_validate(
        bars[resumed].model_dump()
        | {
            "open": "80",
            "low": "80",
            "high": "100",
            "close": "100",
        }
    )
    result = simulate(
        bars, config("FIXED_RULE"), POLICY, FREE, fitted(), signal=signal, outages=(proof,)
    )
    assert result.fills[0].at == START + timedelta(hours=26)
    assert result.fills[1].at == proof.end and result.fills[1].price == Decimal("80")
    assert result.fills[1].reason == "OUTAGE_ADVERSE_GAP_STOP"
    assert result.realized_pnl == Decimal("-2000")
    assert not any(proof.contains(fill.at) for fill in result.fills)
    assert result.outage_exposure[0].holdings == Decimal("100")
    assert any(p.mark_state == "STALE_UNAVAILABLE" and p.holdings == 100 for p in result.equity)
    with pytest.raises(ValueError, match="GAPPED"):
        simulate(bars, config(), POLICY, FREE, fitted())


def test_replay_ending_during_halt_keeps_only_stale_observable_mark():
    proof = outage()
    bars = [b for b in prices() if b.open_at < proof.missing_start]
    bars[-1] = Candle.model_validate(bars[-1].model_dump() | {"high": "200", "close": "200"})

    def signal(h, c, f):
        return len(h) == 25 and h[0].open_at == START, None

    result = simulate(
        bars,
        config("FIXED_RULE"),
        POLICY,
        FREE,
        fitted(),
        signal=signal,
        outages=(proof,),
        liquidate_at_end=False,
    )
    assert result.holdings == Decimal("100")
    assert result.final_equity == Decimal("10000")
    assert result.equity[-1].mark_state == "STALE_UNAVAILABLE"
    assert result.equity[-1].equity == result.final_equity


@pytest.mark.parametrize("lookback", [24, 72, 168])
def test_wall_clock_lookback_rewarms_without_forward_filling(lookback):
    proof = outage()
    bars = prices(lookback + 100)
    before = [b for b in bars if b.open_at < proof.missing_start]
    resumed = [b for b in bars if b.open_at >= proof.end]
    assert not feature_window_available((*before[-lookback:], resumed[0]), lookback + 1, (proof,))
    assert not feature_window_available(resumed[:lookback], lookback + 1, (proof,))
    assert feature_window_available(resumed[: lookback + 1], lookback + 1, (proof,))


def test_future_outage_does_not_change_earlier_decisions_or_fills():
    bars = prices()
    proof = outage()
    prefix = bars[:30]
    plain = simulate(prefix, config(), POLICY, FREE, fitted(), liquidate_at_end=False)
    known_later = simulate(
        prefix, config(), POLICY, FREE, fitted(), liquidate_at_end=False, outages=(proof,)
    )
    assert plain.bytes() == known_later.bytes()
