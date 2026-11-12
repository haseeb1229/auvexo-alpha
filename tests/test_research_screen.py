"""Constructed-input tests for selection, screening and verdict evidence; synthetic only."""

import hashlib
import json
from decimal import Decimal, localcontext

import pytest
from research_fixtures import config, fitted, synthetic_result, synthetic_study, wave_prices

from auvexo_alpha.application.research_metrics import block_uncertainty
from auvexo_alpha.application.research_simulator import artifact_bytes, simulate
from auvexo_alpha.application.research_study import frozen_configs, screen, select_validation
from auvexo_alpha.domain.research import CostModel, PriceAvailability
from auvexo_alpha.infrastructure.research_ledger import SELECTION_TRIAL, frozen_selection
from auvexo_alpha.infrastructure.research_worker import ResearchWorker

POLICY = PriceAvailability(lag_microseconds=1_000_000)
LIMIT = Decimal("0.2")
TWO_REGIMES = ("LOW_VOL_UP", "HIGH_VOL_DOWN")
POSITIVE = {"adjusted_lower": 1.0, "lower_95": 2.0}
SURVIVED = tuple(synthetic_result(["10000"], final="10001") for _ in range(3))


def passing(days=184, trades=100, pnl="10", regimes=TWO_REGIMES, equity=None):
    """184 daily closes span 183 days = 6.01 months; 100 trades of +10 in two regimes."""
    return synthetic_result(
        equity or ["10000"] * days, [(i, pnl) for i in range(trades)], regimes=regimes
    )


def verdict(result=None, uncertainty=POSITIVE, stress=SURVIVED, stable=True, limit=LIMIT):
    report = screen(result or passing(), uncertainty, stress, stable, max_drawdown=limit)
    return report["verdict"], report["reasons"]


def test_candidate_requires_every_screen_and_is_never_promotion_eligible():
    report = screen(passing(), POSITIVE, SURVIVED, True, max_drawdown=LIMIT)
    assert report["verdict"] == "CANDIDATE" and report["reasons"] == ()
    assert report["promotion_eligible"] is False
    assert report["data_use"] == "PERSONAL_RESEARCH_NONPRODUCTION_ONLY"
    # 183 days / 30.4375 days per month = 6.0123 months.
    assert report["oos_months_approx"] == pytest.approx(6.012320328542094)
    assert report["inputs"] == {
        "closed_trades": 100,
        "observed_regimes": ("HIGH_VOL_DOWN", "LOW_VOL_UP"),
        "net_trade_pnl": Decimal(1000),  # 100 trades * 10
        "uncertainty": POSITIVE,
        "stress_equity": ((Decimal(10000), Decimal(10001)),) * 3,
        "stable_neighbors": True,
        "max_drawdown": Decimal(0),
        "max_drawdown_limit": LIMIT,
    }


@pytest.mark.parametrize(
    "result,reason",
    [
        (passing(trades=99), "FEWER_THAN_100_CLOSED_OOS_TRADES"),
        # 183 daily closes span 182 days = 5.98 months.
        (passing(days=183), "FEWER_THAN_SIX_OOS_MONTHS"),
        (passing(regimes=("LOW_VOL_UP",)), "SINGLE_OR_NO_OBSERVED_REGIME"),
    ],
)
def test_each_insufficient_sample_reason_alone_is_inconclusive(result, reason):
    assert verdict(result) == ("INCONCLUSIVE", (reason,))


def test_each_failed_screen_alone_is_no_edge():
    # Fifty +10 and fifty -10 trades net exactly zero: not a positive expectancy.
    flat = synthetic_result(
        ["10000"] * 184, [(i, "10" if i % 2 else "-10") for i in range(100)], regimes=TWO_REGIMES
    )
    assert verdict(flat) == ("NO_EDGE", ("NONPOSITIVE_NET_EXPECTANCY",))
    for lower in (0.0, -1.0, None):
        assert verdict(uncertainty=POSITIVE | {"adjusted_lower": lower}) == (
            "NO_EDGE",
            ("BONFERRONI_BLOCK_LOWER_NOT_POSITIVE",),
        )
        assert verdict(uncertainty=POSITIVE | {"lower_95": lower}) == (
            "NO_EDGE",
            ("DEPENDENCE_AWARE_95_LOWER_NOT_POSITIVE",),
        )
    breakeven = (*SURVIVED[:2], synthetic_result(["10000"], final="10000"))
    for stress in (breakeven, ()):
        assert verdict(stress=stress) == ("NO_EDGE", ("COST_STRESS_NOT_SURVIVED",))
    assert verdict(stable=False) == ("NO_EDGE", ("PREREGISTERED_VALIDATION_NEIGHBORS_UNSTABLE",))


