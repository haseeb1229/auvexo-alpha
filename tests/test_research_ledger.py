"""Real-PostgreSQL research ledger gates on a generated database per module (DB-2).

Synthetic studies and far-future synthetic holdouts only; no consumed Phase 3 holdout,
real market data or historical outcome is read, re-run or re-labelled.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from pg_fixtures import GENERATED, admin_arguments, database_exists, engine_for, generated_database
from research_fixtures import prices, synthetic_study, unused_holdout_start
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from auvexo_alpha.application.research_simulator import artifact_bytes
from auvexo_alpha.application.research_study import frozen_configs
from auvexo_alpha.domain.research import ResearchSplit, TrialIdentity, bars_digest
from auvexo_alpha.infrastructure.database import SCHEMA_REVISION
from auvexo_alpha.infrastructure.research_data import ResearchRead
from auvexo_alpha.infrastructure.research_ledger import (
    SELECTION_TRIAL,
    ResearchLedger,
    trial_artifact,
)
from auvexo_alpha.infrastructure.research_worker import ResearchWorker

pytestmark = pytest.mark.integration


class FixtureLedger(ResearchLedger):
    """The research role's ledger; the admin engine only places synthetic inputs in the store."""

    def __init__(self, engine, admin, root, managed):
        super().__init__(engine, root, managed)
        self.admin = admin

    def store_inputs(self, study):
        with self.admin.begin() as conn:
            for item in study.inputs:
                m = item.manifest
                conn.execute(
                    text(
                        "INSERT INTO data_manifest VALUES (:v,:k,:s,:t,NULL,:h,:p) "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {
                        "v": m.dataset_version,
                        "k": m.logical_key,
                        "s": m.source_hash,
                        "t": m.created_at,
                        "h": m.content_hash(),
                        "p": m.canonical_bytes().decode(),
                    },
                )

    def register(self, study):
        self.store_inputs(study)
        super().register(study)


@pytest.fixture(scope="module")
def database():
    with generated_database() as name:
        yield name
    assert not database_exists(name)


@pytest.fixture
def ledger(database, tmp_path):
    engine = engine_for(database, "auvexo_research")
    admin = engine_for(database)
    try:
        yield FixtureLedger(engine, admin, tmp_path / "artifacts", tmp_path)
    finally:
        engine.dispose()
        admin.dispose()


PHASE_START = {
    "TRAIN": "train_start",
    "WALK_FORWARD": "train_start",
    "VALIDATION": "validation_start",
    "OOS": "oos_start",
}


def served(ledger, study, phase):
    """One authorized, logged read of 24 synthetic bars, bound to its digest."""
    start = getattr(study.split, PHASE_START[phase])
    authorized = ledger.authorize_read(study.study_id, phase, start, start + timedelta(hours=24))
    bars = prices(24, start)
    return ledger.bind_read(authorized, bars), bars


def data(ledger, study, cfg, phase, **content):
    digest, bars = served(ledger, study, phase)
    identity = TrialIdentity(
        study_hash=study.content_hash(),
        purpose="RESULT",
        config=cfg,
        config_hash=cfg.content_hash(),
        cost_model=study.costs,
        availability=study.availability,
        reads=(digest,),
        consumed_digest=bars_digest(bars),
        consumed_rows=len(bars),
        code_hash=study.code_hash,
        dependency_hash=study.dependency_hash,
    )
    return trial_artifact(identity, fixture="SYNTHETIC_ONLY", **content)


def one_per_family(study, last=False):
    """The first (or last) registered config of each family, in grid order."""
    chosen = {}
    for cfg in study.configs:
        if last or cfg.family not in chosen:
            chosen[cfg.family] = cfg.content_hash()
    return tuple(chosen.values())


def validate_grid(ledger, study, configs=None):
    for index, cfg in enumerate(configs or study.configs):
        ledger.record(
            study.study_id,
            f"grid{index}",
            "VALIDATION",
            cfg.content_hash(),
            data(ledger, study, cfg, "VALIDATION"),
        )


def freeze(ledger, study, selected, phase="VALIDATION"):
    return ledger.record(
        study.study_id,
        SELECTION_TRIAL,
        phase,
        study.configs[0].content_hash(),
        data(ledger, study, study.configs[0], phase, selected=selected),
    )


def sealed(ledger, study):
    return ledger.holdout_state(study.study_id) == "SEALED"


def registered(ledger, study):
    with ledger.engine.connect() as conn:
        return bool(
            conn.scalar(
                text("SELECT count(*) FROM research_study WHERE study_id=:id"),
                {"id": study.study_id},
            )
        )


def around(holdout_start, **changes):
    """A study whose validation window [T-3d, T+300h) spans a holdout starting at T."""
    split = ResearchSplit(
        train_start=holdout_start - timedelta(days=10),
        train_end=holdout_start - timedelta(days=5),
        validation_start=holdout_start - timedelta(days=3),
        validation_end=holdout_start + timedelta(hours=300),
        oos_start=holdout_start + timedelta(hours=348),
        oos_end=holdout_start + timedelta(hours=548),
        purge_embargo_seconds=172800,
    )
    return synthetic_study(**changes).model_copy(update={"split": split})


def insert_unchecked(ledger, study):
    """A row as written before the registration gates existed; reads must still refuse."""
    ledger.store_inputs(study)
    with ledger.engine.begin() as conn:
        conn.execute(
            text("INSERT INTO research_study VALUES (:id,:hash,:payload,:at)"),
            {
                "id": study.study_id,
                "hash": study.content_hash(),
                "payload": study.canonical_bytes().decode(),
                "at": study.registered_at,
            },
        )


def test_generated_database_is_validated_migrated_and_dropped():
    with generated_database() as name:
        assert GENERATED.fullmatch(name) and database_exists(name)
        with psycopg.connect(**(admin_arguments() | {"dbname": name})) as conn:
            assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (
                SCHEMA_REVISION,
            )
            conn.execute("CREATE TABLE leftover(x int)")
            conn.commit()
    # Cleanup proof: the whole database, with every row any test wrote, is gone.
    assert not database_exists(name)


def test_ledger_hashes_duplicates_seal_and_immutable_artifacts(ledger):
    study = synthetic_study(configs=frozen_configs())
    ledger.register(study)
    with pytest.raises(IntegrityError):
        ledger.register(study)
    first = study.configs[0]
    cfg = first.content_hash()
    selected = one_per_family(study)
    payload = data(ledger, study, first, "VALIDATION")
    digest = ledger.record(study.study_id, "trial", "VALIDATION", cfg, payload)
    assert ledger.path(digest).read_bytes() == payload
    with pytest.raises(IntegrityError):
        ledger.record(study.study_id, "trial", "VALIDATION", cfg, payload)
    with pytest.raises(ValueError, match="HOLDOUT_NOT_OPEN"):
        ledger.authorize_read(study.study_id, "OOS", study.split.oos_start, study.split.oos_end)
    with pytest.raises(ValueError, match="GRID_INCOMPLETE"):
        ledger.open_holdout(study.study_id, selected)
    validate_grid(ledger, study, study.configs[1:])
    late_development = data(ledger, study, first, "VALIDATION")
    frozen = freeze(ledger, study, selected)
    ledger.open_holdout(study.study_id, selected)
    with ledger.engine.connect() as conn:
        assert ledger.selected(conn, study.study_id) == selected
        payload_event = json.loads(
            conn.scalar(
                text("SELECT payload FROM research_event WHERE study_id=:id"),
                {"id": study.study_id},
            )
        )
    assert payload_event == {
        "claim": "CONSUMED_BEFORE_READ",
        "selected": list(selected),
        "selection_artifact": frozen,
    }
    with pytest.raises(ValueError, match="DEVELOPMENT_ALREADY_CONSUMED"):
        ledger.record(study.study_id, "post-oos", "VALIDATION", cfg, late_development)
    ledger.authorize_read(study.study_id, "OOS", study.split.oos_start, study.split.oos_end)
    unselected = next(c for c in study.configs if c.content_hash() not in selected)
    with pytest.raises(ValueError, match="POST_HOLDOUT_CONFIG"):
        ledger.record(
            study.study_id,
            "unselected",
            "OOS",
            unselected.content_hash(),
            data(ledger, study, unselected, "OOS"),
        )
    oos = data(ledger, study, first, "OOS")
    kept = ledger.record(study.study_id, "oos.kept", "OOS", cfg, oos)
    ledger.path(kept).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="CORRUPT_RESEARCH_ARTIFACT"):
        ledger.record(study.study_id, "oos.corrupt", "OOS", cfg, oos)
    with pytest.raises(ValueError, match="CORRUPT_RESEARCH_ARTIFACT"):
        ledger.read_trial(study.study_id, "oos.kept")


