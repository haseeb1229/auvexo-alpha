"""Causal OI-only foundation study. This module has no activation or value authority."""

import math
import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from typing import Literal, Self

from pydantic import Field, model_validator

from auvexo_alpha.domain.contracts import Contract, Digest, Label, UTCTime, utc_time
from auvexo_alpha.domain.oi_rights_review import OIReviewAuthority, require_oi_rights
from auvexo_alpha.domain.oi_schedule import slot_allowed
from auvexo_alpha.domain.open_interest import (
    OIManifest,
    OIObservation,
    OIRights,
    OISymbol,
    oi_classify_manifest,
)
from auvexo_alpha.domain.research import DataUseClass

OIResearchUse = Literal[DataUseClass.ENGINEERING_ONLY, DataUseClass.PERSONAL_RESEARCH]
OIVerdict = Literal[
    "PASS_RESEARCH_PREDICTABILITY", "NO_VALUE", "INCONCLUSIVE", "STOPPED_REVIEW_REQUIRED"
]
# Only SCORED is an eligible pair. Every other reason retains the original prediction
# beside an explicit missing-outcome flag and never contributes to any statistic.
OIScoreReason = Literal[
    "SCORED",
    "MISSING_TARGET",
    "TARGET_OUTSIDE_FIXED_WINDOW",
    "TARGET_RECEIPT_OR_AGE_INADMISSIBLE",
    "TARGET_NONPOSITIVE_VALUE",
]
_HOUR = timedelta(hours=1)
_MINUTE = timedelta(minutes=1)
_ZERO = Decimal(0)


class OIStudyWindow(Contract):
    """A pure future-window calculation, never an owner START credential or issuer."""

    study_id: Label
    owner_start_at: UTCTime
    preregistration_hash: Digest
    code_hash: Digest
    rights_snapshot_hash: Digest
    protocol: Literal["oi-fwd.v1"] = "oi-fwd.v1"
    seed: Literal[1229] = 1229
    warmup_hours: Literal[48] = 48
    evaluation_days: Literal[90] = 90

    @property
    def t0(self) -> datetime:
        return datetime.combine(
            self.owner_start_at.date() + timedelta(days=1), datetime.min.time(), UTC
        )

    @property
    def evaluation_start(self) -> datetime:
        return self.t0 + timedelta(hours=48)

    @property
    def evaluation_end(self) -> datetime:
        return self.evaluation_start + timedelta(days=90)


class OIFeatureSnapshot(Contract):
    symbol: OISymbol
    slot_at: UTCTime
    level: Decimal
    previous_level: Decimal | None
    delta: Decimal | None
    fractional_change: Decimal | None
    input_manifest_hashes: tuple[Digest, ...] = Field(min_length=1, max_length=2)
    current_manifest_hash: Digest
    source_hash: Digest
    code_hash: Digest
    rights_snapshot_hash: Digest
    parser_version: Literal["oi-snapshot.v1"] = "oi-snapshot.v1"
    unit: Literal["PROVIDER_NATIVE_OI_UNSPECIFIED"] = "PROVIDER_NATIVE_OI_UNSPECIFIED"
    available_at: UTCTime
    computed_at: UTCTime
    classification: OIResearchUse
    reasons: tuple[Label, ...] = ()
    feature_version: Literal["oi-feature.v1"] = "oi-feature.v1"

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.computed_at < self.available_at or self.slot_at.minute or self.slot_at.second:
            raise ValueError("OI_FEATURE_TIME")
        for value in (self.level, self.previous_level, self.delta, self.fractional_change):
            if value is not None and not value.is_finite():
                raise ValueError("OI_FEATURE_NONFINITE")
        if self.level < 0 or (self.previous_level is not None and self.previous_level < 0):
            raise ValueError("OI_FEATURE_NEGATIVE_LEVEL")
        if self.current_manifest_hash != self.input_manifest_hashes[-1]:
            raise ValueError("OI_FEATURE_MANIFEST_BINDING")
        with localcontext() as context:
            context.prec = 50
            if self.previous_level is not None:
                if self.delta != self.level - self.previous_level:
                    raise ValueError("OI_FEATURE_DELTA_BINDING")
                expected = self.delta / self.previous_level if self.previous_level > 0 else None
                if self.fractional_change != expected:
                    raise ValueError("OI_FEATURE_FRACTION_BINDING")
            elif self.delta is not None or self.fractional_change is not None:
                raise ValueError("OI_FEATURE_MISSING_PREVIOUS")
        return self


