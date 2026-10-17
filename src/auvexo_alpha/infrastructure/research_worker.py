"""Single bounded research worker; no execution dependency or broker capability."""

import json
import time
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal

from auvexo_alpha.application.research_metrics import (
    block_uncertainty,
    metrics,
    permutation_sensitivity,
)
from auvexo_alpha.application.research_simulator import (
    FittedFeatures,
    SimulationResult,
    artifact_bytes,
    fit_features,
    resolve_counterfactuals,
    simulate,
)
from auvexo_alpha.application.research_study import screen, select_validation
from auvexo_alpha.domain.market_data import Candle
from auvexo_alpha.domain.research import StrategyConfig
from auvexo_alpha.infrastructure.research_data import ResearchDataReader
from auvexo_alpha.infrastructure.research_ledger import ResearchLedger


class ResearchWorker:
    def __init__(self, ledger: ResearchLedger, reader: ResearchDataReader) -> None:
        self.ledger, self.reader = ledger, reader

    def development(self, study_id: str) -> tuple[FittedFeatures, tuple[str, ...], dict[str, bool]]:
        study = self.ledger.study(study_id)
        split = study.split
        started = time.monotonic()
        outages = tuple(
            {o.content_hash(): o for item in study.inputs for o in item.outages}.values()
        )
        train = self.reader.read(study_id, "TRAIN", split.train_start, split.train_end)
        fitted = fit_features(train, split.train_start, split.train_end, outages=outages)
        self.ledger.record(
            study_id,
            "fitted.training",
            "TRAIN",
            study.configs[0].content_hash(),
            artifact_bytes(asdict(fitted)),
        )
        validation = self.reader.read(
            study_id, "VALIDATION", split.validation_start, split.validation_end
        )
        validation_base: dict[str, SimulationResult] = {}

        def evaluate(
            phase: str,
            trial: str,
            bars: list[Candle],
            cfg: StrategyConfig,
            features: FittedFeatures,
            multiplier: Decimal,
        ) -> SimulationResult:
            if time.monotonic() - started > study.checkpoint_seconds:
                raise ValueError("WORKER_CHECKPOINT_REQUIRED")
            result = simulate(
                bars,
                cfg,
                study.availability,
                study.costs.model_copy(update={"multiplier": multiplier}),
                features,
                seed=study.seed,
                evidence_hash=study.content_hash(),
                outages=outages,
            )
            self.ledger.record(
                study_id,
                trial,
                phase,
                cfg.content_hash(),
                artifact_bytes(
                    {
                        "result": asdict(result),
                        "metrics": metrics(result),
                        "fitted_features": asdict(features),
                    }
                ),
            )
            return result

        # Training evaluation is explicitly in-sample; fitting never includes validation.
        for index, cfg in enumerate(study.configs):
            # Fit on the first 25 complete training bars, evaluate only subsequent training.
            warm_end = train[25].open_at
            warm_fit = fit_features(train[:25], split.train_start, warm_end, outages=outages)
            evaluate("TRAIN", f"train.{index}", train[25:], cfg, warm_fit, Decimal(1))
        for fold, year in enumerate((2023, 2024)):
            fit_end = datetime(year, 1, 1, tzinfo=split.train_start.tzinfo)
            fit_rows = self.reader.read(study_id, "WALK_FORWARD", split.train_start, fit_end)
            fold_fit = fit_features(fit_rows, split.train_start, fit_end, outages=outages)
            begin = fit_end + timedelta(seconds=split.purge_embargo_seconds)
            end = datetime(year + 1, 1, 1, tzinfo=begin.tzinfo)
            fold_rows = self.reader.read(study_id, "WALK_FORWARD", begin, end)
            for index, cfg in enumerate(study.configs):
                evaluate(
                    "WALK_FORWARD", f"fold.{fold}.{index}", fold_rows, cfg, fold_fit, Decimal(1)
                )
        for index, cfg in enumerate(study.configs):
            for multiplier in study.stress_multipliers:
                result = evaluate(
                    "VALIDATION",
                    f"validation.{index}.{multiplier}",
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
        # Selection metadata is returned before consumption; no OOS prices are read here.
        self.ledger.record(
            study_id,
            "selection.pre_holdout",
            "VALIDATION",
            study.configs[0].content_hash(),
            artifact_bytes({"fitted": asdict(fitted), "selected": selected, "stable": stable}),
        )
        return fitted, selected, stable

    def holdout(
        self,
        study_id: str,
    ) -> dict[str, object]:
        study = self.ledger.study(study_id)
        frozen = json.loads(self.ledger.read_trial(study_id, "selection.pre_holdout"))
        stored_fit = frozen["fitted"]
        fitted = FittedFeatures(
            datetime.fromisoformat(stored_fit["train_start"]),
            datetime.fromisoformat(stored_fit["train_end"]),
            Decimal(stored_fit["volatility_threshold"]),
        )
        selected = tuple(frozen["selected"])
        stable = frozen["stable"]
        self.ledger.open_holdout(study_id, selected)
        rows = self.reader.read(study_id, "OOS", study.split.oos_start, study.split.oos_end)
        outages = tuple(
            {o.content_hash(): o for item in study.inputs for o in item.outages}.values()
        )
        reports: dict[str, object] = {}
        for cfg in study.configs:
            if cfg.content_hash() not in selected:
                continue
            results = []
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
                    for block in (7, 14, 28)
                }
                book = resolve_counterfactuals(
                    result, rows, cfg, study.availability, costs, fitted, outages
                )
                payload = {
                    "result": asdict(result),
                    "fitted_features": asdict(fitted),
                    "metrics": metrics(result),
                    "uncertainty": uncertainty,
                    "counterfactuals": book,
                    "permutation_sensitivity": permutation_sensitivity(result, study.seed),
                }
                self.ledger.record(
                    study_id,
                    f"oos.{cfg.family}.{multiplier}",
                    "OOS",
                    cfg.content_hash(),
                    artifact_bytes(payload),
                )
            primary = results[0]
            reports[cfg.family] = {
                "config_hash": cfg.content_hash(),
                "metrics": metrics(primary),
                "screen": screen(
                    primary,
                    block_uncertainty(primary),
                    tuple(results),
                    stable.get(cfg.family, False),
                )
                if cfg.family in ("BREAKOUT", "MEAN_REVERSION")
                else {"verdict": "BASELINE_ONLY", "promotion_eligible": False},
            }
        return reports
