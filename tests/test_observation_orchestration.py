"""Campaign v2 orchestration through fake ports only; no DB/provider dependencies."""

import re
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from observation_fixtures import (
    BEGIN,
    END,
    account_at,
    changed,
    clock_gate,
    clock_proof,
    fact_for,
    make_config,
    make_config_v2,
    spec_check,
    witness,
)

from auvexo_alpha.application.observation_ports import (
    DecisionJournalEntry,
    JournalFact,
    ObservationRunStart,
    ObservationSnapshot,
    ObservationSourceUnavailable,
    StandingAuthorityRecord,
)
from auvexo_alpha.application.observation_qualification import (
    evaluate_observation_day,
    observation_ledger_tail,
    summarize_observation_days,
)
from auvexo_alpha.application.observation_runner import ObservationRunner, failure_reason
from auvexo_alpha.domain.observation import (
    ObservationLedgerProof,
    ObservationProvenance,
    ObservationResources,
    ObservationStandingResume,
    observation_release,
)
from auvexo_alpha.domain.paper import PaperReservation, bind_authorization
from auvexo_alpha.domain.paper_lifecycle import KillLevel
from auvexo_alpha.domain.paper_risk import assess_paper

START_RESUME = "5" * 64
ACTIVATION = "owner.start.synthetic"
TICK = timedelta(milliseconds=100)


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


def authority(config, **changes):
    value = ObservationStandingResume(
        campaign_hash=config.content_hash(),
        reviewed_sha=config.git_revision,
        start_resume_event_hash=START_RESUME,
        valid_through="2026-12-31",
        owner="owner.founder",
    )
    value = changed(value, **changes) if changes else value
    return StandingAuthorityRecord(ACTIVATION, value, value.content_hash())


class FakePersistence:
    """Records every close attempt; `close_errors` are raised by successive attempts."""

    def __init__(self, config, clock, paper, *, kind, close_errors=(), release_error=None):
        self.config, self.clock, self.kind, self.paper = config, clock, kind, paper
        self.facts_list, self.trace_list = [], []
        self.close_calls, self.receipts = [], []
        self.close_errors, self.release_error = list(close_errors), release_error
        self.run_id = uuid4()
        self.authority = authority(config)
        self.activation = ACTIVATION if kind == "SCHEDULED" else None
        self.prior = None

    def verify_schema(self):
        pass

    def begin(self, config_hash, *, kind, now):
        assert config_hash == self.config.content_hash() and kind == self.kind
        return self.run_id

    def started_run(self, run_id):
        return ObservationRunStart(BEGIN + timedelta(seconds=3), BEGIN.date().isoformat())

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

    def run_activation(self, run_id):
        return self.activation

    def standing_authority(self, config_hash):
        return self.authority

    def prior_run(self, run_id):
        return self.prior

    def run_snapshot(self, run_id):
        approved = tuple(t for t in self.trace_list if t.reservation is not None)
        return ObservationSnapshot(
            account_at(self.clock(), kill=self.paper.kill),
            0,
            "1" * 64,
            tuple(t.reservation.content_hash() for t in approved),
            tuple(sha256(t.intent.content_hash().encode()).hexdigest() for t in approved),
            (),
            (),
            (),
            day_roll_hash=self.paper.roll_hash,
            terminal_authorization_count=len(approved),
            ledger_mismatch_count=self.paper.mismatches,
        )

    def close(self, run_id, evidence, *, now):
        self.close_calls.append(evidence)
        if self.close_errors:
            raise self.close_errors.pop(0)
        receipt = evaluate_observation_day(self.config, evidence, witness(evidence), now=now)
        self.receipts.append(receipt)
        return receipt