def test_open_holdout_accepts_only_the_selection_frozen_before_opening(ledger):
    study = synthetic_study(configs=frozen_configs())
    ledger.register(study)
    validate_grid(ledger, study)
    frozen = one_per_family(study)
    every = tuple(c.content_hash() for c in study.configs)
    # A complete grid is not enough: nothing has been frozen yet.
    with pytest.raises(ValueError, match="SELECTION_NOT_FROZEN_HOLDOUT_SEALED"):
        ledger.open_holdout(study.study_id, frozen)
    freeze(ledger, study, frozen)
    attempts = (
        every,  # the whole grid would be a parameter search against the holdout
        one_per_family(study, last=True),  # the other breakout and mean-reversion windows
        frozen[:-1],
        (*frozen, every[4]),
        tuple(reversed(frozen)),
    )
    for attempt in attempts:
        with pytest.raises(ValueError, match="HOLDOUT_SELECTION_NOT_FROZEN"):
            ledger.open_holdout(study.study_id, attempt)
    for attempt in ((), ("f" * 64,)):
        with pytest.raises(ValueError, match="UNREGISTERED_SELECTION"):
            ledger.open_holdout(study.study_id, attempt)
    assert sealed(ledger, study)
    with pytest.raises(ValueError, match="HOLDOUT_NOT_OPEN"):
        ledger.authorize_read(study.study_id, "OOS", study.split.oos_start, study.split.oos_end)
    ledger.open_holdout(study.study_id, frozen)
    with ledger.engine.connect() as conn:
        assert ledger.selected(conn, study.study_id) == frozen
    for cfg in study.configs:
        if cfg.content_hash() not in frozen:
            with pytest.raises(ValueError, match="POST_HOLDOUT_CONFIG"):
                ledger.record(
                    study.study_id,
                    "late." + cfg.content_hash()[:8],
                    "OOS",
                    cfg.content_hash(),
                    data(ledger, study, cfg, "OOS"),
                )


