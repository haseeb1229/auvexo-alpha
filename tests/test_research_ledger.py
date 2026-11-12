import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from research_fixtures import prices, synthetic_study, unused_holdout_start
from sqlalchemy import URL, create_engine, event, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from test_postgres import connection_args

from auvexo_alpha.application.research_simulator import artifact_bytes
from auvexo_alpha.application.research_study import frozen_configs
from auvexo_alpha.domain.research import ResearchSplit
from auvexo_alpha.infrastructure.research_ledger import SELECTION_TRIAL, ResearchLedger
from auvexo_alpha.infrastructure.research_worker import ResearchWorker

pytestmark = pytest.mark.integration

DATA = artifact_bytes({"fixture": "SYNTHETIC_ONLY", "pnl": "0"})


@pytest.fixture
def ledger(tmp_path):
    args = connection_args()
    engine = create_engine(
        URL.create(
            "postgresql+psycopg",
            username=args["user"],
            password=args["password"],
            host=args["host"],
            port=args["port"],
            database=args["dbname"],
        ),
        hide_parameters=True,
    )

    @event.listens_for(engine, "connect")
    def role(connection, record):
        with connection.cursor() as cursor:
            cursor.execute("SET ROLE auvexo_research")

    try:
        yield ResearchLedger(engine, tmp_path / "artifacts", tmp_path)
    finally:
        engine.dispose()


def one_per_family(study, last=False):
    """The first (or last) registered config of each family, in grid order."""
    chosen = {}
    for cfg in study.configs:
        if last or cfg.family not in chosen:
            chosen[cfg.family] = cfg.content_hash()
    return tuple(chosen.values())


def validate_grid(ledger, study):
    for index, cfg in enumerate(study.configs):
        ledger.record(study.study_id, f"grid{index}", "VALIDATION", cfg.content_hash(), DATA)


def freeze(ledger, study, selected, phase="VALIDATION"):
    return ledger.record(
        study.study_id,
        SELECTION_TRIAL,
        phase,
        study.configs[0].content_hash(),
        artifact_bytes({"selected": selected}),
    )


def sealed(ledger, study):
    with ledger.engine.connect() as conn:
        return ledger.selected(conn, study.study_id) is None


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


def test_ledger_hashes_duplicates_seal_and_immutable_artifacts(ledger):
    study = synthetic_study(configs=frozen_configs())
    ledger.register(study)
    with pytest.raises(IntegrityError):
        ledger.register(study)
    cfg = study.configs[0].content_hash()
    selected = one_per_family(study)
    digest = ledger.record(study.study_id, "trial", "VALIDATION", cfg, DATA)
    assert ledger.path(digest).read_bytes() == DATA
    with pytest.raises(IntegrityError):
        ledger.record(study.study_id, "trial", "VALIDATION", cfg, DATA)
    with pytest.raises(ValueError, match="HOLDOUT_NOT_OPEN"):
        ledger.authorize_read(study.study_id, "OOS", study.split.oos_start, study.split.oos_end)
    with pytest.raises(ValueError, match="GRID_INCOMPLETE"):
        ledger.open_holdout(study.study_id, selected)
    for index, item in enumerate(study.configs[1:]):
        ledger.record(study.study_id, "grid" + str(index), "VALIDATION", item.content_hash(), DATA)
    frozen = freeze(ledger, study, selected)
    ledger.open_holdout(study.study_id, selected)
    with ledger.engine.connect() as conn:
        assert ledger.selected(conn, study.study_id) == selected
        payload = json.loads(
            conn.scalar(
                text("SELECT payload FROM research_event WHERE study_id=:id"),
                {"id": study.study_id},
            )
        )
    assert payload == {
        "claim": "CONSUMED_BEFORE_READ",
        "selected": list(selected),
        "selection_artifact": frozen,
    }
    with pytest.raises(ValueError, match="DEVELOPMENT_ALREADY_CONSUMED"):
        ledger.record(study.study_id, "post-oos", "VALIDATION", cfg, DATA)
    ledger.authorize_read(study.study_id, "OOS", study.split.oos_start, study.split.oos_end)
    unselected = next(c.content_hash() for c in study.configs if c.content_hash() not in selected)
    with pytest.raises(ValueError, match="POST_HOLDOUT_CONFIG"):
        ledger.record(study.study_id, "unselected", "OOS", unselected, DATA)
    ledger.path(digest).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="CORRUPT_RESEARCH_ARTIFACT"):
        ledger.record(study.study_id, "corrupt", "OOS", cfg, DATA)
    with pytest.raises(ValueError, match="CORRUPT_RESEARCH_ARTIFACT"):
        ledger.read_trial(study.study_id, "trial")


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
    for unselected in set(every) - set(frozen):
        with pytest.raises(ValueError, match="POST_HOLDOUT_CONFIG"):
            ledger.record(study.study_id, "late." + unselected[:8], "OOS", unselected, DATA)


@pytest.mark.parametrize("fault", ["whole_grid", "two_breakouts", "missing_family", "duplicate"])
def test_open_holdout_refuses_a_recorded_selection_not_one_config_per_family(ledger, fault):
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
    freeze(ledger, study, recorded)
    for attempt in (recorded, good):
        with pytest.raises(ValueError, match="SELECTION_NOT_ONE_CONFIG_PER_FAMILY"):
            ledger.open_holdout(study.study_id, attempt)
    assert sealed(ledger, study)