class FakePaper:
    """Kernel stand-in: the writer acquisition sets K1; only a standing resume clears it."""

    def __init__(self, clock, events, *, roll_error=None, mismatches=0):
        self.clock, self.events = clock, events
        self.kill_calls, self.snapshots = [], {}
        self.acquired = self.reconciles = 0
        self.kill = KillLevel.K0
        self.roll_error, self.mismatches = roll_error, mismatches
        self.roll_hash = None
        self.resumes = []
        self.journal = [
            JournalFact(
                "OWNER_PAPER_RESUME",
                START_RESUME,
                BEGIN - timedelta(days=1),
                account_at(BEGIN - timedelta(days=1), kill=KillLevel.K0),
            )
        ]

    def _journal(self, kind):
        fact = JournalFact(
            kind, uuid4().hex * 2, self.clock(), account_at(self.clock(), kill=self.kill)
        )
        self.journal.append(fact)
        return fact

    def account(self, account_ref):
        key = (self.clock(), self.kill)
        if key not in self.snapshots:
            self.snapshots[key] = account_at(self.clock(), kill=self.kill)
        return self.snapshots[key]

    def acquire_writer(self, account_ref, *, now):
        self.acquired += 1
        self.kill = max(self.kill, KillLevel.K1)
        self.events.append("acquire")
        self._journal("WRITER_ACQUIRED_PAUSE_NEW")
        return 1

    def reconcile(self, account_ref, *, now):
        self.reconciles += 1
        self.events.append("reconcile")
        self._journal("RECONCILIATION")
        return True

    def roll_flat_boundary(self, account_ref, *, now):
        self.events.append("roll")
        if self.roll_error is not None:
            self.kill = max(self.kill, KillLevel.K1)
            raise self.roll_error
        self.roll_hash = self._journal("FLAT_BOUNDARY_ROLL").content_hash

    def journal_facts(self, account_ref):
        return tuple(self.journal)

    def ledger_mismatch_count(self, account_ref):
        return self.mismatches

    def standing_resume(self, account_ref, use, *, actor, now):
        assert self.kill == KillLevel.K1 and use.journal_tail_hash == self.journal[-1].content_hash
        self.events.append("standing_resume")
        self.resumes.append((use, actor))
        self.kill = KillLevel.K0

    def reservations(self, account_ref):
        return ()

    def set_kill(self, account_ref, level, *, actor, now):
        self.kill_calls.append(level)
        self.kill = max(self.kill, level)

    def authorize(self, intent, policy, market, spec, release, *, now):
        account = self.account(intent.account_ref)
        decision = assess_paper(intent, policy, market, spec, account, release, (), now=now)
        if decision.status == "DENIED":
            self.last = DecisionJournalEntry("DENIED", decision.content_hash())
            return SimpleNamespace(
                decision=changed(decision, exposure=None), authorization=None, reservation=None
            )
        exposure = decision.exposure
        reservation = PaperReservation(
            reservation_id=uuid4(),
            intent_hash=intent.content_hash(),
            intent_id=intent.intent_id,
            logical_key=intent.logical_key,
            account_ref=intent.account_ref,
            instrument_id=intent.instrument_id,
            bucket=exposure.bucket,
            action=intent.action,
            quantity=exposure.quantity,
            notional=exposure.notional,
            modeled_loss=exposure.modeled_loss,
            margin=exposure.margin_required,
            created_at=now,
            expires_at=intent.expires_at,
        )
        authorization = bind_authorization(
            decision, intent, account, reservation.reservation_id, uuid4(), now
        )
        self.last = DecisionJournalEntry("AUTHORIZED", authorization.content_hash())
        return SimpleNamespace(
            decision=decision, authorization=authorization, reservation=reservation
        )

    def last_decision(self, account_ref):
        return self.last


class FakeTruth:
    def __init__(self, events):
        self.events, self.marks, self.specs = events, [], []

    def mark(self, account_ref, market, *, now):
        self.events.append("mark")
        self.marks.append(market)

    def observe_spec(self, account_ref, spec, *, now):
        assert spec.observed_at <= now
        self.events.append("observe_spec")
        self.specs.append(spec)


class FakeFeed:
    """`missed` names (symbol, minute) bars the feed could not prove final: it returns None."""

    def __init__(self, clock, error=None, missed=()):
        self.clock, self.error, self.missed = clock, error, set(missed)
        self.polls = 0

    def require_ready(self, config, *, now):
        config.rights.require_research(now)

    def next_observation(self, symbol, *, window_start, window_end):
        self.polls += 1
        if self.error is not None:
            raise self.error
        minute = int((self.clock() - BEGIN).total_seconds()) // 60
        return None if (symbol, minute) in self.missed else fact_for(symbol, minute)


class FakeGates:
    """Each provider measurement happens after the run start, on the advancing clock."""

    def __init__(self, clock, *, provenance="VERIFIED", windows=None, offset_ms=0, specs=None):
        self.time, self.provenance_status, self.windows = clock, provenance, windows
        self.offset_ms, self.spec_changes = offset_ms, specs or {}

    def provenance(self, *, window_start, window_end):
        assert window_end - window_start == timedelta(seconds=15)
        return ObservationProvenance(status=self.provenance_status, reason="SYNTHETIC_FIXTURE")

    def clock(self):
        self.time.now += TICK
        options = {} if self.windows is None else {"windows": self.windows}
        return clock_gate(self.time.now, offset_ms=self.offset_ms, **options)

    def provider_time(self):
        self.time.now += TICK
        return clock_proof(self.time.now - timedelta(milliseconds=50))

    def spec(self, symbol):
        self.time.now += TICK
        return spec_check(symbol, at=self.time.now, **self.spec_changes.get(symbol, {}))


