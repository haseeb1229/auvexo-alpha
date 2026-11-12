"""Application orchestration through fake ports only; no DB/provider dependencies."""

import re
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from observation_fixtures import BEGIN, END, account_at, changed, fact_for, make_config, witness

from auvexo_alpha.application.observation_ports import (
    DecisionJournalEntry,
    ObservationRunStart,
    ObservationSnapshot,
    ObservationSourceUnavailable,
)
from auvexo_alpha.application.observation_qualification import (
    evaluate_observation_day,
    observation_ledger_tail,
    summarize_observation_days,
)
from auvexo_alpha.application.observation_runner import ObservationRunner, failure_reason
from auvexo_alpha.domain.observation import (
    ObservationLedgerProof,
    ObservationResources,
    observation_release,
)
from auvexo_alpha.domain.paper_lifecycle import KillLevel
from auvexo_alpha.domain.paper_risk import assess_paper


class Clock:
    def __init__(self):
        self.now = BEGIN + timedelta(seconds=3)

    def __call__(self):
        return self.now

    def is_set(self):
        return False

    def wait(self, seconds):
        self.now += timedelta(minutes=1)
        return False


class FakePersistence:
    """Records every close attempt; `close_errors` are raised by successive attempts."""

    def __init__(self, config, clock, *, kind="PREFLIGHT", close_errors=(), release_error=None):
        self.config, self.clock, self.kind = config, clock, kind
        self.facts_list, self.trace_list = [], []
        self.close_calls, self.receipts = [], []
        self.close_errors, self.release_error = list(close_errors), release_error
        self.run_id = uuid4()

    def verify_schema(self):
        pass

    def begin(self, config_hash, *, kind, now):
        assert config_hash == self.config.content_hash() and kind == self.kind
        return self.run_id

    def started_run(self, run_id):
        return ObservationRunStart(BEGIN + timedelta(seconds=3))

    def pinned_release(self, config):
        if self.release_error is not None:
            raise self.release_error
        return observation_release(config, now=BEGIN)

    def append_feed(self, run_id, fact, *, now):
        self.facts_list.append(fact)
        return fact.content_hash()

    def append_trace(self, run_id, trace, *, now):
        self.trace_list.append(trace)
        return trace.content_hash()

    def feeds(self, run_id):
        return tuple(self.facts_list)

    def traces(self, run_id):
        return tuple(self.trace_list)

    def simulations(self, run_id):
        return ()

    def run_snapshot(self, run_id):
        return ObservationSnapshot(account_at(self.clock()), 0, "1" * 64, (), (), (), (), ())

    def close(self, run_id, evidence, *, now):
        self.close_calls.append(evidence)
        if self.close_errors:
            raise self.close_errors.pop(0)
        receipt = evaluate_observation_day(self.config, evidence, witness(evidence), now=now)
        self.receipts.append(receipt)
        return receipt


class FakePaper:
    def __init__(self, clock):
        self.clock, self.kill_calls = clock, []
        self.snapshots = {}
        self.acquired = self.reconciles = 0

    def account(self, account_ref):
        if self.clock() not in self.snapshots:
            self.snapshots[self.clock()] = account_at(self.clock())
        return self.snapshots[self.clock()]

    def acquire_writer(self, account_ref, *, now):
        self.acquired += 1
        return 1

    def reconcile(self, account_ref, *, now):
        self.reconciles += 1
        return True

    def reservations(self, account_ref):
        return ()

    def set_kill(self, account_ref, level, *, actor, now):
        self.kill_calls.append(level)

    def authorize(self, intent, policy, market, spec, release, *, now):
        decision = assess_paper(
            intent, policy, market, spec, self.account(intent.account_ref), release, (), now=now
        )
        assert decision.status == "DENIED"
        self.last = DecisionJournalEntry("DENIED", decision.content_hash())
        return SimpleNamespace(
            decision=changed(decision, exposure=None), authorization=None, reservation=None
        )

    def last_decision(self, account_ref):
        return self.last


class FakeFeed:
    """`missed` names (symbol, minute) bars the feed could not prove final: it returns None."""

    def __init__(self, clock, error=None, missed=()):
        self.clock, self.error, self.missed = clock, error, set(missed)

    def require_ready(self, config, *, now):
        config.rights.require_research(now)

    def next_observation(self, symbol, *, window_start, window_end):
        if self.error is not None:
            raise self.error
        minute = int((self.clock() - BEGIN).total_seconds()) // 60
        return None if (symbol, minute) in self.missed else fact_for(symbol, minute)