def test_drawdown_screen_uses_the_registered_limit_inclusively():
    # Peak 10000 then 8000: drawdown 1 - 8000 / 10000 = 0.2, exactly the limit and allowed.
    at_limit = passing(equity=["10000", "8000", *["10000"] * 182])
    assert verdict(at_limit) == ("CANDIDATE", ())
    # 7999 gives 0.2001 > 0.2.
    beyond = passing(equity=["10000", "7999", *["10000"] * 182])
    assert verdict(beyond) == ("NO_EDGE", ("DRAWDOWN_EXCEEDS_20_PERCENT",))
    # 8500 gives 0.15: inside a registered 20% limit, outside a registered 10% limit.
    moderate = passing(equity=["10000", "8500", *["10000"] * 182])
    assert verdict(moderate) == ("CANDIDATE", ())
    assert verdict(moderate, limit=Decimal("0.1")) == ("NO_EDGE", ("DRAWDOWN_EXCEEDS_10_PERCENT",))
    assert verdict(moderate, limit=Decimal("0.15")) == ("CANDIDATE", ())


def test_insufficient_sample_dominates_failed_screens_in_evaluation_order():
    empty = synthetic_result(["10000"])
    assert verdict(empty, {"reason": "NO_CLOSED_TRADES_OR_DAYS"}, (), False) == (
        "INCONCLUSIVE",
        (
            "FEWER_THAN_100_CLOSED_OOS_TRADES",
            "FEWER_THAN_SIX_OOS_MONTHS",
            "SINGLE_OR_NO_OBSERVED_REGIME",
            "NONPOSITIVE_NET_EXPECTANCY",
            "BONFERRONI_BLOCK_LOWER_NOT_POSITIVE",
            "DEPENDENCE_AWARE_95_LOWER_NOT_POSITIVE",
            "COST_STRESS_NOT_SURVIVED",
            "PREREGISTERED_VALIDATION_NEIGHBORS_UNSTABLE",
        ),
    )


def validation_results(equities):
    return {
        cfg.content_hash(): synthetic_result(["10000"], final=equity)
        for cfg, equity in zip(frozen_configs(), equities, strict=True)
    }


def test_selection_takes_the_best_validation_equity_per_family_in_family_order():
    configs = frozen_configs()
    hashes = [c.content_hash() for c in configs]
    # Grid order: NO_TRADE, PASSIVE, FIXED_RULE, BREAKOUT 72, BREAKOUT 168, MR 24, MR 72.
    validation = validation_results(["10000", "10500", "9900", "10100", "10200", "9900", "9800"])
    expected = (hashes[0], hashes[1], hashes[2], hashes[4], hashes[5])
    assert select_validation(configs, validation) == expected
    assert select_validation(tuple(reversed(configs)), validation) == expected


def test_selection_tie_breaks_on_the_smallest_config_hash_not_grid_order():
    configs = frozen_configs()
    hashes = [c.content_hash() for c in configs]
    validation = validation_results(["10000"] * 7)
    expected = (
        hashes[0],
        hashes[1],
        hashes[2],
        min(hashes[3], hashes[4]),
        min(hashes[5], hashes[6]),
    )
    assert select_validation(configs, validation) == expected
    assert select_validation(tuple(reversed(configs)), validation) == expected


def test_selection_refuses_an_incomplete_or_foreign_grid_and_a_missing_family():
    configs = frozen_configs()
    validation = validation_results(["10000"] * 7)
    missing = dict(list(validation.items())[:-1])
    with pytest.raises(ValueError, match="INCOMPLETE_VALIDATION_SELECTION"):
        select_validation(configs, missing)
    with pytest.raises(ValueError, match="INCOMPLETE_VALIDATION_SELECTION"):
        select_validation(configs, validation | {"f" * 64: synthetic_result(["10000"])})
    without_reversion = configs[:5]
    with pytest.raises(ValueError, match="MISSING_PREREGISTERED_FAMILY"):
        select_validation(
            without_reversion, {c.content_hash(): validation[c.content_hash()] for c in configs[:5]}
        )


