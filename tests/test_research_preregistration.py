import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from research_fixtures import synthetic_study

from auvexo_alpha.application.research_simulator import artifact_bytes
from auvexo_alpha.application.research_study import frozen_configs
from auvexo_alpha.infrastructure.research_ledger import ResearchLedger, frozen_selection

ROOT = Path(__file__).resolve().parents[1]
V1_SHA256 = "82d189d51b01457e8141455d02addafcdbd690e8a73f4f4996eefcc7fbd2b8a4"


def test_v1_immutable_v2_parent_and_evidence_extract_integrity():
    assert hashlib.sha256((ROOT / "docs/phase3/DATA_PLAN.md").read_bytes()).hexdigest() == V1_SHA256
    amendment = (ROOT / "docs/phase3/DATA_PLAN_V2.md").read_text(encoding="utf-8")
    assert V1_SHA256 in amendment
    evidence = json.loads(
        (ROOT / "docs/phase3/evidence/provider-outage-diagnosis.json").read_text(encoding="utf-8")
    )
    assert evidence["data_plan_v1_sha256"] == V1_SHA256
    assert evidence["oos_inspected_before_amendment"] is False
    assert evidence["archive_original_quality"] == "DEGRADED"
    for item in evidence["official_evidence"]:
        assert item["representation"] == "VERIFIED_FACT_EXTRACT"
        assert (
            hashlib.sha256(item["facts"].encode()).hexdigest()
            == (item["sha256_of_utf8_fact_extract"])
        )


def test_phase_gate_requires_seal_and_closes_development_after_consumption(monkeypatch):
    # Pure gate check; PostgreSQL persistence/race qualification is a separate required gate.
    ledger = object.__new__(ResearchLedger)
    study = SimpleNamespace(study_id="synthetic")
    monkeypatch.setattr(ledger, "selected", lambda conn, study_id: None)
    with pytest.raises(ValueError, match="HOLDOUT_NOT_OPEN"):
        ledger.check_phase(None, study, "OOS")
    for phase in ("TRAIN", "VALIDATION", "WALK_FORWARD"):
        ledger.check_phase(None, study, phase)
    monkeypatch.setattr(ledger, "selected", lambda conn, study_id: ("0" * 64,))
    ledger.check_phase(None, study, "OOS")
    for phase in ("TRAIN", "VALIDATION", "WALK_FORWARD"):
        with pytest.raises(ValueError, match="DEVELOPMENT_ALREADY_CONSUMED"):
            ledger.check_phase(None, study, phase)


def recorded_selection(selected):
    return artifact_bytes({"selected": selected, "stable": {}})


def test_frozen_selection_is_exactly_one_registered_config_per_family():
    configs = frozen_configs()
    hashes = [c.content_hash() for c in configs]
    # Grid order: NO_TRADE, PASSIVE, FIXED_RULE, BREAKOUT 72, BREAKOUT 168, MR 24, MR 72.
    one_each = [hashes[0], hashes[1], hashes[2], hashes[4], hashes[5]]
    assert frozen_selection(configs, recorded_selection(one_each)) == tuple(one_each)
    not_one_each = (
        hashes,  # the whole grid: both windows of each hypothesis family
        [*one_each, hashes[3]],  # a second breakout window
        one_each[:-1],  # no mean-reversion choice
        [*one_each[:-1], one_each[0]],  # a duplicate instead of the missing family
    )
    for chosen in not_one_each:
        with pytest.raises(ValueError, match="SELECTION_NOT_ONE_CONFIG_PER_FAMILY"):
            frozen_selection(configs, recorded_selection(chosen))
    for chosen in ([], [*one_each[:-1], "f" * 64], "0" * 64, [1, 2, 3, 4, 5], None):
        with pytest.raises(ValueError, match="UNREGISTERED_SELECTION"):
            frozen_selection(configs, recorded_selection(chosen))
    for artifact in (b"{}", b"[]", b'{"chosen":[]}'):
        with pytest.raises(ValueError, match="UNREGISTERED_SELECTION"):
            frozen_selection(configs, artifact)


