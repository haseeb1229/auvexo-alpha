"""Campaign v2 (ADR-032) pure rules: policy, clock, specs, standing resume, OBV2-12."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from observation_fixtures import (
    BEGIN,
    END,
    HASH,
    account_at,
    changed,
    clock_gate,
    clock_proof,
    fact_for,
    make_config,
    make_config_v2,
    make_run,
    spec_check,
    witness,
)
from test_observation_orchestration import START_RESUME, authority, make_runner

from auvexo_alpha.application.observation_gates import (
    clock_refusals,
    closing_clock_refusals,
    observed_specs,
    plan_standing_resume,
    spec_refusals,
)
from auvexo_alpha.application.observation_ports import JournalFact, PriorRun
from auvexo_alpha.application.observation_qualification import evaluate_observation_day
from auvexo_alpha.domain.observation import (
    ObservationProvenance,
    ObservationStandingResumeUse,
    observation_market,
    observation_policy,
)
from auvexo_alpha.domain.paper import provisional_policy, spec_terms_hash
from auvexo_alpha.domain.paper_lifecycle import KillLevel
from auvexo_alpha.infrastructure.observation_start_gates import ObservationStartGates

STARTED = BEGIN + timedelta(seconds=3)


def test_v2_policy_changes_exactly_the_three_freshness_bounds_and_input_trust():
    config = make_config_v2()
    baseline, actual = provisional_policy().model_dump(), observation_policy(config).model_dump()
    changed_keys = {key for key in baseline if baseline[key] != actual[key]}
    assert changed_keys == {
        "version",
        "allowed_accounts",
        "allowed_instruments",
        "bucket_by_instrument",
        "max_market_age_seconds",
        "max_fx_age_seconds",
        "max_clock_offset_ms",
        "input_trust",
        "pinned_spec_terms",
    }
    assert (actual["max_market_age_seconds"], actual["max_fx_age_seconds"]) == (60, 60)
    assert actual["max_clock_offset_ms"] == 2000 and actual["version"].endswith(".v2")
    assert actual["input_trust"] == "STORE_VERIFIED"
    assert actual["pinned_spec_terms"] == tuple(spec_terms_hash(s) for s in config.specs)
    # v1 keeps its accepted canonical numbers and caller-supplied trust.
    v1 = observation_policy(make_config())
    assert v1.input_trust == "CALLER_SUPPLIED" and v1.max_market_age_seconds == 2


def test_v2_markets_state_bar_close_and_v1_markets_keep_their_recorded_form():
    fact = fact_for("BTCUSDT", 0)
    v1, v2 = observation_market(fact, make_config()), observation_market(fact, make_config_v2())
    assert v2.price_basis == "BAR_CLOSE" and v2.spread_bps() == 0 and v2.bid == v2.ask
    assert v1.price_basis == "QUOTE" and b"price_basis" not in v1.canonical_bytes()
    assert v1.snapshot_id == v2.snapshot_id and v1.content_hash() != v2.content_hash()


def _legacy(value):
    """The encoding before nested contracts kept their own canonical form: one model_dump."""

    def default(item):
        if isinstance(item, Decimal):
            text = format(item, "f")
            return "0" if item == 0 else text.rstrip("0").rstrip(".") if "." in text else text
        if isinstance(item, datetime):
            return item.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        if isinstance(item, UUID):
            return str(item)
        raise TypeError("unsupported canonical value")

    return json.dumps(
        value.model_dump(mode="python"),
        default=default,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def test_nested_contracts_keep_every_recorded_v1_hash():
    config, evidence, proof = make_run(points=12)
    receipt = evaluate_observation_day(config, evidence, proof, now=END)
    # A tree with no defaulted later field encodes byte for byte as before.
    fact = evidence.facts[0]
    assert fact.canonical_bytes() == _legacy(fact)
    # A recorded v1 trace never contained price_basis; its market keeps the old form.
    trace = evidence.traces[0]
    assert b"price_basis" not in trace.canonical_bytes()
    assert b"price_basis" in _legacy(trace)
    for value in (trace, evidence, receipt, config):
        text = value.canonical_bytes()
        for key in (b"provenance", b"clock_gate", b"spec_checks", b"campaign_version"):
            assert key not in text


LEAP, SYNC = "leap_indicator", "time_since_last_good_sync"


@pytest.mark.parametrize(
    "windows,offset_ms,detail",
    (
        # The bound is |offset| plus the 10 ms half round trip: 2000 passes, 2001 refuses.
        (None, 1990, ()),
        (None, 1991, ("provider_offset_bound",)),
        (None, -1990, ()),
        (None, -1991, ("provider_offset_bound",)),
        (((LEAP, "FAIL"), (SYNC, "PASS")), 0, (LEAP,)),
        (((LEAP, "PASS"),), 0, (SYNC,)),
        (((LEAP, "PASS"), (SYNC, "NOT_CHECKED")), 0, (SYNC,)),
        # The open-interest one-second dispersion bound is not a PAPER v2 input.
        (((LEAP, "PASS"), (SYNC, "PASS"), ("offset_bound", "FAIL")), 0, ()),
    ),
)
def test_clock_gate_bounds_are_exact(windows, offset_ms, detail):
    options = {} if windows is None else {"windows": windows}
    gate = clock_gate(STARTED + timedelta(milliseconds=100), offset_ms=offset_ms, **options)
    assert (
        clock_refusals(
            gate, make_config_v2(), started_at=STARTED, window_start=BEGIN, scheduled=False
        )
        == detail
    )


def test_clock_gate_measured_before_the_run_or_outside_the_start_window_refuses():
    config = make_config_v2()
    before = clock_gate(STARTED - timedelta(milliseconds=100))
    assert clock_refusals(
        before, config, started_at=STARTED, window_start=BEGIN, scheduled=False
    ) == ("provider_before_run",)
    # Provider time places the start 1 ms before the window, or 1 ms after its 15 s.
    for started, offset in ((BEGIN, -1), (BEGIN + timedelta(seconds=15), 1)):
        gate = clock_gate(started + timedelta(milliseconds=50), offset_ms=offset, spread_ms=0)
        assert "provider_start_window" in clock_refusals(
            gate, config, started_at=started, window_start=BEGIN, scheduled=True
        )
        # The same instants are fine for a NON_COUNTING run: no start window applies.
        assert not clock_refusals(
            gate, config, started_at=started, window_start=BEGIN, scheduled=False
        )
    exact = clock_gate(BEGIN + timedelta(milliseconds=50), offset_ms=0, spread_ms=0)
    assert not clock_refusals(exact, config, started_at=BEGIN, window_start=BEGIN, scheduled=True)


def test_closing_clock_end_guard_in_provider_time():
    config = make_config_v2()
    assert closing_clock_refusals(None, config, ended_at=END, window_end=END) == (
        "closing_provider_time_missing",
    )
    good = clock_proof(END + timedelta(seconds=1), spread_ms=0)
    assert not closing_clock_refusals(
        good, config, ended_at=END + timedelta(seconds=1), window_end=END
    )
    late = clock_proof(END + timedelta(seconds=30), offset_ms=1, spread_ms=0)
    assert closing_clock_refusals(
        late, config, ended_at=END + timedelta(seconds=30), window_end=END
    ) == ("provider_end_window",)
    early = clock_proof(END, offset_ms=-1, spread_ms=0)
    assert closing_clock_refusals(early, config, ended_at=END, window_end=END) == (
        "provider_end_window",
    )
    after = clock_proof(END + timedelta(seconds=2), spread_ms=0)
    assert "closing_proof_after_close" in closing_clock_refusals(
        after, config, ended_at=END + timedelta(seconds=1), window_end=END
    )
    wide = clock_proof(END + timedelta(seconds=5), offset_ms=2001, spread_ms=0)
    assert "closing_offset_bound" in closing_clock_refusals(
        wide, config, ended_at=END + timedelta(seconds=5), window_end=END
    )


@pytest.mark.parametrize(
    "symbol,changes,detail",
    (
        ("BTCUSDT", {"price_tick": Decimal("0.1")}, "BTCUSDT.price_tick"),
        ("ETHUSDT", {"quantity_step": Decimal("0.001")}, "ETHUSDT.quantity_step"),
        ("BTCUSDT", {"min_quantity": Decimal("0.0001")}, "BTCUSDT.min_quantity"),
        ("ETHUSDT", {"min_notional": Decimal("10")}, "ETHUSDT.min_notional"),
        ("BTCUSDT", {"trade_status": "BREAK"}, "BTCUSDT.trade_status"),
        (
            "BTCUSDT",
            {"sent_at": BEGIN - timedelta(milliseconds=2001)},
            "BTCUSDT.offset",
        ),
    ),
)
def test_each_pinned_term_drift_refuses_and_never_replaces_the_pin(symbol, changes, detail):
    config = make_config_v2()
    checks = tuple(
        spec_check(s, **(changes if s == symbol else {})) for s in ("BTCUSDT", "ETHUSDT")
    )
    assert spec_refusals(config, checks) == (detail,)
    with pytest.raises(ValueError, match="SPEC_DRIFT"):
        observed_specs(config, checks)


def test_max_quantity_is_not_a_pinned_term_and_observation_keeps_provider_time():
    config = make_config_v2()
    later = BEGIN + timedelta(hours=30)
    checks = (
        spec_check("BTCUSDT", at=later, max_quantity=Decimal("100")),
        spec_check("ETHUSDT", at=later),
    )
    observed = observed_specs(config, checks)
    assert [s.observed_at for s in observed] == [later, later]
    assert [spec_terms_hash(s) for s in observed] == [spec_terms_hash(s) for s in config.specs]
    assert spec_refusals(config, checks[:1]) == ("ETHUSDT.missing",)
    assert spec_refusals(config, checks + checks[:1]) == ("BTCUSDT.missing",)


# Journal shape of a clean interval: START's audited resume, then this run's start.
def journal(*kinds, kill=KillLevel.K1, day=BEGIN):
    facts = [
        JournalFact(
            "OWNER_PAPER_RESUME",
            START_RESUME,
            BEGIN - timedelta(days=1),
            account_at(BEGIN - timedelta(days=1), kill=KillLevel.K0),
        )
    ]
    for index, kind in enumerate(kinds or ("WRITER_ACQUIRED_PAUSE_NEW", "RECONCILIATION")):
        facts.append(JournalFact(kind, str(index) * 64, day, account_at(day, kill=kill)))
    facts.append(JournalFact("FLAT_BOUNDARY_ROLL", "f" * 64, day, account_at(day, kill=kill)))
    facts.append(JournalFact("RECONCILIATION", "e" * 64, day, account_at(day, kill=kill)))
    return facts


def plan(config=None, *, record="default", activation="owner.start.synthetic", **changes):
    config = config or make_config_v2()
    options = (
        dict(
            run_id=uuid4(),
            run_activation_id=activation,
            local_day=BEGIN.date().isoformat(),
            prior=None,
            journal=journal(),
            account=account_at(STARTED),
            ledger_mismatch_count=0,
            now=STARTED,
        )
        | changes
    )
    return plan_standing_resume(
        config, authority(config) if record == "default" else record, **options
    )


def test_standing_resume_first_night_relies_on_start_and_journals_its_facts():
    use = plan()
    assert isinstance(use, ObservationStandingResumeUse)
    assert use.boundary == "START_RESUME" and use.boundary_hash == START_RESUME
    assert use.roll_event_hash == "f" * 64 and use.journal_tail_hash == "e" * 64
    assert use.examined_event_hashes == ("0" * 64, "1" * 64, "f" * 64, "e" * 64)


def previous(**changes):
    config, evidence, proof = make_run(points=12)
    receipt = evaluate_observation_day(config, evidence, proof, now=END)
    clean = dict(
        journal_tail_hash=START_RESUME,
        final_kill=KillLevel.K0,
        final_reconciled=True,
        position_hashes=(),
        ledger_mismatch_count=0,
    )
    receipt = changed(receipt, **(clean | changes))
    return PriorRun(receipt, receipt.content_hash())


def test_standing_resume_after_a_clean_previous_receipt():
    prior = previous()
    use = plan(prior=prior)
    assert isinstance(use, ObservationStandingResumeUse)
    assert use.boundary == "PREVIOUS_RECEIPT" and use.boundary_hash == prior.receipt_hash


@pytest.mark.parametrize(
    "changes,reason",
    (
        ({"record": None}, "NO_STANDING_AUTHORITY"),
        ({"activation": None}, "AUTHORITY_ACTIVATION_MISMATCH"),
        ({"activation": "owner.start.other"}, "AUTHORITY_ACTIVATION_MISMATCH"),
        ({"local_day": "2027-01-01"}, "AUTHORITY_EXPIRED"),
        ({"prior": PriorRun(None, None)}, "PREVIOUS_RUN_NOT_CLOSED"),
        ({"ledger_mismatch_count": 1}, "LEDGER_MISMATCH"),
        ({"account": account_at(STARTED, kill=KillLevel.K2)}, "KILL_NOT_WRITER_K1"),
        ({"account": account_at(STARTED, kill=KillLevel.K0)}, "KILL_NOT_WRITER_K1"),
        (
            {"account": changed(account_at(STARTED), reconciled=False)},
            "ACCOUNT_NOT_FLAT_RECONCILED",
        ),
        ({"journal": journal()[:-2]}, "DAY_NOT_ROLLED"),
        ({"journal": journal(day=BEGIN - timedelta(days=1))}, "DAY_NOT_ROLLED"),
        ({"journal": journal()[1:]}, "START_RESUME_MISSING"),
        ({"journal": journal("KILL_STATE")}, "EVENT_KILL_STATE"),
        ({"journal": journal("LOSS_BREACH_LATCH")}, "EVENT_LOSS_BREACH_LATCH"),
        ({"journal": journal("TRUTH_QUARANTINE")}, "EVENT_TRUTH_QUARANTINE"),
        ({"journal": journal("UNKNOWN_RECONCILE_ONLY")}, "EVENT_UNKNOWN_RECONCILE_ONLY"),
        ({"journal": journal("OWNER_POLICY_PIN")}, "EVENT_OWNER_POLICY_PIN"),
        ({"journal": journal("AUTHORIZED")}, "EVENT_AUTHORIZED"),
        ({"journal": journal("EDGE_STATE")}, "EVENT_EDGE_STATE"),
        ({"journal": journal("UTC_DAY_ROLLOVER")}, "EVENT_UTC_DAY_ROLLOVER"),
        (
            {"journal": journal("RECONCILIATION")},
            "KILL_RAISED_BY_RECONCILIATION",
        ),
        (
            {"journal": journal("WRITER_ACQUIRED_PAUSE_NEW", kill=KillLevel.K2)},
            "KILL_RAISED_BY_WRITER_ACQUIRED_PAUSE_NEW",
        ),
    ),
)
def test_every_standing_resume_condition_refuses(changes, reason):
    result = plan(**changes)
    assert isinstance(result, tuple) and reason in result, result


@pytest.mark.parametrize(
    "receipt_changes,reason",
    (
        ({"position_hashes": (HASH,)}, "PREVIOUS_NOT_FLAT"),
        ({"final_reconciled": False}, "PREVIOUS_NOT_RECONCILED"),
        ({"ledger_mismatch_count": 2}, "PREVIOUS_LEDGER_MISMATCH_OR_UNMEASURED"),
        ({"ledger_mismatch_count": None}, "PREVIOUS_LEDGER_MISMATCH_OR_UNMEASURED"),
        ({"final_kill": KillLevel.K1}, "PREVIOUS_KILL_RAISED"),
        ({"journal_tail_hash": "9" * 64}, "PREVIOUS_JOURNAL_TAIL_UNKNOWN"),
    ),
)
def test_every_previous_night_condition_refuses(receipt_changes, reason):
    result = plan(prior=previous(**receipt_changes))
    assert isinstance(result, tuple) and reason in result


def test_an_authority_for_another_campaign_or_commit_refuses():
    config = make_config_v2()
    other = make_config_v2(campaign_id="synthetic.other.v2")
    assert "AUTHORITY_CAMPAIGN_MISMATCH" in plan(config, record=authority(other))
    assert "AUTHORITY_CAMPAIGN_MISMATCH" in plan(
        config, record=authority(config, reviewed_sha="b" * 40)
    )
    # The last valid day is still inside the authority.
    assert isinstance(
        plan(config, record=authority(config, valid_through=BEGIN.date().isoformat())),
        ObservationStandingResumeUse,
    )


@pytest.fixture(scope="module")
def passing():
    fixture = make_runner()
    receipt = fixture.runner.run(kind="SCHEDULED")
    assert receipt.status == "PASS", receipt.reasons
    return fixture.config, fixture.persistence.close_calls[0]


def judge(config, evidence):
    return evaluate_observation_day(config, evidence, witness(evidence), now=evidence.ended_at)


@pytest.mark.parametrize(
    "changes,reason",
    (
        ({"provenance": None}, "PROVENANCE_UNVERIFIABLE"),
        (
            {"provenance": ObservationProvenance(status="UNVERIFIABLE", reason="LOG_OFF")},
            "PROVENANCE_UNVERIFIABLE",
        ),
        (
            {"provenance": ObservationProvenance(status="NOT_SCHEDULED", reason="MANUAL")},
            "PROVENANCE_NOT_SCHEDULED",
        ),
        ({"clock_gate": None}, "CLOCK_UNTRUSTED"),
        ({"closing_clock": None}, "CLOCK_UNTRUSTED"),
        ({"spec_checks": ()}, "SPEC_UNVERIFIED"),
        ({"day_roll_hash": None}, "DAY_NOT_ROLLED"),
        ({"terminal_authorization_count": 0}, "AUTHORIZATION_NOT_TERMINAL"),
        ({"terminal_authorization_count": None}, "AUTHORIZATION_NOT_TERMINAL"),
        ({"ledger_mismatch_count": 1}, "LEDGER_REPLAY_MISMATCH"),
        ({"ledger_mismatch_count": None}, "LEDGER_REPLAY_MISMATCH"),
    ),
)
def test_each_obv2_12_condition_alone_makes_a_date_incomplete(passing, changes, reason):
    config, evidence = passing
    assert judge(config, evidence).status == "PASS"
    receipt = judge(config, changed(evidence, **changes))
    assert receipt.status == "INCOMPLETE" and reason in receipt.reasons


def test_drifted_spec_evidence_and_open_position_cannot_pass(passing):
    config, evidence = passing
    drifted = (changed(evidence.spec_checks[0], min_notional=Decimal("6")),) + (
        evidence.spec_checks[1:]
    )
    assert "SPEC_DRIFT" in judge(config, changed(evidence, spec_checks=drifted)).reasons
    early = (changed(evidence.spec_checks[0], sent_at=evidence.started_at - timedelta(1)),)
    receipt = judge(config, changed(evidence, spec_checks=early + evidence.spec_checks[1:]))
    assert "SPEC_UNVERIFIED" in receipt.reasons
    held = changed(
        evidence.final_account,
        positions=(
            {
                "position_ref": "position." + "a" * 64,
                "instrument_id": "binance.spot.BTCUSDT",
                "bucket": "crypto",
                "quantity": Decimal("0.001"),
                "entry_price": Decimal("50000"),
                "mark_price": Decimal("50000"),
                "stop_price": Decimal("49500"),
            },
        ),
    )
    assert "NOT_FLAT_AT_END" in judge(config, changed(evidence, final_account=held)).reasons


def test_a_denial_only_night_is_labelled_and_never_counts(passing):
    config, evidence = passing
    denied = make_runner(kind="PREFLIGHT")
    receipt = denied.runner.run(kind="PREFLIGHT")
    assert "DENIAL_ONLY" in receipt.reasons and receipt.authorization_count == 0
    assert judge(config, evidence).authorization_count > 0


SYNCED_STATUS = (
    "Leap Indicator: 0(no warning)\nStratum: 3 (secondary reference - syncd by (S)NTP)\n"
    "Time since Last Good Sync Time: 120.5s\nPhase Offset: -0.0012s\n"
    "Root Dispersion: 7.9s\nRoot Delay: 0.05s\nSource: time.windows.com,0x9\n"
)


class GateFeed:
    def provider_time(self):
        return clock_proof(STARTED + timedelta(milliseconds=100))

    def spec(self, symbol):
        return spec_check(symbol)


def test_start_gates_reuse_the_windows_time_diagnosis_and_fail_closed():
    calls = []

    def provenance(task_path, *, window_start, window_end):
        calls.append((task_path, window_start, window_end))
        return ObservationProvenance(status="UNVERIFIABLE", reason="SYNTHETIC")

    config = make_config_v2()
    gates = ObservationStartGates(
        GateFeed(), clock_status=lambda: SYNCED_STATUS, provenance=provenance
    )
    gate = gates.clock()
    checks = dict(gate.windows_checks)
    # Dispersion of 7.9 s fails the open-interest one-second bound; PAPER v2 does not use it.
    assert checks["offset_bound"] == "FAIL" and checks["source_equals_configured"] == "NOT_CHECKED"
    assert not clock_refusals(gate, config, started_at=STARTED, window_start=BEGIN, scheduled=True)
    stale = SYNCED_STATUS.replace("120.5s", "3600.5s")
    gate = ObservationStartGates(GateFeed(), clock_status=lambda: stale).clock()
    assert clock_refusals(
        gate, config, started_at=STARTED, window_start=BEGIN, scheduled=False
    ) == ("time_since_last_good_sync",)
    leap = SYNCED_STATUS.replace("Leap Indicator: 0(no warning)", "Leap Indicator: 3(not synced)")
    gate = ObservationStartGates(GateFeed(), clock_status=lambda: leap).clock()
    assert clock_refusals(
        gate, config, started_at=STARTED, window_start=BEGIN, scheduled=False
    ) == ("leap_indicator",)

    def unreadable():
        raise OSError("w32tm unavailable")

    gate = ObservationStartGates(GateFeed(), clock_status=unreadable).clock()
    assert set(
        clock_refusals(gate, config, started_at=STARTED, window_start=BEGIN, scheduled=False)
    ) == {
        "leap_indicator",
        "time_since_last_good_sync",
    }
    assert gates.provenance(
        window_start=BEGIN, window_end=BEGIN + timedelta(seconds=15)
    ).status == ("UNVERIFIABLE")
    assert calls == [("\\AuvexoAlpha-Paper-Observation", BEGIN, BEGIN + timedelta(seconds=15))]
    assert gates.spec("ETHUSDT") == spec_check("ETHUSDT")