class FakeSimulator:
    def __init__(self):
        self.accepted = []

    def recover_pending(self, account_ref, *, epoch, now):
        return ()

    def observe(self, fact, *, now):
        return ()

    def accept(self, intent, submission, source, *, epoch, now):
        assert submission.decision.status == "APPROVED" and epoch == 1
        self.accepted.append(intent.content_hash())


def make_runner(
    error=None,
    *,
    missed=(),
    kind="SCHEDULED",
    close_errors=(),
    release_error=None,
    roll_error=None,
    gates=None,
):
    config, clock, events = make_config_v2(), Clock(), []
    paper = FakePaper(clock, events, roll_error=roll_error)
    persistence = FakePersistence(
        config, clock, paper, kind=kind, close_errors=close_errors, release_error=release_error
    )
    truth, feed, simulator = FakeTruth(events), FakeFeed(clock, error, missed), FakeSimulator()
    runner = ObservationRunner(
        config,
        persistence,
        paper,
        truth,
        feed,
        simulator=simulator,
        gates=gates(clock) if gates else FakeGates(clock),
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
    return SimpleNamespace(
        runner=runner,
        persistence=persistence,
        paper=paper,
        truth=truth,
        feed=feed,
        simulator=simulator,
        events=events,
        config=config,
    )


def test_scheduled_night_authorizes_after_standing_resume_and_qualifies():
    fixture = make_runner()
    receipt = fixture.runner.run(kind="SCHEDULED")
    assert receipt.status == "PASS" and receipt.kind == "SCHEDULED", receipt.reasons
    # Ten-minute cadence, two symbols, entries stop five minutes before the end: 12 opens.
    assert receipt.authorization_count == receipt.proposal_count == 12
    assert receipt.terminal_authorization_count == 12 and receipt.ledger_mismatch_count == 0
    assert receipt.clock_trusted and receipt.specs_verified and receipt.day_rolled
    assert receipt.provenance_status == "VERIFIED" and receipt.price_basis == "BAR_CLOSE"
    assert receipt.campaign_version == "paper.observation.v2"
    assert len(fixture.simulator.accepted) == 12 and not fixture.paper.kill_calls
    # Start order: writer, reconcile, roll, then specification facts, then the resume,
    # and every market is a stored mark before anything is authorized on it.
    order = [e for e in fixture.events if e != "reconcile"]
    assert order[:5] == ["acquire", "roll", "observe_spec", "observe_spec", "standing_resume"]
    assert set(order[5:]) == {"mark"} and len(fixture.truth.marks) == 120
    assert [m.price_basis for m in fixture.truth.marks] == ["BAR_CLOSE"] * 120
    # One reconciliation per bar, only after both symbols are marked for that bar end
    # (a reconciliation between the marks would value the other symbol on a stale bar);
    # then the closing reconciliation.
    loop = fixture.events[fixture.events.index("standing_resume") + 1 :]
    assert loop == ["mark", "mark", "reconcile"] * 60 + ["reconcile"]
    assert [s.observed_at for s in fixture.truth.specs] == [
        c.server_at for c in fixture.persistence.close_calls[0].spec_checks
    ]
    ((use, actor),) = fixture.paper.resumes
    assert actor == "owner.founder" and use.boundary == "START_RESUME"
    assert use.boundary_hash == START_RESUME and use.roll_event_hash == fixture.paper.roll_hash
    assert use.authority_hash == fixture.persistence.authority.authority_hash


def test_preflight_without_standing_authority_is_denial_only_and_never_passes():
    fixture = make_runner(kind="PREFLIGHT")
    receipt = fixture.runner.run(kind="PREFLIGHT")
    assert receipt.status == "INCOMPLETE" and receipt.kind == "NON_COUNTING"
    assert receipt.authorization_count == 0 and receipt.denial_count == receipt.proposal_count
    assert "DENIAL_ONLY" in receipt.reasons and not fixture.paper.resumes
    assert "standing_resume" not in fixture.events and fixture.paper.kill == KillLevel.K1


@pytest.mark.parametrize(
    "status,operational,reason",
    (
        ("NOT_SCHEDULED", "observation.provenance.not_scheduled", "PROVENANCE_NOT_SCHEDULED"),
        ("UNVERIFIABLE", "observation.provenance.unverifiable", "PROVENANCE_UNVERIFIABLE"),
    ),
)
def test_unproven_scheduler_provenance_refuses_before_writer_or_feed(status, operational, reason):
    fixture = make_runner(gates=lambda clock: FakeGates(clock, provenance=status))
    receipt = fixture.runner.run(kind="SCHEDULED")
    assert receipt.status == "INCOMPLETE" and receipt.provenance_status == status
    assert operational in receipt.reasons and reason in receipt.reasons
    assert fixture.paper.acquired == 0 and fixture.feed.polls == 0 and fixture.events == []


@pytest.mark.parametrize(
    "windows,offset_ms,detail",
    (
        ((("leap_indicator", "FAIL"), ("time_since_last_good_sync", "PASS")), 0, "leap_indicator"),
        (
            (("leap_indicator", "PASS"), ("time_since_last_good_sync", "FAIL")),
            0,
            "time_since_last_good_sync",
        ),
        (None, 1991, "provider_offset_bound"),
        (None, 13000, "provider_start_window"),
    ),
)
def test_untrusted_clock_refuses_the_night_before_writer_or_feed(windows, offset_ms, detail):
    fixture = make_runner(
        gates=lambda clock: FakeGates(clock, windows=windows, offset_ms=offset_ms)
    )
    receipt = fixture.runner.run(kind="SCHEDULED")
    assert receipt.status == "INCOMPLETE" and receipt.clock_trusted is False
    assert "CLOCK_UNTRUSTED" in receipt.reasons
    assert "observation.clock.untrusted." + detail in receipt.reasons
    assert fixture.paper.acquired == 0 and fixture.feed.polls == 0


def test_spec_drift_refuses_without_recording_or_replacing_the_pinned_spec():
    drift = {"BTCUSDT": {"min_notional": spec_check("BTCUSDT").min_notional + 1}}
    fixture = make_runner(gates=lambda clock: FakeGates(clock, specs=drift))
    receipt = fixture.runner.run(kind="SCHEDULED")
    assert receipt.status == "INCOMPLETE" and receipt.specs_verified is False
    assert "SPEC_DRIFT" in receipt.reasons
    assert "observation.spec.drift.BTCUSDT.min_notional" in receipt.reasons
    assert fixture.truth.specs == [] and fixture.paper.acquired == 0


def test_refused_flat_boundary_roll_is_k1_and_incomplete_with_its_reasons():
    refusal = ValueError("FLAT_BOUNDARY_ROLL_REFUSED:NOT_FLAT,ACTIVE_RESERVATION")
    fixture = make_runner(roll_error=refusal)
    receipt = fixture.runner.run(kind="SCHEDULED")
    assert receipt.status == "INCOMPLETE" and receipt.day_rolled is False
    assert "observation.day_roll.refused.NOT_FLAT" in receipt.reasons
    assert "observation.day_roll.refused.ACTIVE_RESERVATION" in receipt.reasons
    assert "DAY_NOT_ROLLED" in receipt.reasons and fixture.paper.kill == KillLevel.K1
    assert fixture.truth.specs == [] and fixture.feed.polls == 0 and not fixture.paper.resumes


def test_unexpected_roll_error_is_a_failed_run_not_a_refusal():
    fixture = make_runner(roll_error=ValueError("STALE_PAPER_WRITER"))
    with pytest.raises(ValueError, match="STALE_PAPER_WRITER"):
        fixture.runner.run(kind="SCHEDULED")
    (recorded,) = fixture.persistence.receipts
    assert "observation.run.failed.ValueError.STALE_PAPER_WRITER" in recorded.reasons


def test_refused_standing_resume_leaves_k1_and_the_night_denial_only():
    fixture = make_runner()
    fixture.paper.mismatches = 1
    receipt = fixture.runner.run(kind="SCHEDULED")
    assert receipt.status == "INCOMPLETE" and fixture.paper.kill == KillLevel.K1
    assert "observation.standing_resume.refused.LEDGER_MISMATCH" in receipt.reasons
    assert "DENIAL_ONLY" in receipt.reasons and "LEDGER_REPLAY_MISMATCH" in receipt.reasons
    assert not fixture.paper.resumes and fixture.simulator.accepted == []


def test_campaign_v1_cannot_construct_a_runner():
    with pytest.raises(ValueError, match="^OBSERVATION_CAMPAIGN_VERSION_RETIRED$"):
        ObservationRunner(
            make_config(),
            None,
            None,
            None,
            None,
            simulator=None,
            gates=None,
            resources=lambda now: None,
        )


def test_expected_source_outage_closes_incomplete_without_inventing_truth():
    fixture = make_runner(ObservationSourceUnavailable("NETWORK"))
    receipt = fixture.runner.run(kind="SCHEDULED")
    assert receipt.status == "INCOMPLETE" and receipt.paired_observations == 0
    assert "observation.feed.unavailable" in receipt.operational_reasons
    assert len(fixture.persistence.close_calls) == 1 and fixture.truth.marks == []


def test_one_missed_bar_is_never_an_observation_and_does_not_end_the_run():
    fixture = make_runner(missed={("BTCUSDT", 23)})
    receipt = fixture.runner.run(kind="SCHEDULED")
    # Minute 23 has no BTC fact and no pair; the 22 -> 24 pair gap is exactly 120 s.
    assert len(fixture.persistence.facts_list) == 119
    assert receipt.paired_observations == 59 and receipt.max_gap_seconds == 120
    assert receipt.status == "PASS" and not fixture.paper.kill_calls
    assert receipt.last_observation_at == BEGIN + timedelta(minutes=59)
    assert receipt.ended_at >= END


def test_two_consecutive_missed_bars_trip_the_unchanged_gap_rule_but_the_run_finishes():
    fixture = make_runner(missed={("BTCUSDT", 23), ("ETHUSDT", 24)})
    receipt = fixture.runner.run(kind="SCHEDULED")
    assert receipt.paired_observations == 58 and receipt.max_gap_seconds == 180
    assert receipt.status == "INCOMPLETE"
    assert "observation.feed.gap" in receipt.operational_reasons
    assert "OBSERVATION_GAP" in receipt.reasons
    assert fixture.paper.kill_calls == [KillLevel.K1]
    assert receipt.last_observation_at == BEGIN + timedelta(minutes=59)
    assert receipt.ended_at >= END and len(fixture.persistence.close_calls) == 1


@pytest.mark.parametrize(
    "error",
    (ValueError("HASH_CORRUPT"), RuntimeError("IDENTITY_DENIED"), TypeError("PROGRAMMER_ERROR")),
)
def test_failure_after_begin_propagates_and_leaves_exactly_one_incomplete_receipt(error):
    fixture = make_runner(error)
    with pytest.raises(type(error), match=str(error)) as caught:
        fixture.runner.run(kind="SCHEDULED")
    assert caught.value is error
    reason = "observation.run.failed." + type(error).__name__ + "." + str(error)
    calls = fixture.persistence.close_calls
    assert len(calls) == 1 and calls[0].operational_reasons == (reason,)
    assert calls[0].closing_clock is None
    assert [r.status for r in fixture.persistence.receipts] == ["INCOMPLETE"]
    assert reason in fixture.persistence.receipts[0].reasons
    assert fixture.persistence.receipts[0].paired_observations == 0
    assert fixture.paper.acquired == 1 and not fixture.paper.kill_calls


def test_failure_before_the_writer_fence_still_closes_incomplete_without_reconciling():
    error = ValueError("OBSERVATION_RELEASE_PIN_MISMATCH")
    fixture = make_runner(release_error=error)
    with pytest.raises(ValueError, match="OBSERVATION_RELEASE_PIN_MISMATCH"):
        fixture.runner.run(kind="SCHEDULED")
    assert fixture.paper.acquired == 0 and fixture.paper.reconciles == 0
    assert len(fixture.persistence.close_calls) == 1
    assert fixture.persistence.close_calls[0].operational_reasons == (
        "observation.run.failed.ValueError.OBSERVATION_RELEASE_PIN_MISMATCH",
    )
    assert [r.status for r in fixture.persistence.receipts] == ["INCOMPLETE"]


def test_pass_refused_by_the_store_is_recorded_incomplete_and_can_never_count():
    refusal = RuntimeError("OBSERVATION_FINAL_STATE_OR_WINDOW_DENIED")
    fixture = make_runner(close_errors=[refusal])
    with pytest.raises(RuntimeError, match="OBSERVATION_FINAL_STATE_OR_WINDOW_DENIED") as caught:
        fixture.runner.run(kind="SCHEDULED")
    assert caught.value is refusal
    persistence = fixture.persistence
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
    fixture = make_runner(original, close_errors=[write_failure])
    with pytest.raises(RuntimeError, match="LEDGER_WRITE_FAILED") as caught:
        fixture.runner.run(kind="SCHEDULED")
    assert caught.value is write_failure and caught.value.__context__ is original
    assert len(fixture.persistence.close_calls) == 1 and fixture.persistence.receipts == []


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