@pytest.mark.parametrize("fault", ["whole_grid", "two_breakouts", "missing_family", "duplicate"])
def test_a_selection_not_one_config_per_family_is_never_frozen(ledger, fault):
    """Changed with RS-8: an invalid selection is now refused when it is recorded, inside
    the same transaction, so it never becomes a frozen database fact at all.
    """
    study = synthetic_study(configs=frozen_configs())
    ledger.register(study)
    validate_grid(ledger, study)
    every = tuple(c.content_hash() for c in study.configs)
    good = one_per_family(study)
    recorded = {
        "whole_grid": every,
        "two_breakouts": (*good, every[4]),
        "missing_family": good[:-1],
        "duplicate": (*good[:-1], good[0]),
    }[fault]
    with pytest.raises(ValueError, match="SELECTION_NOT_ONE_CONFIG_PER_FAMILY"):
        freeze(ledger, study, recorded)
    for attempt in (recorded, good):
        with pytest.raises(ValueError, match="SELECTION_NOT_FROZEN_HOLDOUT_SEALED"):
            ledger.open_holdout(study.study_id, attempt)
    assert sealed(ledger, study)
    with ledger.engine.connect() as conn:
        assert not conn.scalar(
            text("SELECT count(*) FROM research_trial WHERE study_id=:id AND trial_id=:t"),
            {"id": study.study_id, "t": SELECTION_TRIAL},
        )


def test_open_holdout_verifies_the_frozen_selection_artifact_and_its_phase(ledger):
    tampered = synthetic_study(configs=frozen_configs())
    ledger.register(tampered)
    validate_grid(ledger, tampered)
    selected = one_per_family(tampered)
    digest = freeze(ledger, tampered, selected)
    artifact = ledger.path(digest)
    original = artifact.read_bytes()
    artifact.write_bytes(artifact_bytes({"selected": selected[:1]}))
    with pytest.raises(ValueError, match="CORRUPT_RESEARCH_ARTIFACT"):
        ledger.open_holdout(tampered.study_id, selected)
    assert sealed(ledger, tampered)
    artifact.write_bytes(original)
    # A selection recorded outside the validation phase was not frozen from validation.
    misfiled = synthetic_study(configs=frozen_configs())
    ledger.register(misfiled)
    validate_grid(ledger, misfiled)
    freeze(ledger, misfiled, selected, phase="TRAIN")
    with pytest.raises(ValueError, match="SELECTION_NOT_FROZEN_HOLDOUT_SEALED"):
        ledger.open_holdout(misfiled.study_id, selected)
    assert sealed(ledger, misfiled)
    # The selection record never counts as a validation result for the config it is filed
    # under: the first config below has no validation trial of its own, so the database
    # refuses to freeze any selection until it has one.
    carrier = synthetic_study(configs=frozen_configs())
    ledger.register(carrier)
    validate_grid(ledger, carrier, carrier.configs[1:])
    with pytest.raises(ValueError, match="^VALIDATION_GRID_INCOMPLETE_SELECTION_NOT_FROZEN$"):
        freeze(ledger, carrier, selected)
    with pytest.raises(ValueError, match="GRID_INCOMPLETE"):
        ledger.open_holdout(carrier.study_id, selected)
    assert sealed(ledger, carrier)
    first = carrier.configs[0]
    ledger.record(
        carrier.study_id,
        "grid.first",
        "VALIDATION",
        first.content_hash(),
        data(ledger, carrier, first, "VALIDATION"),
    )
    freeze(ledger, carrier, selected)
    ledger.open_holdout(carrier.study_id, selected)
    assert not sealed(ledger, carrier)