class OIForecast(Contract):
    study_hash: Digest
    symbol: OISymbol
    slot_at: UTCTime
    created_at: UTCTime
    feature_hash: Digest
    input_manifest_hashes: tuple[Digest, Digest]
    current_manifest_hash: Digest
    current_level: Decimal
    source_hash: Digest
    code_hash: Digest
    rights_snapshot_hash: Digest
    parser_version: Literal["oi-snapshot.v1"] = "oi-snapshot.v1"
    baseline: Decimal = Decimal(0)
    augmented: Decimal
    input_fractional_change: Decimal
    classification: OIResearchUse
    protocol: Literal["oi-fwd.v1"] = "oi-fwd.v1"

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if (
            self.baseline != 0
            or self.slot_at != self.slot_at.replace(minute=0, second=0, microsecond=0)
            or not self.slot_at <= self.created_at < self.slot_at + _MINUTE
            or not self.current_level.is_finite()
            or self.current_level <= 0
            or not self.input_fractional_change.is_finite()
            or self.augmented
            != max(Decimal("-0.05"), min(Decimal("0.05"), self.input_fractional_change))
            or not self.augmented.is_finite()
            or not Decimal("-0.05") <= self.augmented <= Decimal("0.05")
            or self.input_manifest_hashes[-1] != self.current_manifest_hash
        ):
            raise ValueError("OI_FORECAST_INVARIANT")
        return self

    @property
    def logical_key(self) -> str:
        return f"{self.study_hash}:{self.symbol}:{self.slot_at.isoformat()}"


class OIPairScore(Contract):
    study_hash: Digest
    forecast_hash: Digest
    symbol: OISymbol
    slot_at: UTCTime
    target_manifest_hash: Digest | None
    outcome: Decimal | None
    paired_loss_difference: Decimal | None
    scored_at: UTCTime
    eligible: bool
    reason: OIScoreReason
    classification: OIResearchUse

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.eligible != (self.reason == "SCORED"):
            raise ValueError("OI_SCORE_DISPOSITION_BINDING")
        if self.scored_at < self.slot_at + _HOUR:
            raise ValueError("OI_SCORE_BEFORE_TARGET_SLOT")
        values = (self.outcome, self.paired_loss_difference)
        if self.eligible:
            if self.target_manifest_hash is None or any(v is None for v in values):
                raise ValueError("OI_SCORE_MISSING_OUTCOME")
            if any(v is not None and not v.is_finite() for v in values):
                raise ValueError("OI_SCORE_NONFINITE")
        elif any(v is not None for v in values):
            raise ValueError("OI_UNSCORED_HAS_OUTCOME")
        return self


class OIDailyEvidence(Contract):
    day: date
    btc_pairs: int = Field(ge=0, le=19)
    eth_pairs: int = Field(ge=0, le=19)
    btc_mean: Decimal | None
    eth_mean: Decimal | None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        valid = self.btc_pairs >= 16 and self.eth_pairs >= 16
        if (valid and (self.btc_mean is None or self.eth_mean is None)) or (
            not valid and (self.btc_mean is not None or self.eth_mean is not None)
        ):
            raise ValueError("OI_JOINT_DAY_NULL_POLICY")
        if any(v is not None and not v.is_finite() for v in (self.btc_mean, self.eth_mean)):
            raise ValueError("OI_DAY_NONFINITE")
        return self

    @property
    def joint_valid(self) -> bool:
        return self.btc_mean is not None and self.eth_mean is not None


class OIBootstrapInterval(Contract):
    block_days: Literal[7, 14, 28]
    btc_lower: Decimal | None
    btc_upper: Decimal | None
    eth_lower: Decimal | None
    eth_upper: Decimal | None
    draws: Literal[5000] = 5000
    seed: Literal[1229] = 1229
    method: Literal["ALIGNED_NONCIRCULAR_MOVING_BLOCK_DAY_MEANS"] = (
        "ALIGNED_NONCIRCULAR_MOVING_BLOCK_DAY_MEANS"
    )

    @model_validator(mode="after")
    def coherent(self) -> Self:
        values = (self.btc_lower, self.btc_upper, self.eth_lower, self.eth_upper)
        if any(v is not None and not v.is_finite() for v in values):
            raise ValueError("OI_INTERVAL_NONFINITE")
        for lower, upper in ((self.btc_lower, self.btc_upper), (self.eth_lower, self.eth_upper)):
            if (lower is None) != (upper is None) or (
                lower is not None and upper is not None and lower > upper
            ):
                raise ValueError("OI_INTERVAL_ORDER_OR_MISSING")
        return self


