"""Synthetic-only proofs of OI feature, forecast, scoring and statistical invariants."""

import hashlib
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from auvexo_alpha.application.oi_research import (
    OIBootstrapInterval,
    OIDailyEvidence,
    OIForecast,
    OIPairScore,
    OIStudyResult,
    OIStudyWindow,
    bootstrap_intervals,
    compute_oi_features,
    create_forecast,
    daily_evidence,
    decide_predictability,
    descriptive_metrics,
    evaluate_study,
    sample_is_sufficient,
    score_forecast,
)
from auvexo_alpha.domain.oi_rights_review import OIReviewAuthority, OIReviewContinuation
from auvexo_alpha.domain.open_interest import (
    OIManifest,
    OIObservation,
    accepted_oi_rights,
    oi_dataset_version,
)
from auvexo_alpha.domain.research import DataUseClass

HOUR = timedelta(hours=1)
START = datetime(2026, 10, 28, tzinfo=UTC)
CODE = "a" * 64


def digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def study(start=datetime(2026, 10, 25, 12, tzinfo=UTC)):
    return OIStudyWindow(
        study_id="fixture-only",
        owner_start_at=start,
        preregistration_hash="b" * 64,
        code_hash=CODE,
        rights_snapshot_hash=accepted_oi_rights().content_hash(),
    )


