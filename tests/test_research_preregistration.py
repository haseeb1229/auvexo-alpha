import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from auvexo_alpha.infrastructure.research_ledger import ResearchLedger

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