class OIDescriptiveSymbol(Contract):
    """Pair-weighted diagnostics only; they never replace the day-weighted primary effect."""

    symbol: OISymbol
    forecast_count: int = Field(ge=0)
    scored_count: int = Field(ge=0)
    missing_or_unscored_count: int = Field(ge=0)
    clipped_forecast_count: int = Field(ge=0)
    eligible_forecast_coverage: Decimal | None
    baseline_mae: Decimal | None
    augmented_mae: Decimal | None
    baseline_rmse: Decimal | None
    augmented_rmse: Decimal | None
    baseline_bias: Decimal | None
    augmented_bias: Decimal | None
    mean_forecast_creation_delay_seconds: Decimal | None
    joint_day_weighted_effect: Decimal | None
    label: Literal["DESCRIPTIVE_ONLY_NO_METRIC_RESCUE"] = "DESCRIPTIVE_ONLY_NO_METRIC_RESCUE"


class OIStudyResult(Contract):
    study_hash: Digest
    decided_at: UTCTime
    decision: OIVerdict
    reason: Label
    classification: OIResearchUse
    joint_valid_days: int = Field(ge=0, le=90)
    eligible_pairs: tuple[int, int]
    genuine_forward_days: int = Field(ge=0, le=90)
    intervals: tuple[OIBootstrapInterval, ...] = ()
    descriptives: tuple[OIDescriptiveSymbol, ...] = ()
    review_chain_hash: Digest | None = None
    empirical_result: bool = False
    value_gate: Literal["VALUE_ABLATION_REQUIRED"] = "VALUE_ABLATION_REQUIRED"
    operational_oi_enabled: Literal[False] = False
    strategy_promotion_allowed: Literal[False] = False
    phase6_module_enabled: Literal[False] = False
    phase6_progression_allowed: Literal[False] = False
    promotion_eligible: Literal[False] = False

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.classification == DataUseClass.ENGINEERING_ONLY and (
            self.empirical_result or self.genuine_forward_days
        ):
            raise ValueError("OI_ENGINEERING_EVIDENCE_NOT_GENUINE")
        return self

    def require_enablement(self, purpose: str) -> None:
        raise ValueError("OI16_VALUE_ABLATION_REQUIRED:" + purpose)


def _received_in_slot(observation: OIObservation) -> bool:
    """Received and processed in the slot's first 60 seconds; provider age in [0, 120] s."""
    slot = observation.slot_at
    return (
        slot <= observation.received_at < slot + _MINUTE
        and slot <= observation.processed_at < slot + _MINUTE
        and timedelta(0)
        <= observation.received_at - observation.provider_at
        <= timedelta(seconds=120)
    )


def _require_admitted(
    manifest: OIManifest,
    at: datetime,
    review_authority: OIReviewAuthority | None = None,
    *,
    receipt_window: bool = True,
) -> None:
    if not isinstance(manifest, OIManifest):
        raise ValueError("OI_CROSS_PRODUCT_INPUT")
    observation = manifest.observation
    use: Literal["ENGINEERING", "PERSONAL_NONPRODUCTION", "PROMOTION"] = (
        "ENGINEERING"
        if manifest.classification == DataUseClass.ENGINEERING_ONLY
        else ("PERSONAL_NONPRODUCTION")
    )
    classification = oi_classify_manifest(
        manifest, at, intended_use=use, review_authority=review_authority
    )
    if classification == DataUseClass.BLOCKED or observation.quality != "VALID":
        raise ValueError("OI_RESEARCH_INPUT_BLOCKED")
    if observation.available_at > at:
        raise ValueError("OI_FUTURE_AVAILABILITY")
    slot = observation.slot_at
    if not slot_allowed(slot):
        raise ValueError("OI_PROTECTED_SLOT")
    if receipt_window and not _received_in_slot(observation):
        raise ValueError("OI_SLOT_RECEIPT_PROCESS_AGE")