def manifest(
    slot, value="100", symbol="BTCUSDT", use=DataUseClass.ENGINEERING_ONLY, receipt_hash=None
):
    raw = ('{"openInterest":"' + value + '","symbol":"' + symbol + '","time":0}').encode()
    raw_hash = hashlib.sha256(raw).hexdigest()
    observation = OIObservation(
        symbol=symbol,
        slot_at=slot,
        raw_open_interest=value,
        value=Decimal(value),
        provider_time_ms=(slot - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(milliseconds=1),
        provider_at=slot,
        request_sent_at=slot,
        first_seen_at=slot + timedelta(milliseconds=100),
        received_at=slot + timedelta(milliseconds=200),
        processed_at=slot + timedelta(milliseconds=300),
        available_at=slot + timedelta(milliseconds=400),
        code_revision="fixture",
        review_receipt_hash=receipt_hash,
        code_hash=CODE,
        raw_hash=raw_hash,
    )
    normalized = observation.content_hash()
    return OIManifest(
        dataset_version=oi_dataset_version(observation),
        logical_key=f"ds04-a1:{symbol}:{observation.provider_time_ms}:oi-snapshot.v1",
        observation=observation,
        rights=accepted_oi_rights(),
        raw_relative_path=f"oi/raw/{raw_hash}.raw",
        normalized_relative_path=f"oi/normalized/{normalized}.json",
        raw_bytes=len(raw),
        normalized_bytes=len(observation.canonical_bytes()),
        normalized_hash=normalized,
        created_at=observation.available_at,
        processed_at=observation.available_at,
        classification=use,
    )


def prediction(value="110", previous="100", slot=START + HOUR):
    current, prior = manifest(slot, value), manifest(slot - HOUR, previous)
    feature = compute_oi_features(current, prior, at=slot + timedelta(seconds=1))
    forecast = create_forecast(study(), feature, created_at=slot + timedelta(seconds=2))
    return current, feature, forecast


def days(valid=90, count=19, btc="0.0002", eth="0.0003"):
    return tuple(
        OIDailyEvidence(
            day=(START + timedelta(days=i)).date(),
            btc_pairs=count if i < valid else 0,
            eth_pairs=count if i < valid else 0,
            btc_mean=Decimal(btc) if i < valid else None,
            eth_mean=Decimal(eth) if i < valid else None,
        )
        for i in range(90)
    )


def intervals(lower="0.0002", upper="0.0004"):
    return tuple(
        OIBootstrapInterval(
            block_days=b,
            btc_lower=Decimal(lower),
            btc_upper=Decimal(upper),
            eth_lower=Decimal(lower),
            eth_upper=Decimal(upper),
        )
        for b in (14, 7, 28)
    )


def fixture_ledger(window, *, day_count=2, pair_count=19):
    forecasts, scores = [], []
    hours = [*range(15), *range(20, 24)]
    for day in range(day_count):
        for symbol in ("BTCUSDT", "ETHUSDT"):
            for hour in hours[:pair_count]:
                slot = window.evaluation_start + timedelta(days=day, hours=hour)
                if slot + HOUR >= window.evaluation_end:
                    continue
                current_hash = digest((slot, symbol))
                forecast = OIForecast(
                    study_hash=window.content_hash(),
                    symbol=symbol,
                    slot_at=slot,
                    created_at=slot + timedelta(seconds=2),
                    feature_hash=digest((symbol, slot, "f")),
                    input_manifest_hashes=(digest((symbol, slot, "previous")), current_hash),
                    current_manifest_hash=current_hash,
                    current_level=Decimal("100"),
                    source_hash="d" * 64,
                    code_hash=CODE,
                    rights_snapshot_hash=accepted_oi_rights().content_hash(),
                    parser_version="oi-snapshot.v1",
                    augmented=Decimal("0.001"),
                    input_fractional_change=Decimal("0.001"),
                    classification=DataUseClass.ENGINEERING_ONLY,
                )
                score = OIPairScore(
                    study_hash=window.content_hash(),
                    forecast_hash=forecast.content_hash(),
                    symbol=symbol,
                    slot_at=slot,
                    target_manifest_hash=digest((symbol, slot, "target")),
                    outcome=Decimal("0.002"),
                    paired_loss_difference=Decimal("0.001"),
                    scored_at=slot + HOUR + timedelta(seconds=1),
                    eligible=True,
                    reason="SCORED",
                    classification=DataUseClass.ENGINEERING_ONLY,
                )
                forecasts.append(forecast)
                scores.append(score)
    return tuple(forecasts), tuple(scores)


def test_window_strict_next_midnight_warmup_and_fixed_end():
    window = study(datetime(2026, 10, 25, tzinfo=UTC))
    assert window.t0 == datetime(2026, 10, 26, tzinfo=UTC)
    assert window.evaluation_start == START
    assert window.evaluation_end == START + timedelta(days=90)
    for field, value in (("seed", 1230), ("warmup_hours", 24), ("evaluation_days", 91)):
        with pytest.raises(ValidationError):
            OIStudyWindow.model_validate({**window.model_dump(), field: value})


def test_exact_feature_formula_hashes_and_clip():
    current, feature, forecast = prediction()
    assert (
        feature.level == 110 and feature.delta == 10 and feature.fractional_change == Decimal("0.1")
    )
    assert feature.current_manifest_hash == current.content_hash()
    assert feature.available_at == current.observation.available_at
    assert forecast.baseline == 0 and forecast.augmented == Decimal("0.05")
    assert forecast.feature_hash == feature.content_hash()
    assert forecast.current_manifest_hash == current.content_hash()
    assert forecast.classification == DataUseClass.ENGINEERING_ONLY
    assert prediction("90")[2].augmented == Decimal("-0.05")
    assert prediction("105")[2].augmented == Decimal("0.05")
    assert prediction("95")[2].augmented == Decimal("-0.05")


@given(st.integers(min_value=1, max_value=100000), st.integers(min_value=0, max_value=100000))
def test_feature_decimal_and_clip_property(previous, current):
    slot = START + HOUR
    feature = compute_oi_features(
        manifest(slot, str(current)),
        manifest(slot - HOUR, str(previous)),
        at=slot + timedelta(seconds=1),
    )
    with localcontext() as context:
        context.prec = 50
        assert feature.delta == Decimal(current - previous)
        assert feature.fractional_change == Decimal(current - previous) / previous
    if current:
        forecast = create_forecast(study(), feature, created_at=slot + timedelta(seconds=2))
        assert Decimal("-0.05") <= forecast.augmented <= Decimal("0.05")


def test_gap_missing_zero_and_equal_value_are_distinct():
    slot = START + 3 * HOUR
    current = manifest(slot)
    missing = compute_oi_features(current, None, at=slot + timedelta(seconds=1))
    assert missing.level == 100 and missing.delta is None
    assert missing.reasons == ("INSUFFICIENT_HISTORY",)
    gap = compute_oi_features(current, manifest(slot - 2 * HOUR), at=slot + timedelta(seconds=1))
    assert gap.delta is None and gap.reasons == ("NONADJACENT_SLOT",)
    zero = compute_oi_features(current, manifest(slot - HOUR, "0"), at=slot + timedelta(seconds=1))
    assert zero.delta == 100 and zero.fractional_change is None
    assert zero.reasons == ("ZERO_DENOMINATOR",)
    equal = compute_oi_features(current, manifest(slot - HOUR), at=slot + timedelta(seconds=1))
    assert equal.fractional_change == 0
    for feature in (missing, gap, zero):
        with pytest.raises(ValueError, match="INPUT_UNAVAILABLE"):
            create_forecast(study(), feature, created_at=slot + timedelta(seconds=2))


def test_cross_symbol_out_of_order_spot_and_future_availability_refused():
    slot = START + HOUR
    with pytest.raises(ValueError, match="CROSS_SYMBOL"):
        compute_oi_features(manifest(slot), manifest(slot - HOUR, symbol="ETHUSDT"), at=slot + HOUR)
    with pytest.raises(ValueError):
        compute_oi_features(manifest(slot), manifest(slot + HOUR), at=slot + 2 * HOUR)
    with pytest.raises(ValueError, match="BLOCKED|AVAILABILITY"):
        compute_oi_features(manifest(slot), None, at=slot)
    with pytest.raises(ValueError, match="CROSS_PRODUCT"):
        compute_oi_features(object(), None, at=slot)


def test_invalid_rights_parser_unit_or_recycled_identity_refused():
    slot = START + HOUR
    current, prior = manifest(slot), manifest(slot - HOUR)
    for update in ({"unit": "CONTRACT"}, {"parser_version": "spot.v1"}, {"quality": "STALE"}):
        tampered = current.model_copy(
            update={"observation": current.observation.model_copy(update=update)}
        )
        with pytest.raises(ValueError, match="BLOCKED"):
            compute_oi_features(tampered, prior, at=slot + timedelta(seconds=1))
    with pytest.raises(ValueError, match="BLOCKED"):
        compute_oi_features(current, prior, at=datetime(2026, 11, 27, tzinfo=UTC))
    recycled = current.model_copy(
        update={
            "observation": current.observation.model_copy(
                update={
                    "provider_at": prior.observation.provider_at,
                    "provider_time_ms": prior.observation.provider_time_ms,
                }
            )
        }
    )
    with pytest.raises(ValueError, match="BLOCKED"):
        compute_oi_features(recycled, prior, at=slot + timedelta(seconds=1))


@pytest.mark.parametrize("offset", [-1, 60])
def test_forecast_cannot_backdate_or_create_late(offset):
    _, feature, _ = prediction()
    with pytest.raises(ValueError, match="INVARIANT|INPUT_UNAVAILABLE"):
        create_forecast(study(), feature, created_at=feature.slot_at + timedelta(seconds=offset))


def test_forecast_immutable_before_target_and_exact_outcome_scoring():
    current, _, forecast = prediction("102", "100")
    before = forecast.canonical_bytes()
    target = manifest(current.observation.slot_at + HOUR, "105.06")
    score = score_forecast(
        study(), forecast, current, target, scored_at=target.observation.available_at
    )
    assert score.outcome == Decimal("0.03")
    assert score.paired_loss_difference == Decimal("0.02")
    assert forecast.canonical_bytes() == before
    with pytest.raises(ValidationError):
        forecast.augmented = Decimal("0.03")
    missing = score_forecast(
        study(),
        forecast,
        current,
        None,
        scored_at=current.observation.slot_at + HOUR + timedelta(seconds=60),
    )
    assert not missing.eligible and missing.outcome is None and missing.reason == "MISSING_TARGET"
    assert forecast.canonical_bytes() == before
    with pytest.raises(ValueError, match="STILL_PENDING"):
        score_forecast(
            study(), forecast, current, None, scored_at=current.observation.slot_at + HOUR
        )


def test_invalid_target_does_not_change_forecast_or_allow_same_identity():
    current, _, forecast = prediction()
    before = forecast.content_hash()
    target = manifest(current.observation.slot_at + HOUR, "112", "ETHUSDT")
    with pytest.raises(ValueError, match="IDENTITY_OR_CAUSALITY"):
        score_forecast(
            study(), forecast, current, target, scored_at=target.observation.available_at
        )
    assert forecast.content_hash() == before
    with pytest.raises(ValueError, match="BINDING"):
        score_forecast(
            study(),
            forecast,
            manifest(current.observation.slot_at, "111"),
            None,
            scored_at=current.observation.slot_at + 2 * HOUR,
        )


def test_target_outside_end_retained_unscored_and_no_extension():
    window = study()
    slot = window.evaluation_end - HOUR
    current = manifest(slot)
    forecast = OIForecast(
        study_hash=window.content_hash(),
        symbol="BTCUSDT",
        slot_at=slot,
        created_at=slot + timedelta(seconds=1),
        feature_hash="f" * 64,
        input_manifest_hashes=("d" * 64, current.content_hash()),
        current_manifest_hash=current.content_hash(),
        current_level=Decimal("100"),
        source_hash=current.source.content_hash(),
        code_hash=CODE,
        rights_snapshot_hash=current.rights.content_hash(),
        parser_version="oi-snapshot.v1",
        augmented=Decimal("0.01"),
        input_fractional_change=Decimal("0.01"),
        classification=DataUseClass.ENGINEERING_ONLY,
    )
    score = score_forecast(window, forecast, current, None, scored_at=window.evaluation_end)
    assert not score.eligible and score.reason == "TARGET_OUTSIDE_FIXED_WINDOW"


def test_protected_adjacent_forecast_centers_and_no_pre_warmup():
    for hour in (15, 19):
        slot = START + hour * HOUR
        # 15 uses available 14/15; 19's prior18 is itself excluded.
        if hour == 15:
            current, previous = manifest(slot), manifest(slot - HOUR)
            feature = compute_oi_features(current, previous, at=slot + timedelta(seconds=1))
            with pytest.raises(ValueError, match="PROTECTED_ADJACENCY"):
                create_forecast(study(), feature, created_at=slot + timedelta(seconds=2))
        else:
            with pytest.raises(ValueError, match="PROTECTED_SLOT"):
                compute_oi_features(
                    manifest(slot), manifest(slot - HOUR), at=slot + timedelta(seconds=1)
                )
    _, feature, _ = prediction()
    early = feature.model_copy(update={"slot_at": START - HOUR})
    with pytest.raises(ValueError):
        create_forecast(study(), early, created_at=START)


def test_daily_calendar_labels_joint_validity_and_loss_binding():
    window = study()
    forecasts, scores = fixture_ledger(window)
    rows = daily_evidence(window, forecasts, scores)
    assert len(rows) == 90 and rows[0].joint_valid and rows[1].joint_valid
    assert rows[0].btc_pairs == 19 and rows[0].btc_mean == Decimal("0.001")
    assert rows[2].btc_mean is None and rows[2].eth_mean is None
    assert rows[-1].day == window.evaluation_end.date() - timedelta(days=1)
    one_side = tuple(s for s in scores if s.symbol == "BTCUSDT")
    assert not daily_evidence(window, forecasts, one_side)[0].joint_valid
    for bad_scores in (
        scores + scores[:1],
        (scores[0].model_copy(update={"paired_loss_difference": Decimal("0.002")}),),
    ):
        with pytest.raises(ValueError, match="BINDING|CORRUPTION"):
            daily_evidence(window, forecasts, bad_scores)
    with pytest.raises(ValueError, match="DUPLICATE_FORECAST"):
        daily_evidence(window, forecasts + forecasts[:1], scores)


@pytest.mark.parametrize(
    "valid,count,genuine,expected",
    [
        (80, 19, 30, True),
        (79, 19, 79, False),
        (80, 16, 80, False),
        (90, 19, 29, False),
        (90, 19, 90, True),
    ],
)
def test_sample_minima_independent(valid, count, genuine, expected):
    assert sample_is_sufficient(days(valid, count), genuine) is expected


@pytest.mark.parametrize("block", [7, 14, 28])
def test_bootstrap_fixed_deterministic_equal_day_weighting(block):
    evidence = days(80)
    result = bootstrap_intervals(evidence, block)
    assert result == bootstrap_intervals(evidence, block)
    assert result.draws == 5000 and result.seed == 1229
    assert result.btc_lower == result.btc_upper == Decimal("0.0002")
    assert result.eth_lower == result.eth_upper == Decimal("0.0003")


def test_bootstrap_matches_independent_non_circular_reference():
    evidence = tuple(
        OIDailyEvidence(
            day=(START + timedelta(days=i)).date(),
            btc_pairs=19 if i % 10 else 0,
            eth_pairs=19 if i % 10 else 0,
            btc_mean=Decimal(i) / 100000 if i % 10 else None,
            eth_mean=Decimal(90 - i) / 100000 if i % 10 else None,
        )
        for i in range(90)
    )
    actual = bootstrap_intervals(evidence, 14)
    rng, btc, eth = random.Random(1229), [], []
    with localcontext() as context:
        context.prec = 50
        for _ in range(5000):
            indices = []
            while len(indices) < 90:
                start = rng.randrange(77)
                indices.extend(range(start, start + 14))
            selected = [evidence[i] for i in indices[:90] if evidence[i].joint_valid]
            btc.append(sum((d.btc_mean for d in selected), Decimal(0)) / len(selected))
            eth.append(sum((d.eth_mean for d in selected), Decimal(0)) / len(selected))
    assert (actual.btc_lower, actual.btc_upper) == (sorted(btc)[124], sorted(btc)[4875])
    assert (actual.eth_lower, actual.eth_upper) == (sorted(eth)[124], sorted(eth)[4875])


def test_undefined_draws_not_discarded_and_calendar_not_compressed():
    result = bootstrap_intervals(days(0), 14)
    assert result.btc_lower is None and result.eth_upper is None
    with pytest.raises(ValueError, match="90_CALENDAR"):
        bootstrap_intervals(days()[:89], 14)
    with pytest.raises(ValueError, match="JOINT_DAY_NULL"):
        OIDailyEvidence(
            day=START.date(), btc_pairs=0, eth_pairs=0, btc_mean=Decimal(0), eth_mean=None
        )


@pytest.mark.parametrize(
    "bounds,sufficient,expected",
    [
        (intervals(), True, "PASS_RESEARCH_PREDICTABILITY"),
        (intervals(), False, "INCONCLUSIVE"),
        (intervals("0.0001"), True, "INCONCLUSIVE"),
        (intervals("-0.001", "0"), True, "NO_VALUE"),
        (intervals("-0.001", "0.001"), True, "INCONCLUSIVE"),
    ],
)
def test_decision_branches_use_two_symbols_strict_thresholds(bounds, sufficient, expected):
    assert decide_predictability(bounds, sufficient_sample=sufficient) == expected


def test_sensitivity_or_one_coprimary_failure_cannot_be_rescued():
    bound = list(intervals())
    bound[1] = bound[1].model_copy(update={"eth_lower": Decimal(0)})
    assert decide_predictability(tuple(bound), sufficient_sample=True) == "INCONCLUSIVE"
    bound[0] = bound[0].model_copy(update={"btc_upper": Decimal(0), "btc_lower": Decimal("-0.01")})
    assert decide_predictability(tuple(bound), sufficient_sample=True) == "NO_VALUE"
    bound[2] = bound[2].model_copy(update={"btc_lower": None, "btc_upper": None})
    assert decide_predictability(tuple(bound), sufficient_sample=True) == "INCONCLUSIVE"


def test_no_early_primary_result_no_real_clock_credit_and_material_stop():
    window = study()
    forecasts, scores = fixture_ledger(window)
    early = evaluate_study(
        window,
        forecasts,
        scores,
        as_of=START + timedelta(days=3),
        current_rights=accepted_oi_rights(),
    )
    assert early.decision == "INCONCLUSIVE" and not early.intervals
    assert early.reason == "STUDY_WINDOW_OPEN_NO_INTERIM_RESULT"
    assert early.genuine_forward_days == 0 and not early.empirical_result
    stopped = evaluate_study(
        window, forecasts, scores, as_of=START, current_rights=None, material_failure=True
    )
    assert stopped.decision == "STOPPED_REVIEW_REQUIRED"
    expired = evaluate_study(
        window, forecasts, scores, as_of=window.evaluation_end, current_rights=accepted_oi_rights()
    )
    assert expired.reason == "CURRENT_RIGHTS_REVIEW_REQUIRED"
    assert not expired.empirical_result and not expired.intervals


def test_full_fixture_ledger_never_earns_genuine_forward_days():
    # Window arithmetic is synthetic, with no activation; accepted rights are current at evaluation.
    window = study(datetime(2026, 7, 27, tzinfo=UTC))
    forecasts, scores = fixture_ledger(window, day_count=90)
    result = evaluate_study(
        window, forecasts, scores, as_of=window.evaluation_end, current_rights=accepted_oi_rights()
    )
    assert result.joint_valid_days == 90 and min(result.eligible_pairs) >= 1500
    assert result.genuine_forward_days == 0 and not result.empirical_result
    assert result.decision == "INCONCLUSIVE" and result.reason == "INSUFFICIENT_GENUINE_SAMPLE"


def test_oi16_predictability_pass_never_value_enablement_promotion_or_progression():
    result = OIStudyResult(
        study_hash="a" * 64,
        decided_at=START,
        decision="PASS_RESEARCH_PREDICTABILITY",
        reason="FIXTURE_BRANCH_ONLY",
        classification=DataUseClass.ENGINEERING_ONLY,
        joint_valid_days=0,
        eligible_pairs=(0, 0),
        genuine_forward_days=0,
    )
    assert result.value_gate == "VALUE_ABLATION_REQUIRED"
    for purpose in ("OPERATE_OI", "PROMOTE_STRATEGY", "ENABLE_MODULE", "MACRO", "NEWS", "AGENTS"):
        with pytest.raises(ValueError, match="OI16_VALUE_ABLATION_REQUIRED"):
            result.require_enablement(purpose)
    for field in (
        "operational_oi_enabled",
        "strategy_promotion_allowed",
        "phase6_module_enabled",
        "phase6_progression_allowed",
        "promotion_eligible",
    ):
        assert getattr(result, field) is False
        with pytest.raises(ValidationError):
            OIStudyResult.model_validate({**result.model_dump(), field: True})
    for update in (
        {"value_gate": "VALUE_PASS"},
        {"classification": DataUseClass.PROMOTION_ELIGIBLE},
        {"empirical_result": True},
        {"genuine_forward_days": 1},
    ):
        with pytest.raises(ValidationError):
            OIStudyResult.model_validate({**result.model_dump(), **update})


def test_tampered_forecast_level_and_baseline_cannot_change_outcome():
    current, _, forecast = prediction("102", "100")
    target = manifest(forecast.slot_at + HOUR, "105.06")
    bad_level = forecast.model_copy(update={"current_level": Decimal("100")})
    with pytest.raises(ValueError, match="PROVENANCE_BINDING"):
        score_forecast(
            study(), bad_level, current, target, scored_at=target.observation.available_at
        )
    with pytest.raises(ValidationError, match="FORECAST_INVARIANT"):
        OIForecast.model_validate({**forecast.model_dump(), "baseline": Decimal("0.01")})
    with pytest.raises(ValidationError):
        OIForecast.model_validate({**forecast.model_dump(), "parser_version": "spot.v1"})


def test_score_disposition_and_engineering_lineage_cannot_be_upgraded():
    forecasts, scores = fixture_ledger(study(), day_count=1)
    with pytest.raises(ValidationError, match="DISPOSITION_BINDING"):
        OIPairScore.model_validate({**scores[0].model_dump(), "reason": "MISSING_TARGET"})
    upgraded = scores[0].model_copy(update={"classification": DataUseClass.PERSONAL_RESEARCH})
    with pytest.raises(ValueError, match="LEDGER_SCORE_BINDING"):
        daily_evidence(study(), forecasts, (upgraded,))


def test_uncertainty_contract_rejects_nonfinite_reversed_or_partial_bounds():
    base = intervals()[0]
    for update in (
        {"btc_lower": Decimal("NaN")},
        {"btc_lower": Decimal("Infinity")},
        {"eth_lower": Decimal("0.1")},
        {"eth_upper": None},
    ):
        with pytest.raises(ValidationError):
            OIBootstrapInterval.model_validate({**base.model_dump(), **update})
    with pytest.raises(ValueError):
        decide_predictability(
            (base.model_copy(update={"btc_lower": Decimal("NaN")}), *intervals()[1:]),
            sufficient_sample=True,
        )


def test_descriptives_exact_forecast_errors_coverage_delay_and_no_metric_rescue():
    current, _, forecast = prediction("102", "100")
    target = manifest(forecast.slot_at + HOUR, "105.06")
    score = score_forecast(
        study(), forecast, current, target, scored_at=target.observation.available_at
    )
    missing_forecast = forecast.model_copy(
        update={
            "slot_at": forecast.slot_at + HOUR,
            "created_at": forecast.created_at + HOUR,
            "augmented": Decimal("0.05"),
            "input_fractional_change": Decimal("0.1"),
        }
    )
    rows = daily_evidence(study(), (forecast, missing_forecast), (score,))
    btc, eth = descriptive_metrics((forecast, missing_forecast), (score,), rows)
    assert btc.forecast_count == 2 and btc.scored_count == 1 and btc.missing_or_unscored_count == 1
    assert btc.eligible_forecast_coverage == Decimal("0.5") and btc.clipped_forecast_count == 1
    assert btc.baseline_mae == btc.baseline_rmse == Decimal("0.03")
    assert btc.augmented_mae == btc.augmented_rmse == Decimal("0.01")
    assert btc.baseline_bias == Decimal("-0.03") and btc.augmented_bias == Decimal("-0.01")
    assert btc.mean_forecast_creation_delay_seconds == 2 and btc.joint_day_weighted_effect is None
    assert btc.label == "DESCRIPTIVE_ONLY_NO_METRIC_RESCUE"
    assert eth.forecast_count == 0 and eth.eligible_forecast_coverage is None
    assert eth.baseline_mae is None and eth.augmented_rmse is None
    btc.canonical_bytes()


def test_forecast_clip_cannot_be_changed_without_matching_original_feature():
    _, feature, forecast = prediction("102", "100")
    with pytest.raises(ValidationError, match="FORECAST_INVARIANT"):
        OIForecast.model_validate({**forecast.model_dump(), "augmented": Decimal("0.03")})
    for field in ("code_hash", "rights_snapshot_hash"):
        changed = feature.model_copy(update={field: "e" * 64})
        with pytest.raises(ValueError, match="STUDY_PROVENANCE"):
            create_forecast(study(), changed, created_at=forecast.created_at)


def continuation_authority(at, *, first_accepted_at=None):
    """Synthetic accepted-review fixtures only, never runtime/owner acceptance."""
    base = accepted_oi_rights()
    first = OIReviewContinuation(
        base_rights_hash=base.content_hash(),
        previous_review_hash=base.content_hash(),
        source_hash=base.source.content_hash(),
        reviewed_at=datetime(2026, 11, 26, 12, tzinfo=UTC),
        accepted_at=first_accepted_at or datetime(2026, 11, 26, 13, tzinfo=UTC),
        next_review_due=datetime(2026, 12, 27, tzinfo=UTC),
        review_ref="SYNTHETIC_REVIEW_1",
        independent_acceptance_ref="SYNTHETIC_ACCEPTANCE_1",
    )
    chain = (first,)
    if at >= datetime(2026, 12, 26, 13, tzinfo=UTC):
        second = OIReviewContinuation(
            base_rights_hash=base.content_hash(),
            previous_review_hash=first.content_hash(),
            source_hash=base.source.content_hash(),
            reviewed_at=datetime(2026, 12, 26, 12, tzinfo=UTC),
            accepted_at=datetime(2026, 12, 26, 13, tzinfo=UTC),
            next_review_due=datetime(2027, 1, 27, tzinfo=UTC),
            review_ref="SYNTHETIC_REVIEW_2",
            independent_acceptance_ref="SYNTHETIC_ACCEPTANCE_2",
        )
        chain = (first, second)
    return OIReviewAuthority(base, chain, tuple(r.content_hash() for r in chain), at)


def test_same_evidence_review_boundary_preserves_study_and_causal_feature_protocol():
    slot = datetime(2026, 11, 27, tzinfo=UTC)
    authority = continuation_authority(slot + timedelta(hours=2))
    before = study().canonical_bytes()
    previous = manifest(slot - HOUR, "100")
    current = manifest(slot, "102", receipt_hash=authority.receipt_hash_at(slot))
    feature = compute_oi_features(
        current, previous, at=current.observation.available_at, review_authority=authority
    )
    assert feature.fractional_change == Decimal("0.02")
    assert feature.rights_snapshot_hash == accepted_oi_rights().content_hash()
    forecast = create_forecast(study(), feature, created_at=slot + timedelta(seconds=1))
    target = manifest(slot + HOUR, "105.06", receipt_hash=authority.receipt_hash_at(slot + HOUR))
    score = score_forecast(
        study(),
        forecast,
        current,
        target,
        scored_at=target.observation.available_at,
        review_authority=authority,
    )
    assert score.eligible and score.outcome == Decimal("0.03")
    assert score.paired_loss_difference == Decimal("0.02")
    assert study().canonical_bytes() == before and forecast.study_hash == study().content_hash()
    assert forecast.classification == score.classification == DataUseClass.ENGINEERING_ONLY
    assert current.observation.review_receipt_hash == authority.chain[0].content_hash()
    assert previous.observation.review_receipt_hash is None


def test_unknown_review_or_wrong_original_stamp_cannot_admit_features_after_base_due():
    slot = datetime(2026, 11, 27, tzinfo=UTC)
    authority = continuation_authority(slot + HOUR)
    previous = manifest(slot - HOUR)
    for stamp, context in ((None, None), (None, authority), ("f" * 64, authority)):
        current = manifest(slot, "102", receipt_hash=stamp)
        with pytest.raises(ValueError, match="BLOCKED"):
            compute_oi_features(
                current, previous, at=current.observation.available_at, review_authority=context
            )
    current = manifest(slot, "102", receipt_hash=authority.receipt_hash_at(slot))
    with pytest.raises(ValueError, match="BLOCKED"):
        compute_oi_features(current, previous, at=current.observation.available_at)
    with pytest.raises(ValueError):
        OIReviewAuthority(authority.base, authority.chain, (), slot + HOUR)


def test_late_review_gap_is_not_retroactively_filled_by_later_authority():
    gap_slot = datetime(2026, 11, 27, tzinfo=UTC)
    accepted_at = datetime(2026, 11, 28, tzinfo=UTC)
    authority = continuation_authority(accepted_at + HOUR, first_accepted_at=accepted_at)
    current = manifest(gap_slot, "102", receipt_hash=authority.chain[0].content_hash())
    with pytest.raises(ValueError, match="BLOCKED"):
        compute_oi_features(
            current, manifest(gap_slot - HOUR), at=accepted_at + HOUR, review_authority=authority
        )
    # The first valid post-gap fact has no valid adjacent input; no row-count bridge.
    resumed = manifest(accepted_at, "102", receipt_hash=authority.receipt_hash_at(accepted_at))
    feature = compute_oi_features(
        resumed, None, at=resumed.observation.available_at, review_authority=authority
    )
    assert feature.fractional_change is None and feature.reasons == ("INSUFFICIENT_HISTORY",)


def test_90day_fixture_interpretation_binds_accepted_review_chain_but_earns_zero_days():
    window = study()
    forecasts, scores = fixture_ledger(window, day_count=90)
    authority = continuation_authority(window.evaluation_end)
    result = evaluate_study(
        window,
        forecasts,
        scores,
        as_of=window.evaluation_end,
        current_rights=accepted_oi_rights(),
        review_authority=authority,
    )
    assert result.review_chain_hash == authority.chain_hash()
    assert result.joint_valid_days == 90 and min(result.eligible_pairs) >= 1500
    assert result.genuine_forward_days == 0 and not result.empirical_result
    assert result.decision == "INCONCLUSIVE" and result.reason == "INSUFFICIENT_GENUINE_SAMPLE"
    assert result.value_gate == "VALUE_ABLATION_REQUIRED" and not result.operational_oi_enabled
    without_context = evaluate_study(
        window, forecasts, scores, as_of=window.evaluation_end, current_rights=accepted_oi_rights()
    )
    assert without_context.reason == "CURRENT_RIGHTS_REVIEW_REQUIRED"