def test_selection_and_screen_do_not_depend_on_the_ambient_decimal_context():
    configs = frozen_configs()
    low, high = sorted(c.content_hash() for c in configs if c.family == "BREAKOUT")
    validation = validation_results(["10000"] * 7)
    # The larger hash wins only on its 1e-8 better equity; five-digit rounding would tie
    # the two and wrongly fall back to the smaller hash.
    validation[low] = synthetic_result(["10000"], final="10000.00000001")
    validation[high] = synthetic_result(["10000"], final="10000.00000002")
    marginal = synthetic_result(
        ["10000"] * 184,
        [(0, "0.00000001"), *[(i, "10" if i % 2 else "-10") for i in range(100)]],
        regimes=TWO_REGIMES,
    )
    with localcontext() as context:
        context.prec = 5
        assert high in select_validation(configs, validation)
        # Net pnl is exactly +0.00000001; five-digit sums would lose it.
        assert verdict(marginal) == ("CANDIDATE", ())


OLD_SCREEN_KEYS = ("verdict", "reasons", "oos_months_approx", "data_use", "promotion_eligible")


@pytest.mark.parametrize(
    "family,recorded",
    [
        # sha256 of the pre-change output of screen(primary, block_uncertainty(primary), ...)
        # with its then hard-coded seed 1229 / 2000 draws / 14 days / 4 comparisons / 0.20.
        ("BREAKOUT", "e4f5b6cb0a51b409e903a07f14f7e0090b6930289e9297f8ecbfa8dc2fcd1f48"),
        ("MEAN_REVERSION", "5ab472890f58a57c915e498b79e5cd0b4f6658c3da83af94fced1876e0ef28dd"),
    ],
)
def test_manifest_driven_screen_reproduces_the_previous_defaults_for_data_plan_values(
    family, recorded
):
    study = synthetic_study()
    assert (study.seed, study.bootstrap_samples, study.bootstrap_block_days) == (1229, 2000, 14)
    assert (study.comparisons, study.max_drawdown) == (4, Decimal("0.2"))
    bars = wave_prices(1200)
    results = tuple(
        simulate(bars, config(family), POLICY, CostModel(multiplier=m), fitted())
        for m in study.stress_multipliers
    )
    registered = block_uncertainty(
        results[0],
        seed=study.seed,
        draws=study.bootstrap_samples,
        block_days=study.bootstrap_block_days,
        comparisons=study.comparisons,
    )
    assert registered == block_uncertainty(results[0])
    report = screen(results[0], registered, results, True, max_drawdown=study.max_drawdown)
    previous = {"u": registered, "s": {key: report[key] for key in OLD_SCREEN_KEYS}}
    assert hashlib.sha256(artifact_bytes(previous)).hexdigest() == recorded
    if family == "BREAKOUT":
        # The literal pre-change numbers, 119 closed trades over 50 synthetic days.
        assert registered["lower_95"] == 1954.5650064658328
        assert registered["upper_95"] == 11984.062776587392
        assert registered["adjusted_lower"] == 1401.4884138189827
        assert report["verdict"] == "INCONCLUSIVE"
        assert report["reasons"] == (
            "FEWER_THAN_SIX_OOS_MONTHS",
            "SINGLE_OR_NO_OBSERVED_REGIME",
            "COST_STRESS_NOT_SURVIVED",
        )
        # A different registered seed, sample count, block or family size is not ignored.
        for change in ({"seed": 7}, {"draws": 1000}, {"block_days": 7}, {"comparisons": 8}):
            values = dict(seed=1229, draws=2000, block_days=14, comparisons=4) | change
            assert block_uncertainty(results[0], **values) != registered


class MemoryLedger:
    """Worker-facing ledger port in memory; the PostgreSQL gates are integration tests."""

    def __init__(self, study):
        self.manifest, self.trials, self.opened = study, {}, None

    def study(self, study_id):
        return self.manifest

    def record(self, study_id, trial_id, phase, config_hash, result):
        assert trial_id not in self.trials and len(self.trials) < self.manifest.trial_budget
        assert (phase == "OOS") == (self.opened is not None)
        self.trials[trial_id] = result

    def read_trial(self, study_id, trial_id):
        return self.trials[trial_id]

    def open_holdout(self, study_id, selected):
        frozen = self.read_trial(study_id, SELECTION_TRIAL)
        assert frozen_selection(self.manifest.configs, frozen) == selected
        self.opened = selected


