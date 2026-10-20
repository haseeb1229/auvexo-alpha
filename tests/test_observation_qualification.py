"""Synthetic NON_COUNTING contract proofs; no network, database or genuine day credit."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from observation_fixtures import (
    BEGIN,
    END,
    HASH,
    account_at,
    changed,
    evaluate,
    fact_for,
    make_config,
    make_run,
)
from pydantic import ValidationError

from auvexo_alpha.application.observation_qualification import (
    evaluate_observation_day,
    observation_ledger_tail,
    observation_resource_actions,
    plan_observation_intent,
    summarize_observation_days,
    validate_observation_fact,
)
from auvexo_alpha.domain.contracts import MoneyAction
from auvexo_alpha.domain.observation import (
    ObservationLedgerProof,
    ObservationResources,
    observation_market,
    observation_policy,
    observation_release,
    observation_window,
)
from auvexo_alpha.domain.paper import PaperPosition, provisional_policy
from auvexo_alpha.domain.paper_lifecycle import KillLevel
from auvexo_alpha.domain.paper_risk import assess_paper
from auvexo_alpha.infrastructure.source_registry import identity


def test_observation_positive_is_explicitly_noncounting_and_all_denials_are_valid():
    config, evidence, verified = make_run()
    result = evaluate_observation_day(config, evidence, verified, now=END)
    assert result.status == "PASS" and result.kind == "NON_COUNTING"
    assert result.paired_observations == 60
    assert result.authorization_count == result.fill_count == 0
    assert result.proposal_count == result.denial_count == 12
    calendar = summarize_observation_days((result,), None, now=END)
    assert calendar.qualified_count == 0 and not calendar.observation_started


@pytest.mark.parametrize("points", (0, 1, 49, 50))
def test_observation_count_and_fifty_minute_span_are_independent(points):
    config, evidence, _ = make_run(points=points)
    result = evaluate(config, evidence)
    assert result.status == "INCOMPLETE"
    assert "INSUFFICIENT_OBSERVATION_SPAN" in result.reasons


@pytest.mark.parametrize("lateness", (-1, 16, 60))
def test_observation_start_outside_fixed_fifteen_seconds_is_incomplete(lateness):
    config, evidence, _ = make_run()
    result = evaluate(config, changed(evidence, started_at=BEGIN + timedelta(seconds=lateness)))
    assert "SCHEDULE_OR_CONFIG_INVALID" in result.reasons


@pytest.mark.parametrize(
    "attack",
    (
        "duplicate",
        "out_of_order",
        "gap",
        "unpaired",
        "future",
        "source",
        "hash",
        "rights",
        "backfill",
        "old",
        "first_seen",
        "manifest_count",
    ),
)
def test_observation_source_lineage_time_and_pairing_attacks_refuse(attack):
    config, evidence, _ = make_run()
    facts = list(evidence.facts)
    first = facts[0]
    if attack == "duplicate":
        facts.append(first)
    elif attack == "out_of_order":
        facts[0], facts[2] = facts[2], facts[0]
    elif attack == "gap":
        facts = tuple(
            f
            for f in facts
            if f.candle.end_at not in (BEGIN + timedelta(minutes=25), BEGIN + timedelta(minutes=26))
        )
    elif attack == "unpaired":
        facts = tuple(f for f in facts if f.candle.symbol == "BTCUSDT")
    else:
        candle, manifest = first.candle, first.manifest
        if attack == "future":
            candle = changed(
                candle,
                availability=changed(candle.availability, available_at=END + timedelta(seconds=1)),
            )
        elif attack == "source":
            manifest = changed(manifest, source=identity("DS-01"))
        elif attack == "hash":
            manifest = changed(manifest, normalized_hash="2" * 64)
        elif attack == "rights":
            manifest = changed(manifest, rights=changed(manifest.rights, version="unreviewed"))
        elif attack == "backfill":
            candle = changed(
                candle, availability=changed(candle.availability, basis="BACKFILL_RECEIPT")
            )
        elif attack == "old":
            facts[0] = fact_for("BTCUSDT", -1)
        elif attack == "first_seen":
            candle = changed(
                candle, availability=changed(candle.availability, original_first_seen_at=None)
            )
        else:
            manifest = changed(manifest, coverage=changed(manifest.coverage, observed_rows=2))
        if attack != "old":
            facts[0] = changed(first, candle=candle, manifest=manifest)
    assert evaluate(config, changed(evidence, facts=tuple(facts))).status == "INCOMPLETE"


@pytest.mark.parametrize(
    "field",
    (
        "run_evidence_hash",
        "journal_tail_hash",
        "replay_journal_hash",
        "source_fact_hashes",
        "trace_hashes",
        "replay_intent_hashes",
        "replay_decision_hashes",
        "reservation_hashes",
        "outbox_hashes",
        "fill_hashes",
    ),
)
def test_observation_independently_derived_witness_must_match_every_binding(field):
    config, evidence, verified = make_run()
    value = ("2" * 64,) if isinstance(getattr(verified, field), tuple) else "2" * 64
    result = evaluate_observation_day(
        config, evidence, changed(verified, **{field: value}), now=END
    )
    assert "VERIFICATION_OR_REPLAY_BINDING_INVALID" in result.reasons


@pytest.mark.parametrize(
    "field",
    ("unknown_order_refs", "mismatch_refs", "reservation_hashes", "outbox_hashes", "fill_hashes"),
)
def test_observation_unknown_mismatch_or_unaccounted_records_cannot_pass(field):
    config, evidence, _ = make_run()
    value = ("unresolved",) if field.endswith("refs") else (HASH,)
    assert evaluate(config, changed(evidence, **{field: value})).status == "INCOMPLETE"


def test_observation_replay_detects_forged_consistent_hashes_and_does_not_use_pnl():
    config, evidence, _ = make_run()
    trace = evidence.traces[0]
    # Changing a reason and recomputing the witness does not make it replayable.
    forged = changed(trace, decision=changed(trace.decision, reasons=trace.decision.reasons[:1]))
    bad = changed(evidence, traces=(forged,) + evidence.traces[1:])
    assert "PROPOSAL_TRACE_INVALID" in evaluate(config, bad).reasons
    for equity in ("9000", "12000"):
        final = changed(evidence.final_account, cash=Decimal(equity), equity=Decimal(equity))
        assert evaluate(config, changed(evidence, final_account=final)).status == "PASS"


def test_observation_policy_changes_identity_only_and_fixture_is_nonpromotable():
    config = make_config()
    baseline, actual = provisional_policy().model_dump(), observation_policy(config).model_dump()
    for key in ("version", "allowed_accounts", "allowed_instruments", "bucket_by_instrument"):
        baseline.pop(key)
        actual.pop(key)
    assert actual == baseline
    release = observation_release(config, now=BEGIN)
    assert release.fixture_namespace == "PAPER_QUALIFICATION_FIXTURE"
    with pytest.raises(ValidationError):
        changed(release, state="SHADOW")


@pytest.mark.parametrize("price", ("5000", "50000", "100000"))
def test_observation_planner_cadence_is_direction_independent_and_risk_bounded(price):
    config = make_config()
    fact = fact_for("BTCUSDT", 0, delay=3, close=price)
    account = changed(account_at(fact.candle.availability.available_at), kill=KillLevel.K0)
    release = observation_release(config, now=BEGIN)
    intent = plan_observation_intent(
        config, fact, account, release, now=fact.candle.availability.available_at
    )
    assert intent is not None and intent.action == MoneyAction.OPEN and intent.position_ref is None
    decision = assess_paper(
        intent,
        observation_policy(config),
        observation_market(fact),
        config.specs[0],
        account,
        release,
        now=fact.candle.availability.available_at,
    )
    assert decision.exposure.modeled_loss <= account.equity * Decimal("0.0005")
    later = fact_for("BTCUSDT", 1, close=price)
    assert (
        plan_observation_intent(
            config,
            later,
            account_at(later.candle.availability.available_at),
            release,
            now=later.candle.availability.available_at,
        )
        is None
    )
    position = PaperPosition(
        position_ref="observed.position",
        instrument_id="binance.spot.BTCUSDT",
        bucket="crypto",
        quantity=Decimal("0.001"),
        entry_price=Decimal(price),
        mark_price=Decimal(price),
        stop_price=Decimal(price) * Decimal("0.99"),
    )
    close_fact = fact_for("BTCUSDT", 5, close=price)
    held = changed(account_at(close_fact.candle.availability.available_at), positions=(position,))
    close_intent = plan_observation_intent(
        config, close_fact, held, release, now=close_fact.candle.availability.available_at
    )
    assert (
        close_intent.action == MoneyAction.CLOSE
        and close_intent.position_ref == position.position_ref
    )
    assert close_intent.quantity == position.quantity


def test_observation_mapping_never_retimes_stale_market_or_asserts_usd_peg():
    fact = fact_for("BTCUSDT", 0, delay=10)
    market = observation_market(fact)
    assert market.as_of == market.fx_as_of == fact.candle.end_at
    assert market.available_at == fact.candle.availability.available_at
    assert market.adverse_fx == Decimal("1")
    assert market.clock_offset_ms == 10


@pytest.mark.parametrize("field,value", (("base_currency", "EUR"), ("spec_version", "invented.v2")))
def test_observation_fixture_spec_identity_is_exact(field, value):
    config = make_config()
    with pytest.raises(ValidationError):
        changed(config, specs=(changed(config.specs[0], **{field: value}), config.specs[1]))


@pytest.mark.parametrize(
    "count,span,expected", ((13, 14, "OPEN"), (14, 13, "OPEN"), (14, 14, "PASS"))
)
def test_observation_calendar_requires_both_distinct_dates_and_full_elapsed_span(
    count, span, expected
):
    config, evidence, _ = make_run()
    receipt = changed(evaluate(config, evidence), kind="SCHEDULED")
    days = list(range(count))
    days[-1] = span
    receipts = tuple(
        changed(
            receipt, run_id=uuid4(), local_day=(BEGIN.date() + timedelta(days=offset)).isoformat()
        )
        for offset in days
    )
    now = END + timedelta(days=span + 1)
    proof = ObservationLedgerProof(
        campaign_id=config.campaign_id,
        activated_at=BEGIN - timedelta(days=1),
        first_eligible_day=BEGIN.date().isoformat(),
        verified_at=now,
        receipt_hashes=tuple(r.content_hash() for r in receipts),
        ledger_tail_hash=observation_ledger_tail(receipts),
    )
    result = summarize_observation_days(receipts, proof, now=now)
    assert result.status == expected and result.qualified_count == count
    # Synthetic proof construction here tests pure arithmetic only, never DB credit.


@pytest.mark.parametrize("attack", ("duplicate", "hash", "future", "activation", "noncounting"))
def test_observation_calendar_refuses_import_mutation_and_never_counts_test_receipts(attack):
    config, evidence, _ = make_run()
    receipt = changed(evaluate(config, evidence), kind="SCHEDULED")
    receipts = (receipt, receipt) if attack == "duplicate" else (receipt,)
    now = END - timedelta(minutes=1) if attack == "future" else END
    proof = ObservationLedgerProof(
        campaign_id=config.campaign_id,
        activated_at=BEGIN if attack == "activation" else BEGIN - timedelta(days=1),
        first_eligible_day=BEGIN.date().isoformat(),
        verified_at=now,
        receipt_hashes=tuple(r.content_hash() for r in receipts),
        ledger_tail_hash=observation_ledger_tail(receipts),
    )
    if attack == "hash":
        proof = changed(proof, receipt_hashes=("2" * 64,))
    elif attack == "noncounting":
        receipts = (changed(receipt, kind="NON_COUNTING"),)
        proof = changed(
            proof,
            receipt_hashes=tuple(r.content_hash() for r in receipts),
            ledger_tail_hash=observation_ledger_tail(receipts),
        )
    result = summarize_observation_days(receipts, proof, now=now)
    assert result.qualified_count == 0 and result.status != "PASS"


def test_observation_utc_local_date_window_and_malformed_config_are_strict():
    assert observation_window("2026-10-21") == (BEGIN, END)
    with pytest.raises(ValueError):
        observation_window("20261021")
    with pytest.raises(ValidationError):
        changed(make_config(), max_fixture_risk_fraction=Decimal("0.0006"))
    with pytest.raises(ValidationError):
        ObservationResources(
            observed_at=BEGIN, available_ram_bytes=True, cpu_percent=20.0, cpu_high_for_seconds=0
        )


def test_fifty_one_paired_points_can_cover_window_without_inventing_missing_bars():
    minutes = tuple(minute for minute in range(59) if minute not in (7, 14, 21, 28, 35, 42, 49, 56))
    config, evidence, _ = make_run(minutes=minutes)
    result = evaluate(config, evidence)
    assert result.status == "PASS" and result.paired_observations == 51
    assert result.max_gap_seconds == 120
    assert result.first_observation_at == BEGIN
    assert result.last_observation_at == BEGIN + timedelta(minutes=58)


@pytest.mark.parametrize(
    ("minutes", "reason"),
    ((tuple(range(9, 60)), "OBSERVATION_START_GAP"), (tuple(range(51)), "OBSERVATION_END_GAP")),
)
def test_full_window_edges_cannot_hide_unexplained_ten_minute_gaps(minutes, reason):
    config, evidence, _ = make_run(minutes=minutes)
    result = evaluate(config, evidence)
    assert result.paired_observations == 51
    assert result.status == "INCOMPLETE" and reason in result.reasons


@pytest.mark.parametrize(
    ("ram", "cpu", "duration", "expected"),
    (
        (3_000_000_000, "80", 60, ()),
        (3_000_000_000, "80.01", 59, ()),
        (3_000_000_000, "20", 600, ()),
        (3_000_000_000, "80.01", 60, ("PAUSE_OPTIONAL_RESEARCH",)),
        (2_999_999_999, "20", 0, ("PAUSE_OPTIONAL_RESEARCH",)),
        (1_499_999_999, "20", 0, ("PAUSE_OPTIONAL_RESEARCH", "PAUSE_ENTRIES")),
    ),
)
def test_resource_actions_use_exact_current_cpu_and_duration_thresholds(
    ram, cpu, duration, expected
):
    resource = ObservationResources(
        observed_at=BEGIN,
        available_ram_bytes=ram,
        cpu_percent=Decimal(cpu),
        cpu_high_for_seconds=duration,
    )
    assert observation_resource_actions(resource) == expected


def test_standalone_receipt_exposes_pins_resource_and_account_safety_without_sql_join():
    config, evidence, _ = make_run()
    result = evaluate(config, evidence)
    assert result.git_revision == config.git_revision
    assert result.policy_hash == observation_policy(config).content_hash()
    assert result.spec_hashes == tuple(spec.content_hash() for spec in config.specs)
    assert result.source_hash == config.source.content_hash()
    assert result.rights_hash == config.rights.content_hash()
    assert (result.scheduled_at, result.started_at, result.ended_at) == (BEGIN, BEGIN, END)
    assert result.final_kill == evidence.final_account.kill
    assert result.final_reconciled == evidence.final_account.reconciled
    assert result.resources == evidence.resource_snapshots


def test_low_ram_unknown_or_unreconciled_final_state_is_incomplete_without_auto_reset():
    config, evidence, _ = make_run()
    for final in (
        changed(evidence.final_account, unknown_orders=True),
        changed(evidence.final_account, reconciled=False),
        changed(evidence.final_account, journal_healthy=False),
    ):
        assert evaluate(config, changed(evidence, final_account=final)).status == "INCOMPLETE"
    low = changed(evidence.resource_snapshots[0], available_ram_bytes=1_499_999_999)
    result = evaluate(config, changed(evidence, resource_snapshots=(low,)))
    assert "RESOURCE_ENTRY_PAUSE" in result.reasons
    assert result.final_kill == evidence.final_account.kill


def test_calendar_requires_exact_canonical_immutable_ledger_sequence_hash():
    config, evidence, _ = make_run()
    receipt = changed(evaluate(config, evidence), kind="SCHEDULED")
    proof = ObservationLedgerProof(
        campaign_id=config.campaign_id,
        activated_at=BEGIN - timedelta(days=1),
        first_eligible_day=BEGIN.date().isoformat(),
        verified_at=END,
        receipt_hashes=(receipt.content_hash(),),
        ledger_tail_hash="2" * 64,
    )
    result = summarize_observation_days((receipt,), proof, now=END)
    assert result.status == "INVALID" and result.qualified_count == 0
    assert "LEDGER_TAIL_BINDING_INVALID" in result.reasons


def test_planner_refuses_after_window_without_changing_kill():
    config = make_config()
    fact = fact_for("BTCUSDT", 0)
    account = account_at(BEGIN + timedelta(seconds=3))
    release = observation_release(config, now=BEGIN)
    assert plan_observation_intent(config, fact, account, release, now=END) is None
    assert account.kill == KillLevel.K1


@pytest.mark.parametrize(
    "raw",
    (
        '{"serverTime":true}',
        '{"serverTime":9999999999999999999999999999}',
        '{"serverTime":-1}',
        '{"serverTime":0,"unknown":1}',
        "[]",
    ),
)
def test_provider_clock_proof_rejects_invalid_or_overflowing_response(raw):
    from hashlib import sha256

    from auvexo_alpha.domain.observation import ObservationClockProof

    fact = fact_for("BTCUSDT", 0)
    with pytest.raises(ValueError):
        ObservationClockProof.model_validate(
            fact.clock.model_dump()
            | {
                "raw_json": raw,
                "raw_hash": sha256(raw.encode()).hexdigest(),
            }
        )


def test_provider_clock_must_independently_prove_bar_finality_before_receipt():
    import json
    from datetime import UTC, datetime
    from hashlib import sha256

    config = make_config()
    fact = fact_for("BTCUSDT", 0)
    server = fact.candle.end_at - timedelta(milliseconds=1)
    raw = json.dumps(
        {"serverTime": int((server - datetime(1970, 1, 1, tzinfo=UTC)).total_seconds() * 1000)}
    )
    proof = changed(
        fact.clock, server_at=server, raw_json=raw, raw_hash=sha256(raw.encode()).hexdigest()
    )
    with pytest.raises(ValueError, match="OBSERVATION_FACT_INVALID"):
        validate_observation_fact(
            config,
            changed(fact, clock=proof),
            local_day=BEGIN.date().isoformat(),
            now=fact.candle.availability.available_at,
        )