class ScriptedConnection:
    """Answers each statement by its first matching SQL fragment and records what was asked.

    This exercises the ledger's control flow only; the SQL itself is qualified against real
    PostgreSQL by the integration suite.
    """

    def __init__(self, answers):
        self.answers, self.asked = answers, []

    def answer(self, statement, parameters=None):
        sql = str(statement)
        self.asked.append((sql, parameters))
        for fragment, value in self.answers.items():
            if fragment in sql:
                return value
        raise AssertionError("unscripted statement: " + sql)

    def execute(self, statement, parameters=None):
        value = self.answer(statement, parameters)
        return SimpleNamespace(one=lambda: value, all=lambda: value)

    def scalar(self, statement, parameters=None):
        return self.answer(statement, parameters)

    def scalars(self, statement, parameters=None):
        return iter(self.answer(statement, parameters))

    def parameters(self, fragment):
        return [parameters for sql, parameters in self.asked if fragment in sql]


def scripted_ledger(tmp_path, study, answers):
    conn = ScriptedConnection({"pg_advisory_xact_lock": None} | answers)

    @contextmanager
    def transaction():
        yield conn

    ledger = object.__new__(ResearchLedger)
    ledger.engine = SimpleNamespace(begin=transaction, connect=transaction)
    ledger.root = tmp_path.resolve()
    ledger.study = lambda study_id, conn=None: study
    return ledger, conn


SEALED_ELSEWHERE = "NOT EXISTS (SELECT 1 FROM research_event"
EXPOSED_ELSEWHERE = "{split,train_start}"
STORED_INPUTS = "FROM data_manifest"


def stored(study):
    return [(item.manifest.dataset_version, item.manifest_hash) for item in study.inputs]


def test_registration_checks_both_calendar_directions_before_inserting(tmp_path):
    study = synthetic_study()
    split = study.split
    insert = "INSERT INTO research_study VALUES"
    configs = "INSERT INTO research_study_config"
    present = {STORED_INPUTS: stored(study)}
    ledger, conn = scripted_ledger(tmp_path, study, present | {SEALED_ELSEWHERE: 1})
    with pytest.raises(ValueError, match="DEVELOPMENT_OVERLAPS_SEALED_HOLDOUT_OF_ANOTHER_STUDY"):
        ledger.register(study)
    assert conn.parameters(insert) == []
    assert conn.parameters(SEALED_ELSEWHERE)[0] | {"id": None, "instrument": None} == {
        "id": None,
        "instrument": None,
        "start": split.train_start,
        "end": split.validation_end,
    }
    ledger, conn = scripted_ledger(
        tmp_path, study, present | {SEALED_ELSEWHERE: 0, EXPOSED_ELSEWHERE: 1}
    )
    with pytest.raises(ValueError, match="HOLDOUT_OVERLAPS_DEVELOPMENT_OF_ANOTHER_STUDY"):
        ledger.register(study)
    assert conn.parameters(insert) == []
    assert conn.parameters(EXPOSED_ELSEWHERE) == [
        {
            "id": study.study_id,
            "instrument": study.instrument,
            "start": split.oos_start,
            "end": split.oos_end,
        }
    ]
    ledger, conn = scripted_ledger(
        tmp_path,
        study,
        present | {SEALED_ELSEWHERE: 0, EXPOSED_ELSEWHERE: 0, insert: None, configs: None},
    )
    ledger.register(study)
    assert [p["id"] for p in conn.parameters(insert)] == [study.study_id]
    # Every registered config becomes an index/family row the database gates rely on.
    assert [(p["i"], p["h"], p["f"]) for p in conn.parameters(configs)] == [
        (index, c.content_hash(), c.family) for index, c in enumerate(study.configs)
    ]


@pytest.mark.parametrize(
    "change,code",
    [
        ({"code_hash": "1" * 64}, "RESEARCH_CODE_HASH_MISMATCH"),
        ({"dependency_hash": "1" * 64}, "DEPENDENCY_LOCK_HASH_MISMATCH"),
    ],
)
def test_registration_refuses_a_study_not_bound_to_the_running_code_and_lock(
    tmp_path, change, code
):
    study = synthetic_study().model_copy(update=change)
    ledger, conn = scripted_ledger(tmp_path, study, {STORED_INPUTS: stored(study)})
    with pytest.raises(ValueError, match=f"^{code}$"):
        ledger.register(study)
    assert conn.parameters("INSERT") == []