def test_raw_trials_need_a_bound_read_and_selection_needs_the_whole_grid(ledger):
    """The research role keeps INSERT on research_trial, so the database itself refuses a
    trial without a gate-authorized, digest-bound read of its phase, and a selection
    frozen before every registered config has its own validation result.
    """
    study = synthetic_study(configs=frozen_configs())
    ledger.register(study)
    selected = one_per_family(study)
    trial = "INSERT INTO research_trial VALUES (:id,:t,:p,:c,:h,1,now())"
    raw = {
        "id": study.study_id,
        "t": SELECTION_TRIAL,
        "p": "VALIDATION",
        "c": study.configs[0].content_hash(),
        "h": "e" * 64,
    }
    # No read at all, then only a read of another phase: refused either way.
    for prior in (None, "TRAIN"):
        if prior:
            served(ledger, study, prior)
        with pytest.raises(DBAPIError, match="TRIAL_WITHOUT_AUTHORIZED_READ"):
            with ledger.engine.begin() as conn:
                conn.execute(text(trial), raw)
    # An authorized validation read admits the row, but no selection freezes without the
    # complete validation grid.
    served(ledger, study, "VALIDATION")
    with ledger.engine.begin() as conn:
        conn.execute(text(trial), raw)
        outcome = conn.scalar(
            text("SELECT research_freeze_selection(:id,CAST(:s AS jsonb),:h)"),
            {"id": study.study_id, "s": json.dumps(list(selected)), "h": "e" * 64},
        )
    assert outcome == "VALIDATION_GRID_INCOMPLETE_SELECTION_NOT_FROZEN"
    with pytest.raises(ValueError, match="GRID_INCOMPLETE"):
        ledger.open_holdout(study.study_id, selected)
    assert sealed(ledger, study)
    # After a normal opening, an OOS receipt with no bars bound to it backs no result;
    # the normal recorded path still passes.
    normal = synthetic_study(configs=frozen_configs())
    ledger.register(normal)
    validate_grid(ledger, normal)
    freeze(ledger, normal, selected)
    ledger.open_holdout(normal.study_id, selected)
    split = normal.split
    ledger.authorize_read(normal.study_id, "OOS", split.oos_start, split.oos_end)
    oos = {**raw, "id": normal.study_id, "t": "raw.oos", "p": "OOS", "c": selected[0]}
    with pytest.raises(DBAPIError, match="TRIAL_WITHOUT_AUTHORIZED_READ"):
        with ledger.engine.begin() as conn:
            conn.execute(text(trial), oos)
    chosen = next(c for c in normal.configs if c.content_hash() == selected[0])
    ledger.record(normal.study_id, "oos.0", "OOS", selected[0], data(ledger, normal, chosen, "OOS"))