def _use(manifests: tuple[OIManifest, ...]) -> OIResearchUse:
    if any(m.classification == DataUseClass.ENGINEERING_ONLY for m in manifests):
        return DataUseClass.ENGINEERING_ONLY
    return DataUseClass.PERSONAL_RESEARCH


def compute_oi_features(
    current: OIManifest,
    previous: OIManifest | None,
    *,
    at: datetime,
    review_authority: OIReviewAuthority | None = None,
) -> OIFeatureSnapshot:
    """Only observed adjacent inputs; no price contract or outcome can enter."""
    now = utc_time(at)
    _require_admitted(current, now, review_authority)
    observation = current.observation
    previous_level = delta = fraction = None
    inputs: tuple[OIManifest, ...] = (current,)
    reasons: tuple[str, ...] = ("INSUFFICIENT_HISTORY",)
    if previous is not None:
        _require_admitted(previous, now, review_authority)
        p = previous.observation
        if (
            p.symbol != observation.symbol
            or p.source != observation.source
            or p.unit != observation.unit
            or p.parser_version != observation.parser_version
            or p.rights_version != observation.rights_version
            or p.code_hash != observation.code_hash
            or previous.rights.content_hash() != current.rights.content_hash()
        ):
            raise ValueError("OI_CROSS_SYMBOL_SOURCE_UNIT_VERSION")
        if p.slot_at >= observation.slot_at or p.provider_at >= observation.provider_at:
            raise ValueError("OI_RECYCLED_OR_OUT_OF_ORDER")
        if p.slot_at != observation.slot_at - _HOUR:
            reasons = ("NONADJACENT_SLOT",)
        else:
            inputs = (previous, current)
            previous_level = p.value
            with localcontext() as context:
                context.prec = 50
                delta = observation.value - p.value
                fraction = delta / p.value if p.value > 0 else None
            reasons = () if fraction is not None else ("ZERO_DENOMINATOR",)
    return OIFeatureSnapshot(
        symbol=observation.symbol,
        slot_at=observation.slot_at,
        level=observation.value,
        previous_level=previous_level,
        delta=delta,
        fractional_change=fraction,
        input_manifest_hashes=tuple(m.content_hash() for m in inputs),
        current_manifest_hash=current.content_hash(),
        source_hash=observation.source.content_hash(),
        code_hash=observation.code_hash,
        rights_snapshot_hash=current.rights.content_hash(),
        parser_version=observation.parser_version,
        available_at=max(m.observation.available_at for m in inputs),
        computed_at=now,
        classification=_use(inputs),
        reasons=reasons,
    )


def create_forecast(
    study: OIStudyWindow, feature: OIFeatureSnapshot, *, created_at: datetime
) -> OIForecast:
    """Freezes a forecast from h-1/h only; accepts no h+1 parameter."""
    study = OIStudyWindow.model_validate(study.model_dump(mode="python"))
    feature = OIFeatureSnapshot.model_validate(feature.model_dump(mode="python"))
    now = utc_time(created_at)
    if (
        feature.code_hash != study.code_hash
        or feature.rights_snapshot_hash != study.rights_snapshot_hash
    ):
        raise ValueError("OI_FORECAST_STUDY_PROVENANCE")
    if not study.evaluation_start <= feature.slot_at < study.evaluation_end:
        raise ValueError("OI_FORECAST_OUTSIDE_FIXED_WINDOW")
    if not all(slot_allowed(feature.slot_at + offset * _HOUR) for offset in (-1, 0, 1)):
        raise ValueError("OI_FORECAST_PROTECTED_ADJACENCY")
    if (
        feature.fractional_change is None
        or feature.level <= 0
        or len(feature.input_manifest_hashes) != 2
        or not feature.available_at <= feature.computed_at <= now
    ):
        raise ValueError("OI_FORECAST_INPUT_UNAVAILABLE")
    return OIForecast(
        study_hash=study.content_hash(),
        symbol=feature.symbol,
        slot_at=feature.slot_at,
        created_at=now,
        feature_hash=feature.content_hash(),
        input_manifest_hashes=(feature.input_manifest_hashes[0], feature.input_manifest_hashes[1]),
        current_manifest_hash=feature.current_manifest_hash,
        current_level=feature.level,
        source_hash=feature.source_hash,
        code_hash=feature.code_hash,
        rights_snapshot_hash=feature.rights_snapshot_hash,
        parser_version=feature.parser_version,
        augmented=max(Decimal("-0.05"), min(Decimal("0.05"), feature.fractional_change)),
        input_fractional_change=feature.fractional_change,
        classification=feature.classification,
    )


