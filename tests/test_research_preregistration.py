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
        return SimpleNamespace(one=lambda: value)

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
OWN_EVENT = "SELECT payload FROM research_event"


def test_development_reads_ask_whether_another_study_still_seals_the_range(tmp_path):
    study = synthetic_study()
    split = study.split
    ranges = {
        "TRAIN": (split.train_start, split.train_end),
        "VALIDATION": (split.validation_start, split.validation_end),
        "WALK_FORWARD": (split.train_start, split.validation_end),
    }
    for phase, (start, end) in ranges.items():
        ledger, conn = scripted_ledger(tmp_path, study, {OWN_EVENT: None, SEALED_ELSEWHERE: 1})
        with pytest.raises(ValueError, match="READ_OVERLAPS_SEALED_HOLDOUT_OF_ANOTHER_STUDY"):
            ledger.authorize_read(study.study_id, phase, start, end)
        assert conn.parameters(SEALED_ELSEWHERE) == [
            {"id": study.study_id, "instrument": study.instrument, "start": start, "end": end}
        ]
        ledger, conn = scripted_ledger(tmp_path, study, {OWN_EVENT: None, SEALED_ELSEWHERE: 0})
        assert ledger.authorize_read(study.study_id, phase, start, end) == study
    # The study's own opened holdout is read under its own consumption record instead.
    opened = artifact_bytes({"selected": ["0" * 64]}).decode()
    ledger, conn = scripted_ledger(tmp_path, study, {OWN_EVENT: opened})
    assert ledger.authorize_read(study.study_id, "OOS", split.oos_start, split.oos_end) == study
    assert conn.parameters(SEALED_ELSEWHERE) == []


def test_registration_checks_both_calendar_directions_before_inserting(tmp_path):
    study = synthetic_study()
    split = study.split
    insert = "INSERT INTO research_study"
    ledger, conn = scripted_ledger(tmp_path, study, {SEALED_ELSEWHERE: 1})
    with pytest.raises(ValueError, match="DEVELOPMENT_OVERLAPS_SEALED_HOLDOUT_OF_ANOTHER_STUDY"):
        ledger.register(study)
    assert conn.parameters(insert) == []
    assert conn.parameters(SEALED_ELSEWHERE)[0] | {"id": None, "instrument": None} == {
        "id": None,
        "instrument": None,
        "start": split.train_start,
        "end": split.validation_end,
    }
    ledger, conn = scripted_ledger(tmp_path, study, {SEALED_ELSEWHERE: 0, EXPOSED_ELSEWHERE: 1})
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
        tmp_path, study, {SEALED_ELSEWHERE: 0, EXPOSED_ELSEWHERE: 0, insert: None}
    )
    ledger.register(study)
    assert [p["id"] for p in conn.parameters(insert)] == [study.study_id]


def holdout_script(tmp_path, study, recorded):
    """A complete validation grid plus, optionally, one recorded selection artifact."""
    answers = {
        "SELECT config_hash FROM research_trial": [c.content_hash() for c in study.configs],
        "SELECT artifact_hash FROM research_trial": None,
        "JOIN research_study": 0,
        "INSERT INTO research_event": None,
    }
    if recorded is not None:
        artifact = recorded_selection(recorded)
        digest = hashlib.sha256(artifact).hexdigest()
        (tmp_path / (digest + ".json")).write_bytes(artifact)
        answers["SELECT artifact_hash FROM research_trial"] = digest
        answers["SELECT artifact_hash,artifact_bytes"] = (digest, len(artifact))
    return scripted_ledger(tmp_path, study, answers)


def test_holdout_opens_only_with_the_recorded_frozen_selection(tmp_path):
    study = synthetic_study(configs=frozen_configs())
    hashes = [c.content_hash() for c in study.configs]
    frozen = (hashes[0], hashes[1], hashes[2], hashes[4], hashes[5])
    event = "INSERT INTO research_event"
    ledger, conn = holdout_script(tmp_path, study, None)
    with pytest.raises(ValueError, match="SELECTION_NOT_FROZEN_HOLDOUT_SEALED"):
        ledger.open_holdout(study.study_id, frozen)
    assert conn.parameters(event) == []
    refused = (
        tuple(hashes),
        (hashes[0], hashes[1], hashes[2], hashes[3], hashes[6]),
        frozen[:-1],
        tuple(reversed(frozen)),
    )
    for attempt in refused:
        ledger, conn = holdout_script(tmp_path, study, frozen)
        with pytest.raises(ValueError, match="HOLDOUT_SELECTION_NOT_FROZEN"):
            ledger.open_holdout(study.study_id, attempt)
        assert conn.parameters(event) == []
    # A recorded whole-grid "selection" can never open the holdout, whatever is requested.
    for attempt in (tuple(hashes), frozen):
        ledger, conn = holdout_script(tmp_path, study, hashes)
        with pytest.raises(ValueError, match="SELECTION_NOT_ONE_CONFIG_PER_FAMILY"):
            ledger.open_holdout(study.study_id, attempt)
        assert conn.parameters(event) == []
    ledger, conn = holdout_script(tmp_path, study, frozen)
    ledger.open_holdout(study.study_id, frozen)
    (inserted,) = conn.parameters(event)
    assert json.loads(inserted["payload"]) == {
        "claim": "CONSUMED_BEFORE_READ",
        "selected": list(frozen),
        "selection_artifact": hashlib.sha256(recorded_selection(frozen)).hexdigest(),
    }
    # The frozen artifact is hash-verified inside the same transaction.
    ledger, conn = holdout_script(tmp_path, study, frozen)
    digest = hashlib.sha256(recorded_selection(frozen)).hexdigest()
    (tmp_path / (digest + ".json")).write_bytes(recorded_selection(hashes))
    with pytest.raises(ValueError, match="CORRUPT_RESEARCH_ARTIFACT"):
        ledger.open_holdout(study.study_id, frozen)
    assert conn.parameters(event) == []