class FakeSimulator:
    def recover_pending(self, account_ref, *, epoch, now):
        return ()

    def observe(self, fact, *, now):
        return ()

    def accept(self, *args, **kwargs):
        pytest.fail("Denied proposal must never reach simulated order acceptance")


class NoTruthMutation:
    def mark(self, *args, **kwargs):
        pytest.fail("Flat fixture must not invent a position mark")


def make_runner(error=None, *, missed=(), kind="PREFLIGHT", close_errors=(), release_error=None):
    config, clock = make_config(), Clock()
    persistence = FakePersistence(
        config, clock, kind=kind, close_errors=close_errors, release_error=release_error
    )
    paper = FakePaper(clock)
    runner = ObservationRunner(
        config,
        persistence,
        paper,
        NoTruthMutation(),
        FakeFeed(clock, error, missed),
        simulator=FakeSimulator(),
        clock=clock,
        cancel=clock,
        resources=lambda now: ObservationResources(
            observed_at=now,
            available_ram_bytes=4_000_000_000,
            cpu_percent="0",
            cpu_high_for_seconds=0,
        ),
        pause_optional_research=lambda: True,
    )
    return runner, persistence, paper


def test_runner_completes_synthetic_day_through_ports_without_owner_resume_or_truth_mutation():
    runner, persistence, paper = make_runner()
    receipt = runner.run(kind="PREFLIGHT")
    assert receipt.status == "PASS" and receipt.kind == "NON_COUNTING"
    assert receipt.paired_observations == 60 and receipt.proposal_count > 0
    assert receipt.denial_count == receipt.proposal_count and receipt.fill_count == 0
    assert not paper.kill_calls and len(persistence.close_calls) == 1
    assert persistence.close_calls[0].operational_reasons == ()


def test_expected_source_outage_closes_incomplete_without_inventing_truth():
    runner, persistence, _ = make_runner(ObservationSourceUnavailable("NETWORK"))
    receipt = runner.run(kind="PREFLIGHT")
    assert receipt.status == "INCOMPLETE" and receipt.paired_observations == 0
    assert "observation.feed.unavailable" in receipt.operational_reasons
    assert len(persistence.close_calls) == 1


def test_one_missed_bar_is_never_an_observation_and_does_not_end_the_run():
    runner, persistence, paper = make_runner(missed={("BTCUSDT", 23)})
    receipt = runner.run(kind="PREFLIGHT")
    # Minute 23 has no BTC fact and no pair; the 22 -> 24 pair gap is exactly 120 s.
    assert len(persistence.facts_list) == 119
    assert receipt.paired_observations == 59 and receipt.max_gap_seconds == 120
    assert receipt.status == "PASS" and not paper.kill_calls
    assert receipt.last_observation_at == BEGIN + timedelta(minutes=59)
    assert receipt.ended_at >= END


def test_two_consecutive_missed_bars_trip_the_unchanged_gap_rule_but_the_run_finishes():
    runner, persistence, paper = make_runner(missed={("BTCUSDT", 23), ("ETHUSDT", 24)})
    receipt = runner.run(kind="PREFLIGHT")
    assert receipt.paired_observations == 58 and receipt.max_gap_seconds == 180
    assert receipt.status == "INCOMPLETE"
    assert "observation.feed.gap" in receipt.operational_reasons
    assert "OBSERVATION_GAP" in receipt.reasons
    assert paper.kill_calls == [KillLevel.K1]
    assert receipt.last_observation_at == BEGIN + timedelta(minutes=59)
    assert receipt.ended_at >= END and len(persistence.close_calls) == 1


@pytest.mark.parametrize(
    "error",
    (ValueError("HASH_CORRUPT"), RuntimeError("IDENTITY_DENIED"), TypeError("PROGRAMMER_ERROR")),
)
def test_failure_after_begin_propagates_and_leaves_exactly_one_incomplete_receipt(error):
    runner, persistence, paper = make_runner(error)
    with pytest.raises(type(error), match=str(error)) as caught:
        runner.run(kind="PREFLIGHT")
    assert caught.value is error
    reason = "observation.run.failed." + type(error).__name__ + "." + str(error)
    assert len(persistence.close_calls) == 1
    assert persistence.close_calls[0].operational_reasons == (reason,)
    assert [r.status for r in persistence.receipts] == ["INCOMPLETE"]
    assert reason in persistence.receipts[0].reasons
    assert persistence.receipts[0].paired_observations == 0
    assert paper.acquired == 1 and not paper.kill_calls


