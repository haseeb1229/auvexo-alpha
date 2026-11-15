"""Trial identity binding (RS-9) and derived walk-forward folds (RS-10); synthetic only."""

import ast
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from research_fixtures import config, prices, synthetic_study

from auvexo_alpha.application.research_study import (
    FOLD_RULE,
    WalkForwardFold,
    frozen_configs,
    walk_forward_folds,
)
from auvexo_alpha.domain.research import ResearchSplit, TrialIdentity, bars_digest
from auvexo_alpha.infrastructure import research_ledger
from auvexo_alpha.infrastructure.research_data import ResearchDataReader
from auvexo_alpha.infrastructure.research_ledger import (
    LOCK_FILE,
    PACKAGE,
    RESEARCH_MODULES,
    ResearchLedger,
    dependency_lock_hash,
    research_code_hash,
    trial_artifact,
)


def closure(*roots):
    """Every project module executed by importing the roots: imports plus package inits."""
    seen, pending = set(), list(roots)
    while pending:
        relative = pending.pop()
        if relative in seen:
            continue
        seen.add(relative)
        parts = relative.split("/")
        for depth in range(len(parts)):
            init = "/".join([*parts[:depth], "__init__.py"])
            if (PACKAGE / init).is_file() and init not in seen:
                pending.append(init)
        tree = ast.parse((PACKAGE / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            for name in names:
                if name.startswith("auvexo_alpha."):
                    path = name.removeprefix("auvexo_alpha.").replace(".", "/")
                    pending.append(
                        path + ".py"
                        if (PACKAGE / (path + ".py")).is_file()
                        else path + "/__init__.py"
                    )
    return seen


def test_research_code_hash_covers_exactly_the_research_import_closure():
    assert closure("infrastructure/research_worker.py", "infrastructure/research_data.py") == set(
        RESEARCH_MODULES
    )
    # Hand oracle: path-bound concatenation in the fixed order.
    digest = hashlib.sha256()
    for relative in RESEARCH_MODULES:
        digest.update(relative.encode() + b":" + (PACKAGE / relative).read_bytes() + b"\n")
    assert research_code_hash() == digest.hexdigest()
    assert dependency_lock_hash() == hashlib.sha256(LOCK_FILE.read_bytes()).hexdigest()


def test_missing_lock_refuses_instead_of_guessing(monkeypatch, tmp_path):
    monkeypatch.setattr(research_ledger, "LOCK_FILE", tmp_path / "uv.lock")
    with pytest.raises(ValueError, match="^DEPENDENCY_LOCK_UNAVAILABLE$"):
        dependency_lock_hash()


def identity(study, cfg=None, **changes):
    cfg = cfg or study.configs[0]
    bars = prices(30)
    values = dict(
        study_hash=study.content_hash(),
        purpose="RESULT",
        config=cfg,
        config_hash=cfg.content_hash(),
        cost_model=study.costs,
        availability=study.availability,
        reads=(bars_digest(bars),),
        consumed_digest=bars_digest(bars),
        consumed_rows=len(bars),
        code_hash=study.code_hash,
        dependency_hash=study.dependency_hash,
    )
    return TrialIdentity.model_validate(values | changes)


def test_config_hash_must_be_derived_from_the_embedded_config():
    study = synthetic_study()
    with pytest.raises(ValidationError, match="TRIAL_CONFIG_HASH_NOT_DERIVED"):
        identity(study, config_hash=study.configs[1].content_hash())


def test_bars_digest_is_order_and_content_sensitive():
    bars = prices(3)
    assert (
        bars_digest(bars)
        == hashlib.sha256(b"\n".join(b.canonical_bytes() for b in bars)).hexdigest()
    )
    assert bars_digest(bars) != bars_digest(list(reversed(bars)))
    assert bars_digest(bars) != bars_digest(bars[:2])
    with pytest.raises(ValueError, match="EMPTY_RESEARCH_INPUT"):
        bars_digest([])


class Reads:
    def __init__(self, rows):
        self.rows, self.asked = rows, []

    def execute(self, statement, parameters=None):
        self.asked.append(parameters)
        return SimpleNamespace(all=lambda: self.rows)


def check(study, phase, artifact, reads, config_hash=None):
    ResearchLedger.check_trial_identity(
        Reads(reads),
        study,
        phase,
        config_hash or study.configs[0].content_hash(),
        json.loads(artifact),
    )


def test_trial_identity_accepts_only_what_the_study_registered():
    study = synthetic_study()
    good = identity(study)
    served = [(good.reads[0], "VALIDATION")]
    check(
        study, "VALIDATION", trial_artifact(good, result={"config_hash": good.config_hash}), served
    )
    stressed = identity(
        study, cost_model=study.costs.model_copy(update={"multiplier": Decimal("2")})
    )
    check(study, "VALIDATION", trial_artifact(stressed), served)
    wrong = {
        "study": identity(study, study_hash="1" * 64),
        "code": identity(study, code_hash="1" * 64),
        "lock": identity(study, dependency_hash="1" * 64),
        "costs": identity(
            study, cost_model=study.costs.model_copy(update={"multiplier": Decimal("3")})
        ),
        "policy": identity(
            study, availability=study.availability.model_copy(update={"lag_microseconds": 2})
        ),
        "unregistered": identity(study, config(lookback=25)),
    }
    for bad in wrong.values():
        with pytest.raises(ValueError, match="^TRIAL_IDENTITY_MISMATCH$"):
            check(study, "VALIDATION", trial_artifact(bad), served, bad.config_hash)
    # The filed config, the artifact's identity and the result must all agree.
    other = study.configs[1].content_hash()
    with pytest.raises(ValueError, match="^TRIAL_IDENTITY_MISMATCH$"):
        check(study, "VALIDATION", trial_artifact(good), served, other)
    with pytest.raises(ValueError, match="^TRIAL_IDENTITY_MISMATCH$"):
        check(study, "VALIDATION", trial_artifact(good, result={"config_hash": other}), served)
    for artifact in (b"{}", b'{"identity": []}', b'{"identity": {"purpose": "RESULT"}}'):
        with pytest.raises(ValueError, match="^TRIAL_IDENTITY_MISMATCH$"):
            check(study, "VALIDATION", artifact, served)


def test_trial_reads_must_be_receipted_reads_of_this_study_and_phase():
    study = synthetic_study()
    good = identity(study)
    artifact = trial_artifact(good)
    with pytest.raises(ValueError, match="^TRIAL_READ_NOT_AUTHORIZED$"):
        check(study, "VALIDATION", artifact, [])
    with pytest.raises(ValueError, match="^TRIAL_READ_NOT_AUTHORIZED$"):
        check(study, "VALIDATION", artifact, [(good.reads[0], "TRAIN")])
    with pytest.raises(ValueError, match="TRIAL_IDENTITY_MISMATCH"):
        trial_artifact(good, identity={})


def split(train_start, train_end, embargo_hours=48):
    gap = timedelta(hours=embargo_hours)
    return ResearchSplit(
        train_start=train_start,
        train_end=train_end,
        validation_start=train_end + gap,
        validation_end=train_end + gap + timedelta(days=30),
        oos_start=train_end + 2 * gap + timedelta(days=30),
        oos_end=train_end + 2 * gap + timedelta(days=60),
        purge_embargo_seconds=embargo_hours * 3600,
    )


def at(*parts):
    return datetime(*parts, tzinfo=UTC)


def test_phase3_split_derives_the_single_non_duplicate_fold():
    """Hand oracle: two years make two 365-day segments, so one fold: fit 2022, evaluate 2023
    after the embargo. The old second fold (evaluate 2024) repeated validation exactly.
    """
    folds = walk_forward_folds(split(at(2022, 1, 1), at(2024, 1, 1)))
    assert folds == (
        WalkForwardFold(0, at(2022, 1, 1), at(2023, 1, 1), at(2023, 1, 3), at(2024, 1, 1)),
    )
    assert folds[0].role == "INFORMATIONAL_ONLY" and folds[0].rule == FOLD_RULE


def test_folds_follow_the_registered_span_not_calendar_years():
    # 3 years and 12 hours from mid-year: three segments of 365 days 4 hours each.
    folds = walk_forward_folds(split(at(2021, 7, 1), at(2024, 7, 1, 12)))
    span = at(2024, 7, 1, 12) - at(2021, 7, 1)
    assert span == timedelta(days=1096, hours=12)
    first, second = (
        at(2021, 7, 1) + timedelta(days=365, hours=12),
        at(2021, 7, 1) + timedelta(days=731),
    )
    assert [(f.fit_end, f.evaluate_start, f.evaluate_end) for f in folds] == [
        (first, first + timedelta(days=2), second),
        (second, second + timedelta(days=2), at(2024, 7, 1, 12)),
    ]
    assert all(f.fit_start == at(2021, 7, 1) for f in folds)
    # A short span still has one fold; boundaries are floored to the hour.
    (short,) = walk_forward_folds(split(at(2024, 1, 1), at(2024, 1, 11, 1), embargo_hours=24))
    assert short.fit_end == at(2024, 1, 6) and short.evaluate_start == at(2024, 1, 7)


def test_fold_emptied_by_the_embargo_is_refused():
    with pytest.raises(ValueError, match="^WALK_FORWARD_FOLD_EMPTY_AFTER_EMBARGO$"):
        walk_forward_folds(split(at(2024, 1, 1), at(2024, 1, 5), embargo_hours=48))


def test_every_fold_stays_inside_training_and_never_reaches_validation():
    study = synthetic_study(configs=frozen_configs())
    for fold in walk_forward_folds(study.split):
        assert study.split.train_start <= fold.fit_start < fold.fit_end <= study.split.train_end
        assert fold.evaluate_end <= study.split.train_end < study.split.validation_start


class ConflictStore:
    def __init__(self, conflicts):
        self.recorded, self.verified = conflicts, []

    def conflicts(self, instrument, interval, start, end):
        self.asked = (instrument, interval, start, end)
        return self.recorded

    def verify(self, manifest):
        self.verified.append(manifest)


class AuthorizingLedger:
    def __init__(self, study):
        self.study = study

    def authorize_read(self, study_id, phase, start, end):
        return SimpleNamespace(study=self.study)


@pytest.mark.parametrize("side", ["archive_version", "rest_version"])
def test_reader_refuses_bars_with_a_recorded_cross_source_conflict(side):
    study = synthetic_study()
    version = study.inputs[0].manifest.dataset_version
    conflict = SimpleNamespace(
        **({"archive_version": "a" * 64, "rest_version": "b" * 64} | {side: version})
    )
    store = ConflictStore([conflict])
    reader = ResearchDataReader(AuthorizingLedger(study), store)
    coverage = study.inputs[0].manifest.coverage
    start, end = coverage.requested_start, coverage.requested_end
    with pytest.raises(ValueError, match="^CROSS_SOURCE_CONFLICT_UNRESOLVED$"):
        reader.read(study.study_id, "TRAIN", start, end)
    assert store.asked == (study.instrument, "1h", start, end) and store.verified == []