def test_development_read_of_another_studys_sealed_holdout_is_refused(ledger):
    owner = synthetic_study()
    ledger.register(owner)
    start, end = owner.split.oos_start, owner.split.oos_end
    reader = around(start)
    with pytest.raises(ValueError, match="DEVELOPMENT_OVERLAPS_SEALED_HOLDOUT_OF_ANOTHER_STUDY"):
        ledger.register(reader)
    assert not registered(ledger, reader)
    insert_unchecked(ledger, reader)
    hour = timedelta(hours=1)
    overlapping = (
        ("VALIDATION", start, end),
        ("VALIDATION", start - hour, start + hour),
        ("VALIDATION", end - hour, end + hour),
        ("VALIDATION", reader.split.validation_start, reader.split.validation_end),
    )
    for phase, lower, upper in overlapping:
        with pytest.raises(ValueError, match="READ_OVERLAPS_SEALED_HOLDOUT_OF_ANOTHER_STUDY"):
            ledger.authorize_read(reader.study_id, phase, lower, upper)
    # Changed with RS-10: walk-forward folds are derived inside the training span, so a
    # walk-forward read reaching into validation is now outside the registered split.
    with pytest.raises(ValueError, match="^READ_OUTSIDE_REGISTERED_SPLIT$"):
        ledger.authorize_read(
            reader.study_id, "WALK_FORWARD", reader.split.train_start, reader.split.validation_end
        )
    # Half-open calendars: bars ending at the sealed start or beginning at its end are free.
    ledger.authorize_read(reader.study_id, "VALIDATION", reader.split.validation_start, start)
    ledger.authorize_read(reader.study_id, "VALIDATION", end, reader.split.validation_end)
    ledger.authorize_read(
        reader.study_id, "TRAIN", reader.split.train_start, reader.split.train_end
    )
    # The seal is per instrument: the same calendar on the other spot instrument is free.
    other = around(start, instrument="binance.spot.ETHUSDT")
    ledger.register(other)
    ledger.authorize_read(other.study_id, "VALIDATION", start, end)
    # The owner itself is still sealed, and the refusal ends only once it consumes the holdout.
    with pytest.raises(ValueError, match="HOLDOUT_NOT_OPEN"):
        ledger.authorize_read(owner.study_id, "OOS", start, end)
    validate_grid(ledger, owner)
    selected = one_per_family(owner)
    freeze(ledger, owner, selected)
    ledger.open_holdout(owner.study_id, selected)
    for phase, lower, upper in overlapping:
        ledger.authorize_read(reader.study_id, phase, lower, upper)


def test_registration_refuses_calendars_that_cross_another_studys_holdout(ledger):
    owner = synthetic_study()
    ledger.register(owner)
    start = owner.split.oos_start
    reader = around(start)
    with pytest.raises(ValueError, match="DEVELOPMENT_OVERLAPS_SEALED_HOLDOUT_OF_ANOTHER_STUDY"):
        ledger.register(reader)
    # A holdout inside bars the owner may read as development (2022 to 2025) is not fresh.
    stale = synthetic_study().model_copy(
        update={
            "split": ResearchSplit(
                train_start=datetime(2020, 1, 1, tzinfo=UTC),
                train_end=datetime(2021, 1, 1, tzinfo=UTC),
                validation_start=datetime(2021, 1, 3, tzinfo=UTC),
                validation_end=datetime(2021, 6, 1, tzinfo=UTC),
                oos_start=datetime(2024, 6, 1, tzinfo=UTC),
                oos_end=datetime(2024, 6, 9, tzinfo=UTC),
                purge_embargo_seconds=172800,
            )
        }
    )
    with pytest.raises(ValueError, match="HOLDOUT_OVERLAPS_DEVELOPMENT_OF_ANOTHER_STUDY"):
        ledger.register(stale)
    assert not registered(ledger, reader) and not registered(ledger, stale)
    # Once the owner has consumed its holdout those bars may become development data.
    validate_grid(ledger, owner)
    selected = one_per_family(owner)
    freeze(ledger, owner, selected)
    ledger.open_holdout(owner.study_id, selected)
    ledger.register(reader)
    ledger.authorize_read(reader.study_id, "VALIDATION", start, owner.split.oos_end)
    # They can then never be claimed as a fresh holdout by a later study.
    late = synthetic_study(oos_start=start)
    with pytest.raises(ValueError, match="HOLDOUT_OVERLAPS_DEVELOPMENT_OF_ANOTHER_STUDY"):
        ledger.register(late)
    assert not registered(ledger, late)


def test_research_artifact_quota_pressure_and_trial_budget_refuse_before_publication(
    ledger, monkeypatch
):
    study = synthetic_study().model_copy(update={"trial_budget": 1})
    ledger.register(study)
    first = study.configs[0]
    cfg = first.content_hash()
    payload = data(ledger, study, first, "TRAIN")
    ledger.quota = 1
    with pytest.raises(ValueError, match="STORAGE_PRESSURE"):
        ledger.record(study.study_id, "quota", "TRAIN", cfg, payload)
    assert not list(ledger.root.iterdir())
    ledger.quota = 512 * 1024 * 1024
    with monkeypatch.context() as patch:
        patch.setattr(
            "auvexo_alpha.infrastructure.research_ledger.pressure", lambda *args: "HARD_STOP"
        )
        with pytest.raises(ValueError, match="STORAGE_PRESSURE"):
            ledger.record(study.study_id, "pressure", "TRAIN", cfg, payload)
    assert not list(ledger.root.iterdir())
    ledger.record(study.study_id, "first", "TRAIN", cfg, payload)
    with pytest.raises(ValueError, match="TRIAL_BUDGET_EXHAUSTED"):
        ledger.record(study.study_id, "second", "TRAIN", cfg, data(ledger, study, first, "TRAIN"))