def test_open_holdout_verifies_the_frozen_selection_artifact_and_its_phase(ledger):
    tampered = synthetic_study(configs=frozen_configs())
    ledger.register(tampered)
    validate_grid(ledger, tampered)
    selected = one_per_family(tampered)
    digest = freeze(ledger, tampered, selected)
    ledger.path(digest).write_bytes(artifact_bytes({"selected": selected[:1]}))
    with pytest.raises(ValueError, match="CORRUPT_RESEARCH_ARTIFACT"):
        ledger.open_holdout(tampered.study_id, selected)
    assert sealed(ledger, tampered)
    # A selection recorded outside the validation phase was not frozen from validation.
    misfiled = synthetic_study(configs=frozen_configs())
    ledger.register(misfiled)
    validate_grid(ledger, misfiled)
    freeze(ledger, misfiled, selected, phase="TRAIN")
    with pytest.raises(ValueError, match="SELECTION_NOT_FROZEN_HOLDOUT_SEALED"):
        ledger.open_holdout(misfiled.study_id, selected)
    assert sealed(ledger, misfiled)
    # The selection record never counts as a validation result for the config it is filed
    # under: the first config below has no validation trial of its own until the last step.
    carrier = synthetic_study(configs=frozen_configs())
    ledger.register(carrier)
    for index, cfg in enumerate(carrier.configs[1:]):
        ledger.record(carrier.study_id, f"grid{index}", "VALIDATION", cfg.content_hash(), DATA)
    freeze(ledger, carrier, selected)
    with pytest.raises(ValueError, match="GRID_INCOMPLETE"):
        ledger.open_holdout(carrier.study_id, selected)
    assert sealed(ledger, carrier)
    first = carrier.configs[0].content_hash()
    ledger.record(carrier.study_id, "grid.first", "VALIDATION", first, DATA)
    ledger.open_holdout(carrier.study_id, selected)
    assert not sealed(ledger, carrier)


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
        ("WALK_FORWARD", reader.split.train_start, reader.split.validation_end),
    )
    for phase, lower, upper in overlapping:
        with pytest.raises(ValueError, match="READ_OVERLAPS_SEALED_HOLDOUT_OF_ANOTHER_STUDY"):
            ledger.authorize_read(reader.study_id, phase, lower, upper)
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
    cfg = study.configs[0].content_hash()
    ledger.quota = 1
    with pytest.raises(ValueError, match="STORAGE_PRESSURE"):
        ledger.record(study.study_id, "quota", "TRAIN", cfg, b"{}")
    assert not list(ledger.root.iterdir())
    ledger.quota = 512 * 1024 * 1024
    with monkeypatch.context() as patch:
        patch.setattr(
            "auvexo_alpha.infrastructure.research_ledger.pressure", lambda *args: "HARD_STOP"
        )
        with pytest.raises(ValueError, match="STORAGE_PRESSURE"):
            ledger.record(study.study_id, "pressure", "TRAIN", cfg, b"{}")
    assert not list(ledger.root.iterdir())
    ledger.record(study.study_id, "first", "TRAIN", cfg, b"{}")
    with pytest.raises(ValueError, match="TRIAL_BUDGET_EXHAUSTED"):
        ledger.record(study.study_id, "second", "TRAIN", cfg, b"{}")


def test_actual_role_denies_mutation_and_ingestion_or_policy_writes(ledger):
    ledger.register(synthetic_study())
    for table in ("research_study", "research_trial", "research_event"):
        for action in (f"DELETE FROM {table}", f"TRUNCATE {table}"):
            with pytest.raises(DBAPIError), ledger.engine.begin() as conn:
                conn.execute(text(action))
    for statement in (
        "UPDATE foundation_policy SET execution_enabled=true",
        "DELETE FROM data_manifest",
        "CREATE TABLE research_forbidden(x int)",
    ):
        with pytest.raises(DBAPIError), ledger.engine.begin() as conn:
            conn.execute(text(statement))


def test_trial_race_exactly_one_and_global_overlapping_holdout_race(ledger):
    # Identical calendars never cross each other's holdout, so both may register.
    shared = unused_holdout_start()
    first = synthetic_study(oos_start=shared)
    second = synthetic_study(oos_start=shared)
    ledger.register(first)
    ledger.register(second)
    cfg = first.configs[0].content_hash()
    selected = one_per_family(first)
    for study in (first, second):
        for index, item in enumerate(study.configs):
            ledger.record(
                study.study_id,
                "grid" + str(index),
                "VALIDATION",
                item.content_hash(),
                b'{"synthetic":true}',
            )
        freeze(ledger, study, selected)

    def record(_):
        try:
            ledger.record(first.study_id, "raced", "TRAIN", cfg, b'{"synthetic":true}')
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


def test_worker_freezes_training_selection_before_consuming_synthetic_holdout(ledger):
    study = synthetic_study(configs=frozen_configs())
    ledger.register(study)
    reads = []

    class SyntheticReader:
        def read(self, study_id, phase, start, end):
            ledger.authorize_read(study_id, phase, start, end)
            reads.append(phase)
            return prices(200, start)

    worker = ResearchWorker(ledger, SyntheticReader())
    worker.development(study.study_id)
    assert "OOS" not in reads
    assert sealed(ledger, study)
    frozen = ledger.read_trial(study.study_id, SELECTION_TRIAL)
    report = worker.holdout(study.study_id)
    assert reads[-1] == "OOS"
    assert len(report) == 5 and report["BREAKOUT"]["screen"]["verdict"] == "INCONCLUSIVE"
    assert ledger.read_trial(study.study_id, SELECTION_TRIAL) == frozen
    with ledger.engine.connect() as conn:
        assert ledger.selected(conn, study.study_id) == tuple(json.loads(frozen)["selected"])
        trials = dict(
            conn.execute(
                text("SELECT trial_id,phase FROM research_trial WHERE study_id=:id"),
                {"id": study.study_id},
            ).all()
        )
    # 44 development records, 15 holdout results and the two hypothesis verdicts: 61 of 64.
    assert len(trials) == 61 <= study.trial_budget
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