def score_forecast(
    study: OIStudyWindow,
    forecast: OIForecast,
    current: OIManifest,
    target: OIManifest | None,
    *,
    scored_at: datetime,
    review_authority: OIReviewAuthority | None = None,
) -> OIPairScore:
    """Scores the original prediction; missing/invalid targets never erase it."""
    study = OIStudyWindow.model_validate(study.model_dump(mode="python"))
    forecast = OIForecast.model_validate(forecast.model_dump(mode="python"))
    now = utc_time(scored_at)
    if forecast.study_hash != study.content_hash() or current.content_hash() != (
        forecast.current_manifest_hash
    ):
        raise ValueError("OI_SCORE_FORECAST_BINDING")
    if (
        current.observation.symbol != forecast.symbol
        or current.observation.slot_at != forecast.slot_at
        or current.observation.value != forecast.current_level
        or current.observation.source.content_hash() != forecast.source_hash
        or current.observation.code_hash != forecast.code_hash
        or current.rights.content_hash() != forecast.rights_snapshot_hash
        or forecast.code_hash != study.code_hash
        or forecast.rights_snapshot_hash != study.rights_snapshot_hash
    ):
        raise ValueError("OI_SCORE_SOURCE_PROVENANCE_BINDING")
    target_slot = forecast.slot_at + _HOUR
    if now < target_slot:
        raise ValueError("OI_SCORE_BEFORE_TARGET")
    reason: OIScoreReason = "MISSING_TARGET"
    outcome = difference = None
    target_hash = target.content_hash() if target is not None else None
    if target_slot >= study.evaluation_end:
        reason = "TARGET_OUTSIDE_FIXED_WINDOW"
    elif target is None:
        if now < target_slot + _MINUTE:
            raise ValueError("OI_TARGET_STILL_PENDING")
    else:
        _require_admitted(current, current.observation.available_at, review_authority)
        # A wrong, blocked or out-of-order target still refuses. A genuine target that
        # itself failed admission (late receipt/processing, provider age, zero value) is
        # recorded below as an unscored outcome so the original prediction is retained.
        _require_admitted(
            target, target.observation.available_at, review_authority, receipt_window=False
        )
        c, t = current.observation, target.observation
        if (
            c.symbol != forecast.symbol
            or c.slot_at != forecast.slot_at
            or c.value != forecast.current_level
            or c.source.content_hash() != forecast.source_hash
            or t.symbol != forecast.symbol
            or t.slot_at != target_slot
            or t.source.content_hash() != forecast.source_hash
            or t.parser_version != forecast.parser_version
            or t.unit != c.unit
            or t.code_hash != forecast.code_hash
            or target.rights.content_hash() != forecast.rights_snapshot_hash
            or t.provider_at <= c.provider_at
            or target.observation.available_at > now
        ):
            raise ValueError("OI_TARGET_IDENTITY_OR_CAUSALITY")
        if not _received_in_slot(t):
            reason = "TARGET_RECEIPT_OR_AGE_INADMISSIBLE"
        elif t.value <= 0:
            reason = "TARGET_NONPOSITIVE_VALUE"
        else:
            with localcontext() as context:
                context.prec = 50
                outcome = (t.value - forecast.current_level) / forecast.current_level
                difference = abs(outcome - forecast.baseline) - abs(outcome - forecast.augmented)
            reason = "SCORED"
    classification = forecast.classification
    if target is not None and target.classification == DataUseClass.ENGINEERING_ONLY:
        classification = DataUseClass.ENGINEERING_ONLY
    return OIPairScore(
        study_hash=forecast.study_hash,
        forecast_hash=forecast.content_hash(),
        symbol=forecast.symbol,
        slot_at=forecast.slot_at,
        target_manifest_hash=target_hash,
        outcome=outcome,
        paired_loss_difference=difference,
        scored_at=now,
        eligible=reason == "SCORED",
        reason=reason,
        classification=classification,
    )