def test_actual_role_denies_mutation_and_ingestion_or_policy_writes(ledger):
    ledger.register(synthetic_study())
    for table in (
        "research_study",
        "research_trial",
        "research_event",
        "research_study_config",
        "research_selection",
        "research_read_receipt",
        "research_read_digest",
        "research_holdout_completion",
    ):
        for action in (f"DELETE FROM {table}", f"TRUNCATE {table}"):
            with pytest.raises(DBAPIError), ledger.engine.begin() as conn:
                conn.execute(text(action))
    for statement in (
        "UPDATE foundation_policy SET execution_enabled=true",
        "DELETE FROM data_manifest",
        "INSERT INTO data_source_conflict SELECT * FROM data_source_conflict",
        "CREATE TABLE research_forbidden(x int)",
    ):
        with pytest.raises(DBAPIError), ledger.engine.begin() as conn:
            conn.execute(text(statement))


def test_research_role_cannot_write_gate_records_or_bypass_the_trial_guard(ledger):
    study = synthetic_study(configs=frozen_configs())
    ledger.register(study)
    cfg = study.configs[0].content_hash()
    now = datetime.now(UTC)
    direct = {
        "research_event": (
            "INSERT INTO research_event VALUES (:x,:id,'HOLDOUT_OPEN',:h,'{}',:t)",
            {"x": "forged", "id": study.study_id, "h": "e" * 64, "t": now},
        ),
        "research_selection": (
            "INSERT INTO research_selection VALUES (:id,'[]'::jsonb,:h,:t)",
            {"id": study.study_id, "h": "e" * 64, "t": now},
        ),
        "research_read_receipt": (
            "INSERT INTO research_read_receipt VALUES (:x,:id,'OOS',:t,:e,'OPEN',:t)",
            {"x": "e" * 64, "id": study.study_id, "t": now, "e": now + timedelta(hours=1)},
        ),
        "research_holdout_completion": (
            "INSERT INTO research_holdout_completion VALUES (:id,'[]'::jsonb,:t)",
            {"id": study.study_id, "t": now},
        ),
    }
    for statement, values in direct.values():
        with pytest.raises(DBAPIError, match="permission denied"), ledger.engine.begin() as conn:
            conn.execute(text(statement), values)
    # Even a raw insert by the research role cannot file an OOS trial for a sealed study,
    # a trial under an unregistered config, or a config row after the first trial.
    trial = "INSERT INTO research_trial VALUES (:id,:t,:p,:c,:h,1,now())"
    refusals = (
        (
            {"id": study.study_id, "t": "raw", "p": "OOS", "c": cfg, "h": "e" * 64},
            "HOLDOUT_NOT_OPEN",
        ),
        (
            {"id": study.study_id, "t": "raw", "p": "TRAIN", "c": "f" * 64, "h": "e" * 64},
            "TRIAL_CONFIG_NOT_REGISTERED",
        ),
    )
    for values, code in refusals:
        with pytest.raises(DBAPIError, match=code), ledger.engine.begin() as conn:
            conn.execute(text(trial), values)
    ledger.record(
        study.study_id,
        "first",
        "TRAIN",
        cfg,
        data(ledger, study, study.configs[0], "TRAIN"),
    )
    with pytest.raises(DBAPIError, match="CONFIGS_FROZEN_AFTER_FIRST_TRIAL"):
        with ledger.engine.begin() as conn:
            conn.execute(
                text("INSERT INTO research_study_config VALUES (:id,6,:h,'MEAN_REVERSION')"),
                {"id": study.study_id, "h": "d" * 64},
            )


