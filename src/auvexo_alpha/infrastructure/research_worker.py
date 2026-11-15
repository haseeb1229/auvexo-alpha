"""Single bounded research worker; no execution dependency or broker capability."""

import json
import time
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from auvexo_alpha.application.research_metrics import (
    block_uncertainty,
    metrics,
    permutation_sensitivity,
)
from auvexo_alpha.application.research_simulator import (
    FittedFeatures,
    SimulationResult,
    fit_features,
    resolve_counterfactuals,
    simulate,
)
from auvexo_alpha.application.research_study import screen, select_validation, walk_forward_folds
from auvexo_alpha.domain.market_data import Candle
from auvexo_alpha.domain.research import (
    CostModel,
    StrategyConfig,
    StudyManifest,
    TrialIdentity,
    bars_digest,
)
from auvexo_alpha.infrastructure.research_data import ResearchRead
from auvexo_alpha.infrastructure.research_ledger import (
    SELECTION_TRIAL,
    ResearchLedger,
    trial_artifact,
)

Purpose = Literal["FITTED_FEATURES", "RESULT", "SELECTION", "VERDICT", "INFORMATIONAL_WALK_FORWARD"]


class Reader(Protocol):
    def read(self, study_id: str, phase: str, start: datetime, end: datetime) -> ResearchRead: ...


def identity(
    study: StudyManifest,
    purpose: Purpose,
    config: StrategyConfig,
    costs: CostModel,
    reads: Sequence[ResearchRead],
    consumed: Sequence[Candle],
) -> TrialIdentity:
    """What this trial ran, for the ledger to verify before accepting it."""
    return TrialIdentity(
        study_hash=study.content_hash(),
        purpose=purpose,
        config=config,
        config_hash=config.content_hash(),
        cost_model=costs,
        availability=study.availability,
        reads=tuple(dict.fromkeys(read.digest for read in reads)),
        consumed_digest=bars_digest(consumed),
        consumed_rows=len(consumed),
        code_hash=study.code_hash,
        dependency_hash=study.dependency_hash,
    )