def test_failure_before_the_writer_fence_still_closes_incomplete_without_reconciling():
    error = ValueError("OBSERVATION_RELEASE_PIN_MISMATCH")
    runner, persistence, paper = make_runner(release_error=error)
    with pytest.raises(ValueError, match="OBSERVATION_RELEASE_PIN_MISMATCH"):
        runner.run(kind="PREFLIGHT")
    assert paper.acquired == 0 and paper.reconciles == 0
    assert len(persistence.close_calls) == 1
    assert persistence.close_calls[0].operational_reasons == (
        "observation.run.failed.ValueError.OBSERVATION_RELEASE_PIN_MISMATCH",
    )
    assert [r.status for r in persistence.receipts] == ["INCOMPLETE"]


def test_pass_refused_by_the_store_is_recorded_incomplete_and_can_never_count():
    refusal = RuntimeError("OBSERVATION_FINAL_STATE_OR_WINDOW_DENIED")
    runner, persistence, _ = make_runner(kind="SCHEDULED", close_errors=[refusal])
    with pytest.raises(RuntimeError, match="OBSERVATION_FINAL_STATE_OR_WINDOW_DENIED") as caught:
        runner.run(kind="SCHEDULED")
    assert caught.value is refusal
    refused, recorded = persistence.close_calls
    # The first attempt was a genuine application PASS that the store refused.
    would_pass = evaluate_observation_day(
        persistence.config, refused, witness(refused), now=refused.ended_at
    )
    assert would_pass.status == "PASS" and would_pass.kind == "SCHEDULED"
    reason = "observation.run.failed.RuntimeError.OBSERVATION_FINAL_STATE_OR_WINDOW_DENIED"
    assert recorded.operational_reasons == (reason,)
    assert recorded.facts == refused.facts and recorded.traces == refused.traces
    assert [r.status for r in persistence.receipts] == ["INCOMPLETE"]
    receipt = persistence.receipts[0]
    assert receipt.kind == "SCHEDULED" and reason in receipt.reasons

    def credit(day_receipt):
        proof = ObservationLedgerProof(
            campaign_id=persistence.config.campaign_id,
            activated_at=BEGIN - timedelta(days=1),
            first_eligible_day=BEGIN.date().isoformat(),
            verified_at=END + timedelta(hours=1),
            receipt_hashes=(day_receipt.content_hash(),),
            ledger_tail_hash=observation_ledger_tail((day_receipt,)),
        )
        return summarize_observation_days((day_receipt,), proof, now=END + timedelta(hours=1))

    # Control: the same ledger shape credits a PASS, and gives the refused date nothing.
    assert credit(would_pass).qualified_dates == (BEGIN.date().isoformat(),)
    summary = credit(receipt)
    assert summary.reasons == () and summary.qualified_count == 0
    assert summary.qualified_dates == ()


def test_failure_of_the_incomplete_write_itself_surfaces_with_the_original_as_context():
    original = ValueError("HASH_CORRUPT")
    write_failure = RuntimeError("LEDGER_WRITE_FAILED")
    runner, persistence, _ = make_runner(original, close_errors=[write_failure])
    with pytest.raises(RuntimeError, match="LEDGER_WRITE_FAILED") as caught:
        runner.run(kind="PREFLIGHT")
    assert caught.value is write_failure and caught.value.__context__ is original
    assert len(persistence.close_calls) == 1 and persistence.receipts == []


@pytest.mark.parametrize(
    "error,expected",
    (
        (ValueError("HASH_CORRUPT"), "observation.run.failed.ValueError.HASH_CORRUPT"),
        (
            ValueError("C:\\Users\\owner\\.local password=hunter2"),
            "observation.run.failed.ValueError",
        ),
        (RuntimeError("select * from paper_account"), "observation.run.failed.RuntimeError"),
        (KeyError("HASH_CORRUPT"), "observation.run.failed.KeyError"),
        (OSError(13, "Permission denied"), "observation.run.failed.PermissionError"),
    ),
)
def test_failure_reason_carries_only_the_type_and_a_stable_code(error, expected):
    assert failure_reason(error) == expected


def test_failure_reason_is_always_a_valid_bounded_label():
    longest = type("X" * 80, (ValueError,), {})("A" * 64)
    reason = failure_reason(longest)
    assert len(reason) == 96 and reason.startswith("observation.run.failed.XXXX")
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}", reason)