def daily_evidence(
    study: OIStudyWindow, forecasts: tuple[OIForecast, ...], scores: tuple[OIPairScore, ...]
) -> tuple[OIDailyEvidence, ...]:
    """Retain all 90 calendar labels; joint-invalid days have two null means."""
    forecasts = tuple(OIForecast.model_validate(f.model_dump(mode="python")) for f in forecasts)
    scores = tuple(OIPairScore.model_validate(s.model_dump(mode="python")) for s in scores)
    indexed = {forecast.content_hash(): forecast for forecast in forecasts}
    if len(indexed) != len(forecasts) or len({f.logical_key for f in forecasts}) != len(forecasts):
        raise ValueError("OI_DUPLICATE_FORECAST")
    by_day: dict[tuple[date, str], list[Decimal]] = {}
    seen: set[str] = set()
    for score in scores:
        forecast = indexed.get(score.forecast_hash)
        if (
            forecast is None
            or score.forecast_hash in seen
            or score.study_hash != study.content_hash()
            or forecast.study_hash != study.content_hash()
            or (
                forecast.classification == DataUseClass.ENGINEERING_ONLY
                and score.classification != DataUseClass.ENGINEERING_ONLY
            )
            or (score.symbol, score.slot_at) != (forecast.symbol, forecast.slot_at)
        ):
            raise ValueError("OI_LEDGER_SCORE_BINDING")
        seen.add(score.forecast_hash)
        if score.eligible:
            if not (
                study.evaluation_start <= score.slot_at
                and score.slot_at + _HOUR < study.evaluation_end
                and all(slot_allowed(score.slot_at + i * _HOUR) for i in (-1, 0, 1))
            ):
                raise ValueError("OI_LEDGER_WINDOW_OR_SCHEDULE")
            assert score.outcome is not None and score.paired_loss_difference is not None
            with localcontext() as context:
                context.prec = 50
                expected = abs(score.outcome) - abs(score.outcome - forecast.augmented)
            if expected != score.paired_loss_difference:
                raise ValueError("OI_LEDGER_LOSS_CORRUPTION")
            by_day.setdefault((score.slot_at.date(), score.symbol), []).append(expected)
    result = []
    with localcontext() as context:
        context.prec = 50
        for offset in range(90):
            day = study.evaluation_start.date() + timedelta(days=offset)
            btc, eth = by_day.get((day, "BTCUSDT"), []), by_day.get((day, "ETHUSDT"), [])
            valid = len(btc) >= 16 and len(eth) >= 16
            result.append(
                OIDailyEvidence(
                    day=day,
                    btc_pairs=len(btc),
                    eth_pairs=len(eth),
                    btc_mean=sum(btc, _ZERO) / len(btc) if valid else None,
                    eth_mean=sum(eth, _ZERO) / len(eth) if valid else None,
                )
            )
    return tuple(result)


def bootstrap_intervals(
    days: tuple[OIDailyEvidence, ...], block_days: Literal[7, 14, 28]
) -> OIBootstrapInterval:
    """Fixed 5000 aligned, noncircular draws; undefined draws are never discarded."""
    if len(days) != 90 or any(
        b.day != a.day + timedelta(days=1) for a, b in zip(days, days[1:], strict=False)
    ):
        raise ValueError("OI_BOOTSTRAP_REQUIRES_90_CALENDAR_LABELS")
    if block_days not in (7, 14, 28):
        raise ValueError("OI_BOOTSTRAP_BLOCK_NOT_PREREGISTERED")
    estimates: tuple[list[Decimal], list[Decimal]] = ([], [])
    rng = random.Random(1229)
    undefined = False
    with localcontext() as context:
        context.prec = 50
        prefixes = [[_ZERO], [_ZERO]]
        counts = [0]
        for day in days:
            prefixes[0].append(prefixes[0][-1] + (day.btc_mean or _ZERO))
            prefixes[1].append(prefixes[1][-1] + (day.eth_mean or _ZERO))
            counts.append(counts[-1] + int(day.joint_valid))
        for _ in range(5000):
            sums, count, sampled = [_ZERO, _ZERO], 0, 0
            while sampled < 90:
                start = rng.randrange(91 - block_days)
                take = min(block_days, 90 - sampled)
                for symbol in (0, 1):
                    sums[symbol] += prefixes[symbol][start + take] - prefixes[symbol][start]
                count += counts[start + take] - counts[start]
                sampled += take
            if not count:
                undefined = True
            else:
                for symbol in (0, 1):
                    estimates[symbol].append(sums[symbol] / count)
    lower, upper = math.floor(0.025 * 4999), math.ceil(0.975 * 4999)
    for values in estimates:
        values.sort()
    return OIBootstrapInterval(
        block_days=block_days,
        btc_lower=None if undefined else estimates[0][lower],
        btc_upper=None if undefined else estimates[0][upper],
        eth_lower=None if undefined else estimates[1][lower],
        eth_upper=None if undefined else estimates[1][upper],
    )


