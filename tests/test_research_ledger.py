from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from research_fixtures import config
from sqlalchemy import URL, create_engine, event, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from test_data_gates import observation_fixtures
from test_postgres import connection_args

from auvexo_alpha.application.research_simulator import artifact_bytes
from auvexo_alpha.domain.research import (
    CostModel,
    PriceAvailability,
    ResearchSplit,
    StudyManifest,
    classify_manifest,
)
from auvexo_alpha.infrastructure.research_ledger import ResearchLedger

pytestmark = pytest.mark.integration


def synthetic_study(study_id=None, oos_year=2040):
    now = datetime.now(UTC) - timedelta(seconds=1)
    _, _, manifests = observation_fixtures()
    m = manifests[0].model_copy(update={"created_at": now, "processed_at": now})
    coverage = m.coverage.model_copy(
        update={
            "requested_start": datetime(2024, 1, 1, tzinfo=UTC),
            "requested_end": datetime(2024, 1, 1, 1, tzinfo=UTC),
            "earliest": datetime(2024, 1, 1, tzinfo=UTC),
            "latest_end": datetime(2024, 1, 1, 1, tzinfo=UTC),
            "interval": "1h",
        }
    )
    m = m.model_copy(update={"coverage": coverage})
    policy = PriceAvailability(lag_microseconds=1_000_000)
    return StudyManifest(
        study_id=study_id or "synthetic." + uuid4().hex,
        version="fixture.v1",
        registered_at=now,
        instrument="binance.spot.BTCUSDT",
        hypotheses=("SYNTHETIC_A", "SYNTHETIC_B"),
        mechanism_and_falsification="Synthetic PostgreSQL control fixture; no empirical result.",
        inputs=(classify_manifest(m, now, policy),),
        availability=policy,
        configs=tuple(config(f) for f in ("NO_TRADE", "PASSIVE", "FIXED_RULE", "BREAKOUT")),
        costs=CostModel(),
        stress_multipliers=("1", "1.5", "2"),
        split=ResearchSplit(
            train_start=datetime(2022, 1, 1, tzinfo=UTC),
            train_end=datetime(2024, 1, 1, tzinfo=UTC),
            validation_start=datetime(2024, 1, 3, tzinfo=UTC),
            validation_end=datetime(oos_year, 1, 1, tzinfo=UTC),
            oos_start=datetime(oos_year, 1, 3, tzinfo=UTC),
            oos_end=datetime(oos_year + 1, 1, 1, tzinfo=UTC),
            purge_embargo_seconds=172800,
        ),
        seed=1229,
        code_revision="synthetic-control-only",
        code_hash="0" * 64,
        dependency_hash="0" * 64,
        data_plan_v1_hash="0" * 64,
        data_plan_v2_hash="0" * 64,
        baseline_families=("NO_TRADE", "PASSIVE", "FIXED_RULE"),
        parameter_budget=4,
        trial_budget=64,
        max_drawdown="0.2",
    )


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


def test_ledger_hashes_duplicates_seal_and_immutable_artifacts(ledger):
    study = synthetic_study(oos_year=2100 + uuid4().int % 500)
    ledger.register(study)
    with pytest.raises(IntegrityError):
        ledger.register(study)
    cfg = study.configs[0].content_hash()
    data = artifact_bytes({"fixture": "SYNTHETIC_ONLY", "pnl": "0"})
    digest = ledger.record(study.study_id, "trial", "VALIDATION", cfg, data)
    assert ledger.path(digest).read_bytes() == data
    with pytest.raises(IntegrityError):
        ledger.record(study.study_id, "trial", "VALIDATION", cfg, data)
    with pytest.raises(ValueError, match="HOLDOUT_NOT_OPEN"):
        ledger.authorize_read(study.study_id, "OOS", study.split.oos_start, study.split.oos_end)
    with pytest.raises(ValueError, match="GRID_INCOMPLETE"):
        ledger.open_holdout(study.study_id, (cfg,))
    for index, item in enumerate(study.configs[1:]):
        ledger.record(study.study_id, "grid" + str(index), "VALIDATION", item.content_hash(), data)
    ledger.open_holdout(study.study_id, (cfg,))
    with pytest.raises(ValueError, match="DEVELOPMENT_ALREADY_CONSUMED"):
        ledger.record(study.study_id, "post-oos", "VALIDATION", cfg, data)
    ledger.authorize_read(study.study_id, "OOS", study.split.oos_start, study.split.oos_end)
    with pytest.raises(ValueError, match="POST_HOLDOUT_CONFIG"):
        ledger.record(study.study_id, "unselected", "OOS", study.configs[1].content_hash(), data)
    ledger.path(digest).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="CORRUPT_RESEARCH_ARTIFACT"):
        ledger.record(study.study_id, "corrupt", "OOS", cfg, data)


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
    year = 2700 + uuid4().int % 300
    first = synthetic_study(oos_year=year)
    second = synthetic_study(oos_year=year)
    ledger.register(first)
    ledger.register(second)
    cfg = first.configs[0].content_hash()
    for study in (first, second):
        for index, item in enumerate(study.configs):
            ledger.record(
                study.study_id,
                "grid" + str(index),
                "VALIDATION",
                item.content_hash(),
                b'{"synthetic":true}',
            )

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
            ledger.open_holdout(study.study_id, (cfg,))
            return "CONSUMED"
        except ValueError as error:
            assert "ALREADY_CONSUMED" in str(error)
            return "BLOCKED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(consume, (first, second))) == ["BLOCKED", "CONSUMED"]


def test_worker_freezes_training_selection_before_consuming_synthetic_holdout(ledger):
    from research_fixtures import prices

    from auvexo_alpha.application.research_study import frozen_configs
    from auvexo_alpha.infrastructure.research_worker import ResearchWorker

    study = synthetic_study(oos_year=3100 + uuid4().int % 500).model_copy(
        update={
            "configs": frozen_configs(),
            "parameter_budget": 7,
        }
    )
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
    with ledger.engine.connect() as conn:
        assert ledger.selected(conn, study.study_id) is None
    frozen = ledger.read_trial(study.study_id, "selection.pre_holdout")
    report = worker.holdout(study.study_id)
    assert reads[-1] == "OOS"
    assert len(report) == 5 and report["BREAKOUT"]["screen"]["verdict"] == "INCONCLUSIVE"
    assert ledger.read_trial(study.study_id, "selection.pre_holdout") == frozen
    with pytest.raises(ValueError, match="ALREADY_CONSUMED"):
        worker.holdout(study.study_id)
