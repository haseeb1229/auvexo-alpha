from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from test_data_gates import observation_fixtures
from test_data_parser import bar

from auvexo_alpha.domain.research import (
    CostModel,
    DataUseClass,
    PriceAvailability,
    ResearchInput,
    ResearchSplit,
    classify_manifest,
    inherited_use,
)

POLICY = PriceAvailability(lag_microseconds=1_000_000)
NOW = datetime(2026, 10, 25, tzinfo=UTC)


@pytest.mark.parametrize("lag", [0, -1, True, 1.0])
def test_price_policy_rejects_nonpositive_or_coerced_lag(lag):
    with pytest.raises(ValueError):
        PriceAvailability(lag_microseconds=lag)


def test_price_policy_preserves_observed_truth_and_blocks_early_or_vintage():
    candle = bar(datetime(2024, 12, 31, tzinfo=UTC))
    original = candle.canonical_bytes()
    available = POLICY.available_at(candle)
    for early in (candle.end_at, available - timedelta(microseconds=1)):
        with pytest.raises(ValueError, match="LOOKAHEAD"):
            POLICY.require(candle, early)
    POLICY.require(candle, available)
    with pytest.raises(ValueError, match="LOOKAHEAD"):
        candle.require_as_of(available)
    with pytest.raises(ValueError, match="VINTAGE"):
        POLICY.available_at({"kind": "NEWS", "published_at": candle.end_at})
    with pytest.raises(ValueError):
        PriceAvailability(lag_microseconds=1, data_kind="MACRO_VINTAGE")
    assert candle.canonical_bytes() == original


def test_personal_source_rights_and_no_profit_based_promotion():
    _, _, manifests = observation_fixtures()
    m = manifests[0]
    assert classify_manifest(m, NOW, POLICY).classification == DataUseClass.PERSONAL_RESEARCH
    engineering = classify_manifest(m, NOW, POLICY, "ENGINEERING")
    assert engineering.classification == DataUseClass.ENGINEERING_ONLY
    assert classify_manifest(m, NOW, POLICY, "PROMOTION").classification == DataUseClass.BLOCKED
    assert classify_manifest(m, NOW, POLICY, parents=(engineering,)).classification == (
        DataUseClass.ENGINEERING_ONLY
    )
    assert inherited_use((DataUseClass.PROMOTION_ELIGIBLE, DataUseClass.PERSONAL_RESEARCH)) == (
        DataUseClass.PERSONAL_RESEARCH
    )
    assert inherited_use(()) == DataUseClass.BLOCKED


@pytest.mark.parametrize("fault", ["unknown", "expired", "cross", "quality", "checksum", "future"])
def test_rights_source_and_quality_fail_closed(fault):
    _, _, manifests = observation_fixtures()
    m = manifests[0]
    if fault == "unknown":
        m = m.model_copy(update={"rights": m.rights.model_copy(update={"terms_hash": "f" * 64})})
    elif fault == "expired":
        m = m.model_copy(update={"rights": m.rights.model_copy(update={"review_due": NOW})})
    elif fault == "cross":
        assert classify_manifest(m, NOW, POLICY, instrument="exness.cfd.XAU").classification == (
            DataUseClass.BLOCKED
        )
        return
    elif fault == "quality":
        m = m.model_copy(update={"coverage": m.coverage.model_copy(update={"status": "DEGRADED"})})
    elif fault == "checksum":
        m = m.model_copy(update={"source": m.source.model_copy(update={"source_id": "DS-01"})})
    else:
        m = m.model_copy(update={"processed_at": NOW + timedelta(seconds=1)})
    result = classify_manifest(m, NOW, POLICY)
    assert result.classification == DataUseClass.BLOCKED and result.reasons
    assert classify_manifest(manifests[1], NOW, POLICY, parents=(result,)).classification == (
        DataUseClass.BLOCKED
    )


def test_binding_hash_and_split_separation():
    _, _, manifests = observation_fixtures()
    result = classify_manifest(manifests[0], NOW, POLICY)
    with pytest.raises(ValueError, match="HASH"):
        ResearchInput.model_validate(result.model_dump() | {"manifest_hash": "0" * 64})
    with pytest.raises(ValueError, match="EMBARGO"):
        ResearchSplit(
            train_start=NOW - timedelta(days=10),
            train_end=NOW - timedelta(days=5),
            validation_start=NOW - timedelta(days=5),
            validation_end=NOW - timedelta(days=2),
            oos_start=NOW - timedelta(days=2),
            oos_end=NOW,
            purge_embargo_seconds=172800,
        )


@pytest.mark.parametrize("value", [0.1, Decimal("NaN"), Decimal("Infinity"), "-1"])
def test_costs_require_finite_exact_nonnegative_money(value):
    with pytest.raises(ValueError):
        CostModel(fee_bps=value)