@pytest.mark.parametrize("rows", ["missing", "other_hash"])
def test_registration_refuses_inputs_absent_from_or_different_in_the_store(tmp_path, rows):
    study = synthetic_study()
    answer = [] if rows == "missing" else [(v, "f" * 64) for v, _ in stored(study)]
    ledger, conn = scripted_ledger(tmp_path, study, {STORED_INPUTS: answer})
    with pytest.raises(ValueError, match="^STUDY_INPUT_NOT_IN_STORE$"):
        ledger.register(study)
    assert conn.parameters("INSERT") == []


@pytest.mark.parametrize(
    "code",
    [
        "HOLDOUT_NOT_OPEN_OR_DEVELOPMENT_ALREADY_CONSUMED",
        "READ_OUTSIDE_REGISTERED_SPLIT",
        "READ_OVERLAPS_SEALED_HOLDOUT_OF_ANOTHER_STUDY",
        None,
    ],
)
def test_reads_are_authorized_and_logged_by_the_database_gate_only(tmp_path, code):
    study = synthetic_study()
    split = study.split
    gate = "research_authorize_read"
    ledger, conn = scripted_ledger(tmp_path, study, {gate: code, STORED_INPUTS: stored(study)})
    with pytest.raises(ValueError, match=f"^{code or 'RESEARCH_GATE_FAILED'}$"):
        ledger.authorize_read(study.study_id, "TRAIN", split.train_start, split.train_end)
    (asked,) = conn.parameters(gate)
    assert (asked["phase"], asked["start"], asked["end"]) == (
        "TRAIN",
        split.train_start,
        split.train_end,
    )
    ledger, conn = scripted_ledger(
        tmp_path, study, {gate: "AUTHORIZED", STORED_INPUTS: stored(study)}
    )
    read = ledger.authorize_read(study.study_id, "TRAIN", split.train_start, split.train_end)
    assert read.study == study and read.receipt_id == conn.parameters(gate)[0]["receipt"]
    assert len(read.receipt_id) == 64


def test_holdout_opening_maps_the_database_gate_and_never_writes_the_event_itself(tmp_path):
    study = synthetic_study(configs=frozen_configs())
    hashes = [c.content_hash() for c in study.configs]
    frozen = [hashes[0], hashes[1], hashes[2], hashes[4], hashes[5]]
    gate = "research_open_holdout"
    for code in ("SELECTION_NOT_FROZEN_HOLDOUT_SEALED", "HOLDOUT_SELECTION_NOT_FROZEN"):
        ledger, conn = scripted_ledger(
            tmp_path, study, {"FROM research_selection": None, gate: code}
        )
        with pytest.raises(ValueError, match=f"^{code}$"):
            ledger.open_holdout(study.study_id, tuple(frozen))
        assert json.loads(conn.parameters(gate)[0]["selected"]) == frozen
    # The retained selection artifact must still agree with the database's frozen row.
    artifact = recorded_selection(frozen)
    digest = hashlib.sha256(artifact).hexdigest()
    (tmp_path / (digest + ".json")).write_bytes(recorded_selection(hashes))
    ledger, conn = scripted_ledger(
        tmp_path,
        study,
        {
            "FROM research_selection": frozen,
            "SELECT artifact_hash,artifact_bytes": (digest, len(artifact)),
        },
    )
    with pytest.raises(ValueError, match="CORRUPT_RESEARCH_ARTIFACT"):
        ledger.open_holdout(study.study_id, tuple(frozen))
    assert conn.parameters(gate) == []
    with pytest.raises(ValueError, match="UNREGISTERED_SELECTION"):
        ledger.open_holdout(study.study_id, ())


def test_ledger_source_never_writes_gate_records_directly():
    """HOLDOUT_OPEN, frozen selections, read receipts and completions come only from the
    reviewed SECURITY DEFINER functions; the research role holds no INSERT on them.
    """
    source = (ROOT / "src/auvexo_alpha/infrastructure/research_ledger.py").read_text()
    for table in (
        "research_event",
        "research_selection",
        "research_read_receipt",
        "research_holdout_completion",
    ):
        assert f"INSERT INTO {table}" not in source
