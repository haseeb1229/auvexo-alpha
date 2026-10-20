"""Application orchestration through fake ports only; no DB/provider dependencies."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from observation_fixtures import BEGIN, account_at, changed, fact_for, make_config, witness

from auvexo_alpha.application.observation_ports import (
    DecisionJournalEntry,
    ObservationRunStart,
    ObservationSnapshot,
    ObservationSourceUnavailable,
)
from auvexo_alpha.application.observation_qualification import evaluate_observation_day
from auvexo_alpha.application.observation_runner import ObservationRunner
from auvexo_alpha.domain.observation import ObservationResources, observation_release
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
    def __init__(self, config, clock):
        self.config, self.clock = config, clock
        self.facts_list, self.trace_list = [], []
        self.closed = None
        self.run_id = uuid4()

    def verify_schema(self):
        pass

    def begin(self, config_hash, *, kind, now):
        assert config_hash == self.config.content_hash() and kind == "PREFLIGHT"
        return self.run_id

    def started_run(self, run_id):
        return ObservationRunStart(BEGIN + timedelta(seconds=3))

    def pinned_release(self, config):
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
        self.closed = evidence
        return evaluate_observation_day(self.config, evidence, witness(evidence), now=now)


class FakePaper:
    def __init__(self, clock):
        self.clock, self.kill_calls = clock, []
        self.snapshots = {}

    def account(self, account_ref):
        if self.clock() not in self.snapshots:
            self.snapshots[self.clock()] = account_at(self.clock())
        return self.snapshots[self.clock()]

    def acquire_writer(self, account_ref, *, now):
        return 1

    def reconcile(self, account_ref, *, now):
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
    def __init__(self, clock, error=None):
        self.clock, self.error = clock, error

    def require_ready(self, config, *, now):
        config.rights.require_research(now)

    def next_observation(self, symbol, *, window_start, window_end):
        if self.error is not None:
            raise self.error
        minute = int((self.clock() - BEGIN).total_seconds()) // 60
        return fact_for(symbol, minute)


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


def make_runner(error=None):
    config, clock = make_config(), Clock()
    persistence, paper = FakePersistence(config, clock), FakePaper(clock)
    runner = ObservationRunner(
        config,
        persistence,
        paper,
        NoTruthMutation(),
        FakeFeed(clock, error),
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
    assert not paper.kill_calls and persistence.closed is not None


def test_expected_source_outage_closes_incomplete_without_inventing_truth():
    runner, persistence, _ = make_runner(ObservationSourceUnavailable("NETWORK"))
    receipt = runner.run(kind="PREFLIGHT")
    assert receipt.status == "INCOMPLETE" and receipt.paired_observations == 0
    assert "observation.feed.unavailable" in receipt.operational_reasons
    assert persistence.closed is not None


@pytest.mark.parametrize(
    "error",
    (ValueError("HASH_CORRUPT"), RuntimeError("IDENTITY_DENIED"), TypeError("PROGRAMMER_ERROR")),
)
def test_application_does_not_swallow_unexpected_security_or_corruption_failures(error):
    runner, persistence, _ = make_runner(error)
    with pytest.raises(type(error), match=str(error)):
        runner.run(kind="PREFLIGHT")
    assert persistence.closed is None