class WaveReader:
    def read(self, study_id, phase, start, end):
        return wave_prices(200, start, drift=1)


def run_worker(**registered):
    study = synthetic_study(configs=frozen_configs()).model_copy(update=registered)
    ledger = MemoryLedger(study)
    worker = ResearchWorker(ledger, WaveReader())
    worker.development(study.study_id)
    return study, ledger, worker.holdout(study.study_id)


def test_worker_records_each_hypothesis_verdict_with_its_inputs_inside_the_trial_budget():
    study, ledger, report = run_worker()
    # 1 fit + 7 train + 14 fold + 21 validation + 1 selection + 15 OOS + 2 verdicts.
    assert len(ledger.trials) == 61 <= study.trial_budget == 64
    assert sorted(t for t in ledger.trials if t.startswith("verdict.")) == [
        "verdict.BREAKOUT",
        "verdict.MEAN_REVERSION",
    ]
    assert len(ledger.opened) == 5 and len(report) == 5
    for family in ("NO_TRADE", "PASSIVE", "FIXED_RULE"):
        assert report[family]["screen"] == {"verdict": "BASELINE_ONLY", "promotion_eligible": False}
    for family in ("BREAKOUT", "MEAN_REVERSION"):
        recorded = json.loads(ledger.trials["verdict." + family])
        assert recorded["family"] == family
        assert recorded["config_hash"] == report[family]["config_hash"]
        assert recorded["screen"] == json.loads(artifact_bytes(report[family]["screen"]))
        assert recorded["screen"]["verdict"] == "INCONCLUSIVE" and recorded["screen"]["reasons"]
        assert recorded["registered"] == {
            "seed": 1229,
            "bootstrap_samples": 2000,
            "bootstrap_block_days": 14,
            "comparisons": 4,
            "max_drawdown": "0.2",
            "stress_multipliers": ["1", "1.5", "2"],
        }
        assert recorded["trials"] == [f"oos.{family}.{m}" for m in ("1", "1.5", "2")]
        primary = json.loads(ledger.trials[f"oos.{family}.1"])
        assert list(primary["uncertainty"]) == ["14", "28", "7"]
        assert recorded["screen"]["inputs"]["uncertainty"] == primary["uncertainty"]["14"]
        assert len(recorded["screen"]["inputs"]["stress_equity"]) == 3
    breakout = json.loads(ledger.trials["verdict.BREAKOUT"])["screen"]["inputs"]
    assert breakout["closed_trades"] > 0 and breakout["uncertainty"]["draws"] == 2000


def test_worker_verdict_follows_non_default_registered_parameters():
    registered = dict(
        seed=7,
        bootstrap_samples=1000,
        bootstrap_block_days=21,
        comparisons=8,
        max_drawdown=Decimal("0.1"),
    )
    study, ledger, _ = run_worker(**registered)
    recorded = json.loads(ledger.trials["verdict.BREAKOUT"])
    assert recorded["registered"] == {
        "seed": 7,
        "bootstrap_samples": 1000,
        "bootstrap_block_days": 21,
        "comparisons": 8,
        "max_drawdown": "0.1",
        "stress_multipliers": ["1", "1.5", "2"],
    }
    inputs = recorded["screen"]["inputs"]
    assert inputs["max_drawdown_limit"] == "0.1"
    primary = json.loads(ledger.trials["oos.BREAKOUT.1"])
    assert sorted(primary["uncertainty"], key=int) == ["7", "21", "28"]
    assert inputs["uncertainty"] == primary["uncertainty"]["21"]
    assert (inputs["uncertainty"]["draws"], inputs["uncertainty"]["block_days"]) == (1000, 21)
    assert inputs["uncertainty"]["comparisons"] == 8
    # The same replay under the DATA_PLAN defaults yields a different registered bootstrap.
    _, default_ledger, _ = run_worker()
    default = json.loads(default_ledger.trials["verdict.BREAKOUT"])["screen"]["inputs"]
    assert default["closed_trades"] == inputs["closed_trades"] > 0
    assert default["uncertainty"] != inputs["uncertainty"]