class ResearchWorker:
    def __init__(self, ledger: ResearchLedger, reader: Reader) -> None:
        self.ledger, self.reader = ledger, reader

    def development(self, study_id: str) -> tuple[FittedFeatures, tuple[str, ...], dict[str, bool]]:
        study = self.ledger.study(study_id)
        split = study.split
        started = time.monotonic()
        outages = tuple(
            {o.content_hash(): o for item in study.inputs for o in item.outages}.values()
        )
        train_read = self.reader.read(study_id, "TRAIN", split.train_start, split.train_end)
        train = train_read.bars
        fitted = fit_features(train, split.train_start, split.train_end, outages=outages)
        first = study.configs[0]
        self.ledger.record(
            study_id,
            "fitted.training",
            "TRAIN",
            first.content_hash(),
            trial_artifact(
                identity(study, "FITTED_FEATURES", first, study.costs, [train_read], train),
                fitted_features=asdict(fitted),
            ),
        )
        validation_read = self.reader.read(
            study_id, "VALIDATION", split.validation_start, split.validation_end
        )
        validation = validation_read.bars
        validation_base: dict[str, SimulationResult] = {}

        def evaluate(
            phase: str,
            trial: str,
            reads: Sequence[ResearchRead],
            bars: list[Candle],
            cfg: StrategyConfig,
            features: FittedFeatures,
            multiplier: Decimal,
            **extra: object,
        ) -> SimulationResult:
            if time.monotonic() - started > study.checkpoint_seconds:
                raise ValueError("WORKER_CHECKPOINT_REQUIRED")
            costs = study.costs.model_copy(update={"multiplier": multiplier})
            result = simulate(
                bars,
                cfg,
                study.availability,
                costs,
                features,
                seed=study.seed,
                evidence_hash=study.content_hash(),
                outages=outages,
            )
            purpose: Purpose = "INFORMATIONAL_WALK_FORWARD" if extra else "RESULT"
            self.ledger.record(
                study_id,
                trial,
                phase,
                cfg.content_hash(),
                trial_artifact(
                    identity(study, purpose, cfg, costs, reads, bars),
                    result=asdict(result),
                    metrics=metrics(result),
                    fitted_features=asdict(features),
                    **extra,
                ),
            )
            return result

        # Training evaluation is explicitly in-sample; fitting never includes validation.
        for index, cfg in enumerate(study.configs):
            # Fit on the first 25 complete training bars, evaluate only subsequent training.
            warm_end = train[25].open_at
            warm_fit = fit_features(train[:25], split.train_start, warm_end, outages=outages)
            evaluate("TRAIN", f"train.{index}", [train_read], train[25:], cfg, warm_fit, Decimal(1))
        # Folds come from the registered training span and never repeat validation.
        for fold in walk_forward_folds(split):
            fit_read = self.reader.read(study_id, "WALK_FORWARD", fold.fit_start, fold.fit_end)
            fold_fit = fit_features(fit_read.bars, fold.fit_start, fold.fit_end, outages=outages)
            fold_read = self.reader.read(
                study_id, "WALK_FORWARD", fold.evaluate_start, fold.evaluate_end
            )
            for index, cfg in enumerate(study.configs):
                evaluate(
                    "WALK_FORWARD",
                    f"fold.{fold.index}.{index}",
                    [fit_read, fold_read],
                    fold_read.bars,
                    cfg,
                    fold_fit,
                    Decimal(1),
                    fold=asdict(fold),
                    selection_role="INFORMATIONAL_ONLY_NOT_USED_FOR_SELECTION",
                )
        for index, cfg in enumerate(study.configs):
            for multiplier in study.stress_multipliers:
                result = evaluate(
                    "VALIDATION",
                    f"validation.{index}.{multiplier}",
                    [train_read, validation_read],
                    validation,
                    cfg,
                    fitted,
                    multiplier,
                )
                if multiplier == 1:
                    validation_base[cfg.content_hash()] = result
        selected = select_validation(study.configs, validation_base)
        stable = {
            family: all(
                validation_base[c.content_hash()].final_equity
                > validation_base[c.content_hash()].initial_cash
                for c in study.configs
                if c.family == family
            )
            for family in ("BREAKOUT", "MEAN_REVERSION")
        }
        # Recording the selection freezes it in the database before any OOS bar is read.
        self.ledger.record(
            study_id,
            SELECTION_TRIAL,
            "VALIDATION",
            first.content_hash(),
            trial_artifact(
                identity(
                    study,
                    "SELECTION",
                    first,
                    study.costs,
                    [train_read, validation_read],
                    validation,
                ),
                fitted=asdict(fitted),
                selected=selected,
                stable=stable,
            ),
        )
        return fitted, selected, stable

    def holdout(self, study_id: str) -> dict[str, object]:
        """Open the holdout once, or resume an interrupted run of the same frozen selection.

        Resumption never re-opens: every recomputed trial must equal any trial already
        recorded byte for byte, and only missing trials are appended.
        """
        study = self.ledger.study(study_id)
        state = self.ledger.holdout_state(study_id)
        if state == "COMPLETE":
            raise ValueError("HOLDOUT_ALREADY_CONSUMED_AND_COMPLETE")
        frozen = json.loads(self.ledger.read_trial(study_id, SELECTION_TRIAL))
        stored_fit = frozen["fitted"]
        fitted = FittedFeatures(
            datetime.fromisoformat(stored_fit["train_start"]),
            datetime.fromisoformat(stored_fit["train_end"]),
            Decimal(stored_fit["volatility_threshold"]),
        )
        selected = tuple(frozen["selected"])
        stable = frozen["stable"]
        if state == "SEALED":
            # The database re-reads the frozen selection itself and refuses any other set.
            self.ledger.open_holdout(study_id, selected)
        oos_read = self.reader.read(study_id, "OOS", study.split.oos_start, study.split.oos_end)
        rows = oos_read.bars
        outages = tuple(
            {o.content_hash(): o for item in study.inputs for o in item.outages}.values()
        )
        # The registered block length decides the verdict; 7/28 days are reported sensitivity.
        blocks = sorted({7, study.bootstrap_block_days, 28})
        reports: dict[str, object] = {}
        recorded: list[str] = []

        def record(trial: str, cfg: StrategyConfig, artifact: bytes) -> None:
            self.ledger.record(study_id, trial, "OOS", cfg.content_hash(), artifact, resume=True)
            recorded.append(trial)

        for cfg in study.configs:
            if cfg.content_hash() not in selected:
                continue
            results = []
            uncertainties = []
            for multiplier in study.stress_multipliers:
                costs = study.costs.model_copy(update={"multiplier": multiplier})
                result = simulate(
                    rows,
                    cfg,
                    study.availability,
                    costs,
                    fitted,
                    seed=study.seed,
                    evidence_hash=study.content_hash(),
                    outages=outages,
                )
                results.append(result)
                uncertainty = {
                    str(block): block_uncertainty(
                        result,
                        seed=study.seed,
                        draws=study.bootstrap_samples,
                        block_days=block,
                        comparisons=study.comparisons,
                    )
                    for block in blocks
                }
                uncertainties.append(uncertainty)
                book = resolve_counterfactuals(
                    result, rows, cfg, study.availability, costs, fitted, outages
                )
                record(
                    f"oos.{cfg.family}.{multiplier}",
                    cfg,
                    trial_artifact(
                        identity(study, "RESULT", cfg, costs, [oos_read], rows),
                        result=asdict(result),
                        fitted_features=asdict(fitted),
                        metrics=metrics(result),
                        uncertainty=uncertainty,
                        counterfactuals=book,
                        permutation_sensitivity=permutation_sensitivity(result, study.seed),
                    ),
                )
            # The manifest guarantees the first multiplier is the unstressed cost model.
            primary = results[0]
            verdict: dict[str, object] = {"verdict": "BASELINE_ONLY", "promotion_eligible": False}
            if cfg.family in ("BREAKOUT", "MEAN_REVERSION"):
                # Same stored bootstrap as the recorded primary trial; no unregistered defaults.
                verdict = screen(
                    primary,
                    uncertainties[0][str(study.bootstrap_block_days)],
                    tuple(results),
                    stable.get(cfg.family, False),
                    max_drawdown=study.max_drawdown,
                )
                record(
                    f"verdict.{cfg.family}",
                    cfg,
                    trial_artifact(
                        identity(study, "VERDICT", cfg, study.costs, [oos_read], rows),
                        family=cfg.family,
                        config_hash=cfg.content_hash(),
                        screen=verdict,
                        registered={
                            "seed": study.seed,
                            "bootstrap_samples": study.bootstrap_samples,
                            "bootstrap_block_days": study.bootstrap_block_days,
                            "comparisons": study.comparisons,
                            "max_drawdown": study.max_drawdown,
                            "stress_multipliers": study.stress_multipliers,
                        },
                        trials=tuple(
                            f"oos.{cfg.family}.{multiplier}"
                            for multiplier in study.stress_multipliers
                        ),
                    ),
                )
            reports[cfg.family] = {
                "config_hash": cfg.content_hash(),
                "metrics": metrics(primary),
                "screen": verdict,
            }
        self.ledger.complete_holdout(study_id, tuple(recorded))
        return reports