def decide_predictability(
    intervals: tuple[OIBootstrapInterval, ...], *, sufficient_sample: bool
) -> OIVerdict:
    """Statistical branch only, no evidence/permission issuer; useful for fixture proofs."""
    intervals = tuple(
        OIBootstrapInterval.model_validate(i.model_dump(mode="python")) for i in intervals
    )
    if (
        not sufficient_sample
        or len(intervals) != 3
        or {i.block_days for i in intervals} != {7, 14, 28}
    ):
        return "INCONCLUSIVE"
    if any(None in (i.btc_lower, i.btc_upper, i.eth_lower, i.eth_upper) for i in intervals):
        return "INCONCLUSIVE"
    primary = next(i for i in intervals if i.block_days == 14)
    if all(
        value is not None and value > (Decimal("0.0001") if i.block_days == 14 else _ZERO)
        for i in intervals
        for value in (i.btc_lower, i.eth_lower)
    ):
        return "PASS_RESEARCH_PREDICTABILITY"
    if any(value is not None and value <= 0 for value in (primary.btc_upper, primary.eth_upper)):
        return "NO_VALUE"
    return "INCONCLUSIVE"


def descriptive_metrics(
    forecasts: tuple[OIForecast, ...],
    scores: tuple[OIPairScore, ...],
    days: tuple[OIDailyEvidence, ...],
) -> tuple[OIDescriptiveSymbol, ...]:
    """No price/cost/PnL claim. Source/HTTP lag remains in immutable input manifests."""
    indexed = {f.content_hash(): f for f in forecasts}
    result = []
    with localcontext() as context:
        context.prec = 50
        for symbol in ("BTCUSDT", "ETHUSDT"):
            symbol_forecasts = [f for f in forecasts if f.symbol == symbol]
            symbol_scores = [s for s in scores if s.symbol == symbol and s.eligible]
            baseline_errors, augmented_errors = [], []
            for score in symbol_scores:
                forecast = indexed[score.forecast_hash]
                assert score.outcome is not None
                baseline_errors.append(forecast.baseline - score.outcome)
                augmented_errors.append(forecast.augmented - score.outcome)
            count, total = len(symbol_scores), len(symbol_forecasts)
            daily = [d.btc_mean if symbol == "BTCUSDT" else d.eth_mean for d in days]
            means = [value for value in daily if value is not None]
            delays = [
                Decimal(str((f.created_at - f.slot_at).total_seconds())) for f in symbol_forecasts
            ]
            result.append(
                OIDescriptiveSymbol(
                    symbol=symbol,
                    forecast_count=total,
                    scored_count=count,
                    missing_or_unscored_count=total - count,
                    clipped_forecast_count=sum(
                        abs(f.input_fractional_change) > Decimal("0.05") for f in symbol_forecasts
                    ),
                    eligible_forecast_coverage=Decimal(count) / total if total else None,
                    baseline_mae=sum(map(abs, baseline_errors), _ZERO) / count if count else None,
                    augmented_mae=sum(map(abs, augmented_errors), _ZERO) / count if count else None,
                    baseline_rmse=(sum((e * e for e in baseline_errors), _ZERO) / count).sqrt()
                    if count
                    else None,
                    augmented_rmse=(sum((e * e for e in augmented_errors), _ZERO) / count).sqrt()
                    if count
                    else None,
                    baseline_bias=sum(baseline_errors, _ZERO) / count if count else None,
                    augmented_bias=sum(augmented_errors, _ZERO) / count if count else None,
                    mean_forecast_creation_delay_seconds=sum(delays, _ZERO) / total
                    if total
                    else None,
                    joint_day_weighted_effect=sum(means, _ZERO) / len(means) if means else None,
                )
            )
    return tuple(result)