def test_trial_without_a_receipted_read_or_with_stale_code_is_refused(ledger):
    study = synthetic_study()
    ledger.register(study)
    first = study.configs[0]
    bars = prices(24, study.split.train_start)
    unreceipted = trial_artifact(
        TrialIdentity(
            study_hash=study.content_hash(),
            purpose="RESULT",
            config=first,
            config_hash=first.content_hash(),
            cost_model=study.costs,
            availability=study.availability,
            reads=(bars_digest(bars),),
            consumed_digest=bars_digest(bars),
            consumed_rows=len(bars),
            code_hash=study.code_hash,
            dependency_hash=study.dependency_hash,
        )
    )
    with pytest.raises(ValueError, match="^TRIAL_READ_NOT_AUTHORIZED$"):
        ledger.record(study.study_id, "unread", "TRAIN", first.content_hash(), unreceipted)
    stale = synthetic_study().model_copy(update={"code_hash": "1" * 64})
    with pytest.raises(ValueError, match="^RESEARCH_CODE_HASH_MISMATCH$"):
        ledger.register(stale)
    # A study row written without the gates is still refused at every read.
    insert_unchecked(ledger, stale)
    with pytest.raises(ValueError, match="^RESEARCH_CODE_HASH_MISMATCH$"):
        ledger.authorize_read(
            stale.study_id, "TRAIN", stale.split.train_start, stale.split.train_end
        )


def receipts_of(ledger, study):
    with ledger.engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT phase,range_start,range_end,holdout_state FROM research_read_receipt "
                "WHERE study_id=:id ORDER BY authorized_at,receipt_id"
            ),
            {"id": study.study_id},
        ).all()


def test_trial_race_exactly_one_and_global_overlapping_holdout_race(ledger):
    # Identical calendars never cross each other's holdout, so both may register.
    shared = unused_holdout_start()
    first = synthetic_study(oos_start=shared)
    second = synthetic_study(oos_start=shared)
    ledger.register(first)
    ledger.register(second)
    selected = one_per_family(first)
    for study in (first, second):
        validate_grid(ledger, study)
        freeze(ledger, study, selected)
    raced = data(ledger, first, first.configs[0], "TRAIN")

    def record(_):
        try:
            ledger.record(first.study_id, "raced", "TRAIN", first.configs[0].content_hash(), raced)
            return "INSERTED"
        except IntegrityError:
            return "DUPLICATE"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(record, range(2))) == ["DUPLICATE", "INSERTED"]

    def consume(study):
        try:
            ledger.open_holdout(study.study_id, selected)
            return "CONSUMED"
        except ValueError as error:
            assert "ALREADY_CONSUMED" in str(error)
            return "BLOCKED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(consume, (first, second))) == ["BLOCKED", "CONSUMED"]
    with ledger.engine.connect() as conn:
        assert (
            conn.scalar(
                text("SELECT count(*) FROM research_event WHERE study_id IN (:a,:b)"),
                {"a": first.study_id, "b": second.study_id},
            )
            == 1
        )


class SyntheticReader:
    def __init__(self, ledger):
        self.ledger, self.phases = ledger, []

    def read(self, study_id, phase, start, end):
        authorized = self.ledger.authorize_read(study_id, phase, start, end)
        self.phases.append(phase)
        bars = [b for b in prices(200, start) if b.end_at <= end]
        return ResearchRead(bars, self.ledger.bind_read(authorized, bars))


def test_worker_freezes_training_selection_before_consuming_synthetic_holdout(ledger):
    study = synthetic_study(configs=frozen_configs())
    ledger.register(study)
    reader = SyntheticReader(ledger)
    worker = ResearchWorker(ledger, reader)
    worker.development(study.study_id)
    assert "OOS" not in reader.phases
    assert sealed(ledger, study)
    frozen = ledger.read_trial(study.study_id, SELECTION_TRIAL)
    report = worker.holdout(study.study_id)
    assert reader.phases[-1] == "OOS"
    assert len(report) == 5 and report["BREAKOUT"]["screen"]["verdict"] == "INCONCLUSIVE"
    assert ledger.read_trial(study.study_id, SELECTION_TRIAL) == frozen
    assert ledger.holdout_state(study.study_id) == "COMPLETE"
    with ledger.engine.connect() as conn:
        assert ledger.selected(conn, study.study_id) == tuple(json.loads(frozen)["selected"])
        trials = dict(
            conn.execute(
                text("SELECT trial_id,phase FROM research_trial WHERE study_id=:id"),
                {"id": study.study_id},
            ).all()
        )
        completed = conn.scalar(
            text("SELECT trials FROM research_holdout_completion WHERE study_id=:id"),
            {"id": study.study_id},
        )
    # 37 development records (the duplicate validation fold is gone, RS-10), 15 holdout
    # results and the two hypothesis verdicts: 54 of 64.
    assert len(trials) == 54 <= study.trial_budget
    assert sorted(completed) == sorted(t for t, p in trials.items() if p == "OOS")
    assert {t: p for t, p in trials.items() if t.startswith("verdict.")} == {
        "verdict.BREAKOUT": "OOS",
        "verdict.MEAN_REVERSION": "OOS",
    }
    for family in ("BREAKOUT", "MEAN_REVERSION"):
        recorded = json.loads(ledger.read_trial(study.study_id, "verdict." + family))
        assert recorded["screen"] == json.loads(artifact_bytes(report[family]["screen"]))
        assert recorded["screen"]["verdict"] == "INCONCLUSIVE" and recorded["screen"]["reasons"]
        assert recorded["config_hash"] == report[family]["config_hash"]
        assert recorded["registered"] == {
            "seed": study.seed,
            "bootstrap_samples": study.bootstrap_samples,
            "bootstrap_block_days": study.bootstrap_block_days,
            "comparisons": study.comparisons,
            "max_drawdown": "0.2",
            "stress_multipliers": ["1", "1.5", "2"],
        }
        primary = json.loads(ledger.read_trial(study.study_id, f"oos.{family}.1"))
        assert recorded["screen"]["inputs"]["uncertainty"] == primary["uncertainty"]["14"]
    with pytest.raises(ValueError, match="ALREADY_CONSUMED"):
        worker.holdout(study.study_id)
    # Every authorized read was logged; a post-completion OOS read is logged as such.
    ledger.authorize_read(study.study_id, "OOS", study.split.oos_start, study.split.oos_end)
    logged = receipts_of(ledger, study)
    assert [r[0] for r in logged].count("OOS") == 2
    assert [r[3] for r in logged if r[0] == "OOS"] == ["OPEN", "COMPLETE"]
    assert all(r[3] == "SEALED" for r in logged if r[0] != "OOS")
    assert len(logged) == len(reader.phases) + 1


