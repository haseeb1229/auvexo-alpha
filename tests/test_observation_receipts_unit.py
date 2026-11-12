"""Receipt rights-at-recorded-time and PASS-refusal logic through fakes.

No database, provider or genuine evidence: synthetic NON_COUNTING fixtures only.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from observation_fixtures import BEGIN, END, changed, make_config, make_run, witness
from sqlalchemy.exc import DBAPIError

from auvexo_alpha.application.observation_qualification import evaluate_observation_day
from auvexo_alpha.infrastructure import observation_store
from auvexo_alpha.infrastructure.observation_store import (
    PASS_REFUSALS,
    ObservationStore,
    receipt_refusal_code,
    refused_evidence,
)
from auvexo_alpha.infrastructure.paper_truth import canonical_payload

# The pinned DS-02 record is valid on [2026-10-16T00:00Z, 2026-11-16T00:00Z).
EXPIRY = datetime(2026, 11, 16, tzinfo=UTC)
LAST_VALID_INSTANT = datetime(2026, 11, 15, 23, 59, 59, 999999, tzinfo=UTC)
AFTER_EXPIRY = datetime(2026, 11, 20, 9, tzinfo=UTC)
DATABASE = "auvexo_paperobs_" + "a" * 20


class LedgerEngine:
    """Read-only stand-in returning stored receipt rows and recording any write."""

    def __init__(self, rows=()):
        self.rows, self.writes = list(rows), []
        self.url = SimpleNamespace(database=DATABASE)

    def connect(self):
        return self

    def begin(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *failure):
        return False

    def execute(self, statement, parameters):
        if str(statement).lstrip().upper().startswith("INSERT"):
            self.writes.append(parameters)
        return self

    def mappings(self):
        return self

    def all(self):
        return self.rows


def detached_store(config, run, *, rows=(), replay=None):
    """An ObservationStore with no engine identity; only the logic under test is real."""
    store = object.__new__(ObservationStore)
    store.engine = LedgerEngine(rows)
    store.config = lambda config_hash: config
    store.run = lambda run_id: run
    store.verify_schema = lambda: None
    store.replayed = []

    def recorded_replay(run_id, run_row, pinned, evidence, *, now):
        store.replayed.append(evidence)
        return replay

    store._replay = recorded_replay
    return store


def test_rights_are_judged_at_the_receipt_recorded_instant_at_exact_boundaries():
    config = make_config()
    assert config.rights.review_due == EXPIRY
    ObservationStore._rights_when_recorded(config, LAST_VALID_INSTANT)
    ObservationStore._rights_when_recorded(config, datetime(2026, 10, 16, tzinfo=UTC))
    for refused in (EXPIRY, AFTER_EXPIRY, datetime(2026, 10, 15, 23, 59, 59, 999999, tzinfo=UTC)):
        with pytest.raises(ValueError, match="SOURCE_RIGHTS_BLOCKED_OR_EXPIRED"):
            ObservationStore._rights_when_recorded(config, refused)


def test_verify_is_current_and_strict_unless_given_a_stored_receipt_time():
    config, evidence, proof = make_run()
    store = detached_store(config, {"campaign_hash": config.content_hash()}, replay=proof)
    for now in (EXPIRY, AFTER_EXPIRY):
        with pytest.raises(ValueError, match="SOURCE_RIGHTS_BLOCKED_OR_EXPIRED"):
            store.verify(evidence.run_id, evidence, now=now)
    assert store.replayed == []
    assert store.verify(evidence.run_id, evidence, now=LAST_VALID_INSTANT) == proof
    # History after expiry: one microsecond before expiry verifies, the expiry instant never.
    assert (
        store.verify(evidence.run_id, evidence, now=AFTER_EXPIRY, recorded_at=LAST_VALID_INSTANT)
        == proof
    )
    with pytest.raises(ValueError, match="SOURCE_RIGHTS_BLOCKED_OR_EXPIRED"):
        store.verify(evidence.run_id, evidence, now=AFTER_EXPIRY, recorded_at=EXPIRY)
    assert len(store.replayed) == 2


def test_reading_history_neither_uses_nor_extends_a_renewed_registry_record(monkeypatch):
    config, evidence, proof = make_run()
    store = detached_store(config, {"campaign_hash": config.content_hash()}, replay=proof)
    renewed = changed(
        config.rights, version="review.2026-11-15.v2", review_due=datetime(2027, 1, 1, tzinfo=UTC)
    )
    monkeypatch.setattr(observation_store, "rights", lambda source_id: renewed)
    # The campaign's own pinned record still ends at its own expiry.
    with pytest.raises(ValueError, match="SOURCE_RIGHTS_BLOCKED_OR_EXPIRED"):
        store.verify(evidence.run_id, evidence, now=AFTER_EXPIRY, recorded_at=EXPIRY)
    assert (
        store.verify(evidence.run_id, evidence, now=AFTER_EXPIRY, recorded_at=LAST_VALID_INSTANT)
        == proof
    )
    # Starting or closing now remains pinned to the current registry record.
    with pytest.raises(ValueError, match="OBSERVATION_CURRENT_SOURCE_RIGHTS_MISMATCH"):
        store.verify(evidence.run_id, evidence, now=LAST_VALID_INSTANT)
    with pytest.raises(ValueError, match="OBSERVATION_CURRENT_SOURCE_RIGHTS_MISMATCH"):
        store.begin(config.content_hash(), kind="PREFLIGHT", now=LAST_VALID_INSTANT)
    assert store.engine.writes == []


@pytest.mark.parametrize("kind", ("PREFLIGHT", "SCHEDULED"))
def test_begin_still_requires_currently_valid_rights(kind):
    config = make_config()
    store = detached_store(config, None)
    store.activation = lambda config_hash: pytest.fail("rights precede activation lookup")
    for now in (EXPIRY, AFTER_EXPIRY):
        with pytest.raises(ValueError, match="SOURCE_RIGHTS_BLOCKED_OR_EXPIRED"):
            store.begin(config.content_hash(), kind=kind, now=now)
    assert store.engine.writes == []


def test_begin_one_microsecond_before_expiry_reaches_the_run_insert():
    config = make_config()
    store = detached_store(config, None)
    run_id = store.begin(config.content_hash(), kind="PREFLIGHT", now=LAST_VALID_INSTANT)
    assert [(w["id"], w["k"], w["now"]) for w in store.engine.writes] == [
        (str(run_id), "PREFLIGHT", LAST_VALID_INSTANT)
    ]


def scheduled_ledger(recorded_at):
    config, evidence, _ = make_run()
    evidence = changed(evidence, kind="SCHEDULED")
    proof = witness(evidence)
    receipt = evaluate_observation_day(config, evidence, proof, now=recorded_at)
    row = {
        "payload": canonical_payload(
            {"receipt": receipt, "evidence": evidence, "verification": proof}
        ),
        "run_id": str(evidence.run_id),
        "disposition": receipt.status,
        "local_date": BEGIN.date(),
        "campaign_hash": config.content_hash(),
        "recorded_at": recorded_at,
        "receipt_hash": receipt.content_hash(),
    }
    run = {
        "campaign_hash": config.content_hash(),
        "kind": "SCHEDULED",
        "database_name": DATABASE,
        "activation_id": "owner.start.synthetic",
    }
    store = detached_store(config, run, rows=[row], replay=proof)
    store.activation = lambda config_hash: {
        "database_name": DATABASE,
        "activation_id": "owner.start.synthetic",
        "reviewed_sha": config.git_revision,
        "activated_at": BEGIN - timedelta(days=1),
        "first_date": BEGIN.date(),
    }
    return config, store, receipt


def test_earned_dates_stay_readable_after_the_rights_review_date():
    recorded_at = datetime(2026, 10, 21, 17, 0, 5, tzinfo=UTC)
    config, store, receipt = scheduled_ledger(recorded_at)
    assert receipt.status == "PASS" and receipt.kind == "SCHEDULED"
    for now in (LAST_VALID_INSTANT, EXPIRY, AFTER_EXPIRY):
        summary = store.qualified_dates(config.content_hash(), now=now)
        assert summary.reasons == () and summary.qualified_dates == ("2026-10-21",)
        assert summary.qualified_count == 1 and summary.observation_started
    assert store.engine.writes == []


def test_a_stored_receipt_recorded_outside_its_pinned_rights_is_refused_not_counted():
    # A forged row dated at the expiry instant: neither the read nor a count is produced.
    config, store, _ = scheduled_ledger(EXPIRY)
    with pytest.raises(ValueError, match="SOURCE_RIGHTS_BLOCKED_OR_EXPIRED"):
        store.qualified_dates(config.content_hash(), now=AFTER_EXPIRY)
    assert store.replayed == []


class Refusal(Exception):
    """Shape of a driver error: SQLSTATE plus the primary message of a RAISE EXCEPTION."""

    def __init__(self, sqlstate, message):
        super().__init__(message)
        self.sqlstate = sqlstate
        self.diag = SimpleNamespace(message_primary=message)


@pytest.mark.parametrize("code", PASS_REFUSALS)
def test_only_the_two_pass_guard_refusals_are_named(code):
    assert PASS_REFUSALS == (
        "OBSERVATION_FINAL_STATE_OR_WINDOW_DENIED",
        "OBSERVATION_SOURCE_COVERAGE_DENIED",
    )
    assert receipt_refusal_code(DBAPIError("INSERT", {}, Refusal("P0001", code))) == code


@pytest.mark.parametrize(
    "cause",
    (
        Refusal("23505", "OBSERVATION_FINAL_STATE_OR_WINDOW_DENIED"),
        Refusal("P0001", "OBSERVATION_RECEIPT_RUN_BINDING_DENIED"),
        Refusal("P0001", "PREFLIGHT_OR_RESTORE_CANNOT_QUALIFY"),
        Refusal("P0001", "OBSERVATION_RUN_ALREADY_CLOSED"),
        Refusal("42501", "permission denied for table paper_observation_receipt"),
        RuntimeError("OBSERVATION_SOURCE_COVERAGE_DENIED"),
    ),
)
def test_any_other_database_failure_is_not_a_pass_refusal(cause):
    assert receipt_refusal_code(DBAPIError("INSERT", {}, cause)) is None


def test_refused_pass_evidence_replays_incomplete_and_unknown_codes_are_rejected():
    config, evidence, proof = make_run()
    assert evaluate_observation_day(config, evidence, proof, now=END).status == "PASS"
    refused = refused_evidence(evidence, "OBSERVATION_FINAL_STATE_OR_WINDOW_DENIED")
    reason = "observation.receipt.refused.OBSERVATION_FINAL_STATE_OR_WINDOW_DENIED"
    assert refused.operational_reasons == (reason,)
    assert refused.model_dump(exclude={"operational_reasons"}) == evidence.model_dump(
        exclude={"operational_reasons"}
    )
    receipt = evaluate_observation_day(config, refused, witness(refused), now=END)
    assert receipt.status == "INCOMPLETE" and receipt.reasons == (reason,)
    # The original witness does not cover the amended evidence.
    stale = evaluate_observation_day(config, refused, proof, now=END)
    assert stale.status == "INCOMPLETE"
    assert "VERIFICATION_OR_REPLAY_BINDING_INVALID" in stale.reasons
    with pytest.raises(ValueError, match="OBSERVATION_RECEIPT_REFUSAL_UNKNOWN"):
        refused_evidence(evidence, "ANYTHING_ELSE")