def sample_is_sufficient(days: tuple[OIDailyEvidence, ...], genuine_days: int) -> bool:
    """All independent calendar and joint-day sample minima remain necessary."""
    return (
        len(days) == 90
        and sum(d.joint_valid for d in days) >= 80
        and sum(d.btc_pairs for d in days if d.joint_valid) >= 1500
        and sum(d.eth_pairs for d in days if d.joint_valid) >= 1500
        and 30 <= genuine_days <= 90
    )


def evaluate_study(
    study: OIStudyWindow,
    forecasts: tuple[OIForecast, ...],
    scores: tuple[OIPairScore, ...],
    *,
    as_of: datetime,
    current_rights: OIRights | None,
    review_authority: OIReviewAuthority | None = None,
    material_failure: bool = False,
) -> OIStudyResult:
    """No interim result inspection or window extension, and no fixture calendar credit.

    ``as_of`` is caller supplied, so it alone never closes the window: the ledger's own
    records must also reach the final scheduled slot. Classification labels likewise
    remain caller supplied here; genuineness needs store-verified manifests upstream.
    """
    now = utc_time(as_of)
    study_hash = study.content_hash()
    evidenced_through = max(
        (
            *(s.scored_at for s in scores if s.study_hash == study_hash),
            *(f.created_at for f in forecasts if f.study_hash == study_hash),
        ),
        default=None,
    )
    window_evidenced = (
        evidenced_through is not None and evidenced_through >= study.evaluation_end - _HOUR
    )
    use: OIResearchUse = DataUseClass.PERSONAL_RESEARCH
    if (
        not scores
        or any(f.classification == DataUseClass.ENGINEERING_ONLY for f in forecasts)
        or any(s.classification == DataUseClass.ENGINEERING_ONLY for s in scores)
    ):
        use = DataUseClass.ENGINEERING_ONLY
    rights_current = False
    if current_rights is not None:
        try:
            require_oi_rights(
                OIRights.model_validate(current_rights.model_dump(mode="python")),
                now,
                review_authority,
            )
            rights_current = True
        except ValueError:
            rights_current = False
    reason = "FIXED_WINDOW_COMPLETE"
    verdict: OIVerdict = "INCONCLUSIVE"
    intervals: tuple[OIBootstrapInterval, ...] = ()
    descriptives: tuple[OIDescriptiveSymbol, ...] = ()
    valid_days = btc = eth = genuine = 0
    if material_failure:
        verdict, reason = "STOPPED_REVIEW_REQUIRED", "MATERIAL_FAILURE"
    elif now < study.evaluation_end or not window_evidenced:
        # Includes a future or otherwise unsupported as_of over a ledger that stops early.
        reason = "STUDY_WINDOW_OPEN_NO_INTERIM_RESULT"
    elif not rights_current:
        reason = "CURRENT_RIGHTS_REVIEW_REQUIRED"
    elif any(s.scored_at > now for s in scores):
        reason = "FUTURE_SCORE_BLOCKED"
    else:
        days = daily_evidence(study, forecasts, scores)
        descriptives = descriptive_metrics(forecasts, scores, days)
        valid_days = sum(d.joint_valid for d in days)
        btc = sum(d.btc_pairs for d in days if d.joint_valid)
        eth = sum(d.eth_pairs for d in days if d.joint_valid)
        genuine = valid_days if use == DataUseClass.PERSONAL_RESEARCH else 0
        sufficient = sample_is_sufficient(days, genuine)
        if sufficient:
            intervals = tuple(bootstrap_intervals(days, block) for block in (14, 7, 28))
            verdict = decide_predictability(intervals, sufficient_sample=True)
        else:
            reason = "INSUFFICIENT_GENUINE_SAMPLE"
    return OIStudyResult(
        study_hash=study_hash,
        decided_at=now,
        decision=verdict,
        reason=reason,
        classification=use,
        joint_valid_days=valid_days,
        eligible_pairs=(btc, eth),
        genuine_forward_days=genuine,
        intervals=intervals,
        descriptives=descriptives,
        review_chain_hash=review_authority.chain_hash() if review_authority is not None else None,
        empirical_result=use == DataUseClass.PERSONAL_RESEARCH
        and reason == "FIXED_WINDOW_COMPLETE",
    )