def test_interrupted_holdout_resumes_without_reopening_and_adds_only_missing_trials(
    ledger, monkeypatch
):
    study = synthetic_study(configs=frozen_configs())
    ledger.register(study)
    ResearchWorker(ledger, SyntheticReader(ledger)).development(study.study_id)
    original = ResearchLedger.record
    remaining = {"oos": 4}

    def crashing(self, study_id, trial_id, phase, *args, **kwargs):
        if phase == "OOS":
            if remaining["oos"] == 0:
                raise RuntimeError("simulated crash inside the holdout run")
            remaining["oos"] -= 1
        return original(self, study_id, trial_id, phase, *args, **kwargs)

    monkeypatch.setattr(ResearchLedger, "record", crashing)
    with pytest.raises(RuntimeError, match="simulated crash"):
        ResearchWorker(ledger, SyntheticReader(ledger)).holdout(study.study_id)
    monkeypatch.setattr(ResearchLedger, "record", original)
    assert ledger.holdout_state(study.study_id) == "OPEN"

    def oos_trials():
        with ledger.engine.connect() as conn:
            return dict(
                conn.execute(
                    text(
                        "SELECT trial_id,artifact_hash FROM research_trial "
                        "WHERE study_id=:id AND phase='OOS'"
                    ),
                    {"id": study.study_id},
                ).all()
            )

    before = oos_trials()
    assert len(before) == 4

    # Two resumers race: the trial key and the per-study lock keep every trial single, and
    # exactly one of them records the completion.
    def resume(_):
        try:
            ResearchWorker(ledger, SyntheticReader(ledger)).holdout(study.study_id)
            return "COMPLETED"
        except ValueError as error:
            assert str(error) in (
                "HOLDOUT_ALREADY_COMPLETE",
                "HOLDOUT_ALREADY_CONSUMED_AND_COMPLETE",
            )
            return "ALREADY_COMPLETE"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(resume, range(2)))
    after = oos_trials()
    assert outcomes == ["ALREADY_COMPLETE", "COMPLETED"] and len(after) == 17
    assert all(after[t] == digest for t, digest in before.items())
    with ledger.engine.connect() as conn:
        assert (
            conn.scalar(
                text("SELECT count(*) FROM research_event WHERE study_id=:id"),
                {"id": study.study_id},
            )
            == 1
        )
    assert ledger.holdout_state(study.study_id) == "COMPLETE"
    with pytest.raises(ValueError, match="^HOLDOUT_ALREADY_CONSUMED_AND_COMPLETE$"):
        ResearchWorker(ledger, SyntheticReader(ledger)).holdout(study.study_id)
    # A resumed trial that differs from what was recorded is refused, never overwritten.
    first = next(iter(before))
    with pytest.raises(ValueError, match="^HOLDOUT_RESUME_MISMATCH$"):
        ledger.record(
            study.study_id,
            first,
            "OOS",
            study.configs[0].content_hash(),
            b'{"different": true}',
            resume=True,
        )
