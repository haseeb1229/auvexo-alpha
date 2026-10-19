"""Mandatory real-PostgreSQL adversarial PAPER engineering evidence, never market evidence."""

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from json import dumps
from multiprocessing import get_context
from os import _exit
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
from paper_fixtures import fixture_bundle
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError

from auvexo_alpha.domain.paper import PaperIntent, PaperReason, paper_position_ref
from auvexo_alpha.domain.paper_lifecycle import KillLevel
from auvexo_alpha.infrastructure.paper_identity import PaperIdentityError
from auvexo_alpha.infrastructure.paper_store import PaperStore, PaperTruth
from tools.paper_local import (
    admin_args,
    engine_for,
    isolated_database,
    load_credentials,
    migrate,
    require_migration,
    snapshot,
)

pytestmark = pytest.mark.integration

IMMUTABLE_TABLES = (
    "paper_policy",
    "paper_release",
    "paper_intent",
    "paper_authorization",
    "paper_journal",
    "paper_denial",
    "paper_lifecycle",
    "paper_truth_event",
    "paper_production_release",
    "paper_production_lifecycle",
)


@pytest.fixture(scope="module")
def paper_database():
    with isolated_database() as name:
        require_migration(name)
        yield name


def test_paper_forward_migration_idempotent_and_downgrade_refused(paper_database):
    before = snapshot(paper_database)
    require_migration(paper_database)
    assert snapshot(paper_database) == before
    refused = migrate(paper_database, "downgrade", "0004_research_ledger")
    assert refused.returncode != 0
    assert b"destructive downgrade disabled" in refused.stderr
    assert snapshot(paper_database) == before
    with psycopg.connect(dbname=paper_database, **admin_args()) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0005_paper_core",
        )
        assert conn.execute(
            "SELECT execution_enabled,binance_live_derivatives FROM foundation_policy"
        ).fetchone() == (False, "BLOCKED_BY_POLICY")


@pytest.mark.parametrize("table", IMMUTABLE_TABLES)
@pytest.mark.parametrize(
    "operation",
    ("UPDATE {table} SET payload=payload", "DELETE FROM {table}", "TRUNCATE {table} CASCADE"),
)
def test_paper_histories_immutable_even_to_migrator(paper_database, table, operation):
    with psycopg.connect(dbname=paper_database, **admin_args()) as conn:
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute(operation.format(table=table))
        conn.rollback()


@pytest.mark.parametrize("role", ("auvexo_paper", "auvexo_paper_truth"))
def test_paper_roles_cannot_cross_foundation_research_or_schema(paper_database, role):
    engine = engine_for(paper_database, role)
    try:
        for statement in (
            "UPDATE foundation_policy SET execution_enabled=true",
            "DELETE FROM research_study",
            "INSERT INTO research_trial VALUES ('forbidden','forbidden','OOS',"
            "repeat('0',64),repeat('0',64),1,now())",
            "CREATE TABLE paper_forbidden(x integer)",
            "CREATE ROLE paper_forbidden_role",
            "GRANT auvexo_paper_truth TO auvexo_paper",
        ):
            with pytest.raises(DBAPIError), engine.begin() as conn:
                conn.execute(text(statement))
        with engine.connect() as conn:
            role_state = conn.execute(
                text(
                    "SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles "
                    "WHERE rolname=current_user"
                )
            ).one()
            assert role_state == (False, False, False)
    finally:
        engine.dispose()


def test_paper_truth_is_separate_and_runtime_cannot_manufacture_it(paper_database):
    runtime = engine_for(paper_database, "auvexo_paper")
    truth = engine_for(paper_database, "auvexo_paper_truth")
    try:
        for statement in (
            "INSERT INTO paper_truth_event"
            "(event_id,account_ref,kind,content_hash,payload,recorded_at) "
            "VALUES ('forbidden','paper.forbidden','STATUS',repeat('0',64),'{}',now())",
            "UPDATE paper_truth_event SET payload=payload",
            "DELETE FROM paper_truth_event",
        ):
            with pytest.raises(DBAPIError), runtime.begin() as conn:
                conn.execute(text(statement))
        with pytest.raises(DBAPIError), truth.begin() as conn:
            conn.execute(text("UPDATE paper_account SET reconciled=true"))
        with pytest.raises(DBAPIError), truth.begin() as conn:
            conn.execute(text("INSERT INTO paper_policy VALUES(repeat('0',64),'{}',now())"))
    finally:
        runtime.dispose()
        truth.dispose()


@pytest.fixture
def paper_core(paper_database, request):
    runtime = engine_for(paper_database, "auvexo_paper")
    owner = engine_for(paper_database, "auvexo_paper_owner")
    simulator = engine_for(paper_database, "auvexo_paper_truth")
    bundle = fixture_bundle(account_ref="paper.test." + uuid4().hex)
    if getattr(request, "param", None):
        bundle.policy = type(bundle.policy).model_validate(
            bundle.policy.model_dump() | request.param
        )
    store = PaperStore(runtime, owner_engine=owner)
    truth = PaperTruth(simulator)
    store.initialize(bundle.account, bundle.policy, bundle.release, now=bundle.now)
    epoch = store.acquire_writer(bundle.account.account_ref, now=bundle.now)
    assert store.reconcile(bundle.account.account_ref, now=bundle.now)
    store.resume(bundle.account.account_ref, actor="owner.fixture", now=bundle.now)
    bundle.account = store.account(bundle.account.account_ref)
    bundle.intent = bundle.rebind()
    try:
        yield bundle, store, truth, epoch
    finally:
        runtime.dispose()
        owner.dispose()
        simulator.dispose()


def submit(bundle, store, *, logical_key=None, **changes):
    bundle.account = store.account(bundle.account.account_ref)
    intent = bundle.rebind(
        intent_id=uuid4(), logical_key=logical_key or "fixture." + uuid4().hex, **changes
    )
    result = store.authorize(
        intent, bundle.policy, bundle.market, bundle.spec, bundle.release, now=bundle.now
    )
    return intent, result


def test_paper_atomic_records_denials_and_duplicate_logical_key(paper_core):
    b, store, _, _ = paper_core
    intent, first = submit(b, store, logical_key="same.logical.action")
    assert first.decision.status == "APPROVED"
    assert first.authorization.intent_hash == intent.content_hash()
    assert first.reservation.intent_hash == intent.content_hash()
    _, duplicate = submit(b, store, logical_key="same.logical.action")
    assert duplicate.decision.status == "DENIED"
    assert PaperReason.DUPLICATE_INTENT in duplicate.decision.reasons
    assert len(store.reservations(b.account.account_ref)) == 1
    assert store.outbox(intent.content_hash())["state"] == "RESERVED"
    assert store.journal(b.account.account_ref)


def _race_submit(arguments):
    """Spawn-safe independent connection and engine, with no inherited pooled sessions."""
    database, bundle, logical_key, barrier = arguments
    bundle = deepcopy(bundle)
    engine = engine_for(database, "auvexo_paper")
    try:
        store = PaperStore(engine)
        bundle.account = store.account(bundle.account.account_ref)
        intent = bundle.rebind(intent_id=uuid4(), logical_key=logical_key)
        # Every proposal sees an individually valid pre-race account snapshot.
        # All independent writers cross into the transaction concurrently.
        barrier.wait(timeout=30)
        result = store.authorize(
            intent, bundle.policy, bundle.market, bundle.spec, bundle.release, now=bundle.now
        )
        return result.decision.status, intent.content_hash(), tuple(result.decision.reasons)
    finally:
        engine.dispose()


def race_outcomes(database, bundle, pool_type, keys):
    context = get_context("spawn")
    with context.Manager() as manager:
        barrier = manager.Barrier(4)
        jobs = [(database, bundle, key, barrier) for key in keys]
        options = {"mp_context": context} if pool_type is ProcessPoolExecutor else {}
        with pool_type(max_workers=4, **options) as pool:
            return list(pool.map(_race_submit, jobs))


@pytest.mark.parametrize("pool_type", (ThreadPoolExecutor, ProcessPoolExecutor))
def test_paper_independent_race_deduplicates_and_reserves_once(
    paper_database, paper_core, pool_type
):
    b, store, _, _ = paper_core
    # Every worker has its own engine and connection; process workers use Windows spawn.
    outcomes = race_outcomes(paper_database, b, pool_type, ["logical.race.same"] * 4)
    assert sum(status == "APPROVED" for status, _, _ in outcomes) == 1
    assert all(
        status == "APPROVED"
        or PaperReason.DUPLICATE_INTENT in reasons
        or PaperReason.HASH_MISMATCH in reasons
        for status, _, reasons in outcomes
    )
    assert len(store.reservations(b.account.account_ref)) == 1
    with store.engine.connect() as conn:
        for table in ("paper_intent", "paper_authorization", "paper_reservation", "paper_outbox"):
            assert (
                conn.execute(
                    text(
                        f"SELECT count(*) FROM {table} WHERE "
                        + (
                            "account_ref=:account"
                            if table != "paper_authorization"
                            else "intent_hash IN (SELECT intent_hash FROM paper_intent "
                            "WHERE account_ref=:account)"
                        )
                    ),
                    {"account": b.account.account_ref},
                ).scalar_one()
                == 1
            )


@pytest.mark.parametrize("pool_type", (ThreadPoolExecutor, ProcessPoolExecutor))
@pytest.mark.parametrize(
    "paper_core", [{"max_bucket_risk_fraction": Decimal("0.0015")}], indirect=True
)
def test_paper_independent_race_never_oversubscribes_aggregate(
    paper_database, paper_core, pool_type
):
    b, store, _, _ = paper_core
    # One .01 proposal fits; two exceed the frozen lower bucket cap of 15.
    outcomes = race_outcomes(paper_database, b, pool_type, ["capacity." + str(i) for i in range(4)])
    assert sum(status == "APPROVED" for status, _, _ in outcomes) == 1
    assert all(
        status == "APPROVED"
        or PaperReason.BUCKET_RISK_CAP in reasons
        or PaperReason.HASH_MISMATCH in reasons
        for status, _, reasons in outcomes
    )
    reserved = store.reservations(b.account.account_ref)
    assert sum((r.modeled_loss for r in reserved), Decimal("0")) <= Decimal("15")
    with store.engine.connect() as conn:
        count, risk = conn.execute(
            text(
                "SELECT count(*),sum((payload::jsonb->>'modeled_loss')::numeric) "
                "FROM paper_reservation WHERE account_ref=:account AND active"
            ),
            {"account": b.account.account_ref},
        ).one()
        assert count == 1 and Decimal("0") < risk <= Decimal("15")
        for table in ("paper_intent", "paper_outbox"):
            assert (
                conn.execute(
                    text(f"SELECT count(*) FROM {table} WHERE account_ref=:account"),
                    {"account": b.account.account_ref},
                ).scalar_one()
                == 1
            )
    _, fresh_denial = submit(b, store)
    assert fresh_denial.decision.status == "DENIED"
    assert PaperReason.BUCKET_RISK_CAP in fresh_denial.decision.reasons


@pytest.mark.parametrize("fault", ("LOST_RESPONSE", "CRASH_AFTER_SEND"))
def test_paper_unknown_durable_truth_retains_capacity_and_cannot_resend(paper_core, fault):
    b, store, truth, epoch = paper_core
    intent, first = submit(b, store)
    before = first.reservation.modeled_loss
    if fault == "CRASH_AFTER_SEND":
        with pytest.raises(RuntimeError):
            store.dispatch(intent.content_hash(), epoch, truth, now=b.now, fault=fault)
    else:
        store.dispatch(intent.content_hash(), epoch, truth, now=b.now, fault=fault)
    assert store.outbox(intent.content_hash())["state"] == "UNKNOWN"
    assert (
        sum((r.modeled_loss for r in store.reservations(b.account.account_ref)), Decimal("0"))
        == before
    )
    with pytest.raises(ValueError):
        store.dispatch(intent.content_hash(), epoch, truth, now=b.now)
    _, paused = submit(b, store)
    assert paused.decision.status == "DENIED"
    assert not store.reconcile(b.account.account_ref, now=b.now)
    truth.status(
        intent.content_hash(), "ACKNOWLEDGED", account_ref=b.account.account_ref, now=b.now
    )
    assert store.reconcile(b.account.account_ref, now=b.now)
    # Reconciling a proven ACK restores the order projection, never automatic K0.
    assert store.account(b.account.account_ref).kill != KillLevel.K0
    assert store.outbox(intent.content_hash())["attempts"] == 1
    with pytest.raises(ValueError):
        store.dispatch(intent.content_hash(), epoch, truth, now=b.now)


def test_paper_writer_epoch_fences_stale_writer_and_restart_stays_paused(paper_core):
    b, store, truth, epoch = paper_core
    intent, _ = submit(b, store)
    newer = store.acquire_writer(b.account.account_ref, now=b.now)
    assert newer > epoch
    with pytest.raises(ValueError):
        store.dispatch(intent.content_hash(), epoch, truth, now=b.now)
    account = store.account(b.account.account_ref)
    assert not account.reconciled and account.kill != KillLevel.K0
    _, decision = submit(b, store)
    assert decision.decision.status == "DENIED"


def _claim_then_crash(database, intent_hash, epoch, now):
    engine = engine_for(database, "auvexo_paper")
    PaperStore(engine).claim(intent_hash, epoch, now=now)
    # Deliberately skip Python finally blocks after a durable dispatch-attempt commit.
    _exit(73)


def test_paper_process_crash_after_durable_attempt_enters_unknown_without_resend(
    paper_database, paper_core
):
    b, store, truth, epoch = paper_core
    intent, first = submit(b, store)
    process = get_context("spawn").Process(
        target=_claim_then_crash, args=(paper_database, intent.content_hash(), epoch, b.now)
    )
    process.start()
    process.join(timeout=30)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        pytest.fail("Synthetic child dispatch process did not complete within its bound")
    assert process.exitcode == 73
    assert store.outbox(intent.content_hash())["state"] == "SENT_PENDING"
    assert not truth.events(b.account.account_ref)
    new_epoch = store.acquire_writer(b.account.account_ref, now=b.now)
    assert not store.reconcile(b.account.account_ref, now=b.now)
    assert store.outbox(intent.content_hash())["state"] == "UNKNOWN"
    assert (
        store.reservations(b.account.account_ref)[0].modeled_loss == first.reservation.modeled_loss
    )
    with pytest.raises(ValueError):
        store.dispatch(intent.content_hash(), new_epoch, truth, now=b.now)


def test_paper_partial_duplicate_out_of_order_and_cancel_fill_race(paper_core):
    b, store, truth, epoch = paper_core
    intent, first = submit(b, store)
    store.dispatch(intent.content_hash(), epoch, truth, now=b.now)
    event = "partial." + uuid4().hex
    truth.fill(
        intent.content_hash(),
        Decimal("0.004"),
        b.intent.entry,
        account_ref=b.account.account_ref,
        now=b.now,
        event_id=event,
    )
    truth.fill(
        intent.content_hash(),
        Decimal("0.004"),
        b.intent.entry,
        account_ref=b.account.account_ref,
        now=b.now,
        event_id=event,
    )
    assert store.reconcile(b.account.account_ref, now=b.now)
    assert store.outbox(intent.content_hash())["state"] == "PARTIALLY_FILLED"
    assert sum(p.quantity for p in store.account(b.account.account_ref).positions) == Decimal(
        "0.004"
    )
    remaining = store.reservations(b.account.account_ref)
    assert sum(r.quantity for r in remaining) == Decimal("0.006")
    assert sum(r.modeled_loss for r in remaining) <= first.reservation.modeled_loss
    truth.status(intent.content_hash(), "CANCELED", account_ref=b.account.account_ref, now=b.now)
    # Delayed fill is an independent virtual fact: must survive an earlier terminal status.
    truth.fill(
        intent.content_hash(),
        Decimal("0.006"),
        b.intent.entry,
        account_ref=b.account.account_ref,
        now=b.now + timedelta(microseconds=1),
    )
    truth.status(
        intent.content_hash(), "ACKNOWLEDGED", account_ref=b.account.account_ref, now=b.now
    )
    assert store.reconcile(b.account.account_ref, now=b.now + timedelta(microseconds=1))
    assert store.outbox(intent.content_hash())["state"] == "FILLED"
    assert sum(p.quantity for p in store.account(b.account.account_ref).positions) == Decimal(
        "0.01"
    )
    assert not store.reservations(b.account.account_ref)


def test_paper_runtime_cannot_resume_or_relax_kill_state(paper_core):
    b, store, _, _ = paper_core
    store.set_kill(b.account.account_ref, KillLevel.K4, actor="runtime.fixture", now=b.now)
    runtime_only = PaperStore(store.engine)
    with pytest.raises(ValueError):
        runtime_only.resume(b.account.account_ref, actor="owner.fixture", now=b.now)
    with pytest.raises(ValueError):
        runtime_only.set_kill(b.account.account_ref, KillLevel.K0, actor="owner.fixture", now=b.now)
    assert store.account(b.account.account_ref).kill == KillLevel.K4


def test_paper_fixture_registry_cannot_enter_production_registry(paper_core):
    b, store, _, _ = paper_core
    with pytest.raises(ValueError):
        store.register_release(b.release, fixture_registry=False, now=b.now)
    with store.owner_engine.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM paper_production_release")).scalar_one() == 0
        assert (
            conn.execute(text("SELECT count(*) FROM paper_production_lifecycle")).scalar_one() == 0
        )
    with pytest.raises(DBAPIError), store.owner_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO paper_production_release VALUES (:hash,:payload,:now)"),
            {
                "hash": b.release.content_hash(),
                "payload": b.release.canonical_bytes().decode(),
                "now": b.now,
            },
        )


def test_paper_claim_rejects_altered_expired_or_unpersisted_authorization(paper_core):
    b, store, _, epoch = paper_core
    intent, first = submit(b, store)
    for change in (
        {"intent_hash": "0" * 64},
        {"policy_hash": "0" * 64},
        {"spec_hash": "0" * 64},
        {"release_hash": "0" * 64},
        {"account_ref": "paper.wrong"},
        {"writer_epoch": epoch + 1},
        {"authorization_id": uuid4()},
    ):
        altered = first.authorization.model_copy(update=change)
        with pytest.raises(ValueError):
            store.claim(intent.content_hash(), epoch, now=b.now, authorization=altered)
        assert store.outbox(intent.content_hash())["attempts"] == 0
    with pytest.raises(ValueError):
        store.claim(intent.content_hash(), epoch, now=b.now + timedelta(minutes=1))
    assert store.outbox(intent.content_hash())["attempts"] == 0
    claimed = store.claim(
        intent.content_hash(), epoch, now=b.now, authorization=first.authorization
    )
    assert claimed == first.authorization
    assert store.outbox(intent.content_hash())["attempts"] == 1


def test_paper_truth_boundary_fences_epoch_changed_after_claim(paper_core):
    b, store, truth, epoch = paper_core
    intent, _ = submit(b, store)
    store.claim(intent.content_hash(), epoch, now=b.now)
    store.acquire_writer(b.account.account_ref, now=b.now)
    with pytest.raises(ValueError):
        truth.record_order(intent, now=b.now, writer_epoch=epoch)
    assert not truth.events(b.account.account_ref)


def test_paper_truth_order_cannot_exceed_exact_authorized_quantity(paper_core):
    b, store, truth, epoch = paper_core
    intent, _ = submit(b, store)
    store.claim(intent.content_hash(), epoch, now=b.now)
    with pytest.raises(ValueError):
        truth.record_order(intent, now=b.now, writer_epoch=epoch, quantity=Decimal("0.02"))
    assert not truth.events(b.account.account_ref)


def test_paper_unrealized_loss_uses_fresh_independent_marks_and_sticks(paper_core):
    b, store, truth, epoch = paper_core
    intent, _ = submit(b, store)
    store.dispatch(intent.content_hash(), epoch, truth, now=b.now)
    truth.fill(intent.content_hash(), "0.01", "50000", account_ref=b.account.account_ref, now=b.now)
    assert store.reconcile(b.account.account_ref, now=b.now)
    b.now += timedelta(seconds=1)
    b.market = type(b.market).model_validate(
        b.market.model_dump()
        | {
            "snapshot_id": uuid4(),
            "as_of": b.now,
            "available_at": b.now,
            "fx_as_of": b.now,
            "bid": Decimal("40000"),
            "ask": Decimal("40000"),
        }
    )
    truth.mark(b.account.account_ref, b.market, now=b.now)
    assert store.reconcile(b.account.account_ref, now=b.now)
    account = store.account(b.account.account_ref)
    # Paid conservative cost1.7675; position value404 rather than initial505.
    assert account.cash == Decimal("9493.2325")
    assert account.equity == Decimal("9897.2325")
    _, denied = submit(b, store)
    assert PaperReason.DAILY_LOSS_CAP in denied.decision.reasons
    assert store.account(b.account.account_ref).kill == KillLevel.K2
    with pytest.raises(ValueError, match="LOSS_LIMIT"):
        store.resume(b.account.account_ref, actor="owner.fixture", now=b.now)
    assert not store.reconcile(b.account.account_ref, now=b.now + timedelta(seconds=3))


def test_paper_close_charges_modeled_costs_and_cannot_reverse(paper_core):
    from auvexo_alpha.domain.contracts import MoneyAction

    b, store, truth, epoch = paper_core
    intent, _ = submit(b, store)
    store.dispatch(intent.content_hash(), epoch, truth, now=b.now)
    truth.fill(intent.content_hash(), "0.01", "50000", account_ref=b.account.account_ref, now=b.now)
    assert store.reconcile(b.account.account_ref, now=b.now)
    ref = store.account(b.account.account_ref).positions[0].position_ref
    close, result = submit(
        b, store, action=MoneyAction.CLOSE, side="SELL", quantity=Decimal("0.004"), position_ref=ref
    )
    assert result.decision.status == "APPROVED"
    assert result.authorization.exposure.modeled_loss == Decimal("0.707")
    store.dispatch(close.content_hash(), epoch, truth, now=b.now)
    truth.fill(close.content_hash(), "0.004", "50000", account_ref=b.account.account_ref, now=b.now)
    assert store.reconcile(b.account.account_ref, now=b.now)
    account = store.account(b.account.account_ref)
    assert account.cash == Decimal("9694.5255")
    assert account.positions[0].quantity == Decimal("0.006")
    assert account.equity == Decimal("9997.5255")


def test_paper_external_position_requires_reconciliation_then_stays_paused(paper_core):
    from auvexo_alpha.domain.paper import PaperPosition

    b, store, truth, _ = paper_core
    external = PaperPosition(
        position_ref="external.virtual.position",
        instrument_id=b.intent.instrument_id,
        bucket="crypto",
        quantity=Decimal("0.002"),
        entry_price=b.intent.entry,
        mark_price=b.intent.entry,
        mark_as_of=b.now,
        fx_as_of=b.now,
        stop_price=b.intent.stop,
    )
    truth.external_position(b.account.account_ref, external, now=b.now)
    _, pending = submit(b, store)
    assert pending.decision.status == "DENIED"
    assert PaperReason.ACCOUNT_UNRECONCILED in pending.decision.reasons
    assert not store.reconcile(b.account.account_ref, now=b.now)
    assert store.reconcile(b.account.account_ref, now=b.now)
    account = store.account(b.account.account_ref)
    external_fact = next(
        e for e in truth.events(b.account.account_ref) if e["kind"] == "EXTERNAL_POSITION"
    )
    expected_external = external.model_copy(
        update={
            "mark_available_at": b.now,
            "mark_snapshot_hash": external.content_hash(),
            "mark_fact_hash": external_fact["content_hash"],
        }
    )
    assert account.positions == (expected_external,)
    assert account.kill != KillLevel.K0
    _, denied = submit(b, store)
    assert denied.decision.status == "DENIED"


def test_paper_observed_flows_and_utc_day_never_clear_loss_or_kill(paper_core):
    _, store, truth, _ = paper_core
    b = fixture_bundle(account_ref="paper.loss." + uuid4().hex, equity="9890")
    b.account = type(b.account).model_validate(
        b.account.model_dump()
        | {"high_water_equity": Decimal("10000"), "day_start_equity": Decimal("10000")}
    )
    store.initialize(b.account, b.policy, b.release, now=b.now)
    store.acquire_writer(b.account.account_ref, now=b.now)
    assert store.reconcile(b.account.account_ref, now=b.now)
    with pytest.raises(ValueError, match="LOSS_LIMIT"):
        store.resume(b.account.account_ref, actor="owner.fixture", now=b.now)
    truth.adjustment(b.account.account_ref, Decimal("1000"), now=b.now)
    assert store.reconcile(b.account.account_ref, now=b.now)
    account = store.account(b.account.account_ref)
    assert account.day_start_equity - (account.equity - account.day_net_flows) == Decimal("110")
    assert account.kill != KillLevel.K0
    with pytest.raises(ValueError, match="LOSS_LIMIT"):
        store.resume(b.account.account_ref, actor="owner.fixture", now=b.now)
    midnight = (b.now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    assert store.reconcile(b.account.account_ref, now=midnight)
    store.roll_day(b.account.account_ref, now=midnight)
    rolled = store.account(b.account.account_ref)
    assert rolled.day_start_at.hour == rolled.day_start_at.minute == 0
    assert rolled.kill != KillLevel.K0
    assert rolled.high_water_equity == account.high_water_equity
    assert rolled.net_flows_since_high_water == Decimal("1000")


def test_paper_edge_resume_requires_owner_role_and_persists_history(paper_core):
    from auvexo_alpha.domain.paper_lifecycle import EdgeState, EdgeTransition

    b, store, _, _ = paper_core
    suspension = EdgeTransition(
        release_hash=b.release.content_hash(),
        from_state=EdgeState.NORMAL,
        to_state=EdgeState.SUSPEND,
        fixture_version="paper.edge.synthetic.v1",
        evidence_hash="2" * 64,
        recorded_at=b.now,
        actor="system.fixture",
        actor_role="SYSTEM",
    )
    store.set_edge(b.account.account_ref, suspension, now=b.now)
    runtime = PaperStore(store.engine)
    relaxation = EdgeTransition.model_validate(
        suspension.model_dump()
        | {
            "from_state": EdgeState.SUSPEND,
            "to_state": EdgeState.NORMAL,
            "actor": "owner.fixture",
            "actor_role": "OWNER",
        }
    )
    with pytest.raises(ValueError):
        runtime.set_edge(b.account.account_ref, relaxation, now=b.now)
    with pytest.raises(ValueError, match="EDGE"):
        store.resume(b.account.account_ref, actor="owner.fixture", now=b.now)
    store.set_edge(b.account.account_ref, relaxation, now=b.now)
    assert store.account(b.account.account_ref).kill != KillLevel.K0
    history = [
        event for event in store.journal(b.account.account_ref) if event["kind"] == "EDGE_STATE"
    ]
    assert [event["data"]["to_state"] for event in history] == ["SUSPEND", "NORMAL"]


def test_paper_release_revocation_fences_existing_authorization(paper_core):
    from auvexo_alpha.domain.paper_lifecycle import ReleaseState, transition_release

    b, store, _, epoch = paper_core
    intent, _ = submit(b, store)
    suspended, transition = transition_release(
        b.release,
        ReleaseState.SUSPENDED,
        actor="owner.fixture",
        actor_role="OWNER",
        approved_at=b.now,
        evidence_hash="2" * 64,
    )
    store.register_release(suspended, fixture_registry=True, transition=transition, now=b.now)
    store.activate_release(b.account.account_ref, suspended, actor="owner.fixture", now=b.now)
    with pytest.raises(ValueError):
        store.claim(intent.content_hash(), epoch, now=b.now)
    assert store.outbox(intent.content_hash())["attempts"] == 0
    assert store.account(b.account.account_ref).kill != KillLevel.K0


@pytest.mark.parametrize(
    "mutation",
    (
        "content_hash=repeat('0',64)",
        "kind='CORRUPT_METADATA'",
        "recorded_at=recorded_at+interval '1 second'",
    ),
)
def test_paper_corrupt_journal_is_detected_and_never_authorizes(
    paper_database, paper_core, mutation
):
    b, store, _, _ = paper_core
    with psycopg.connect(dbname=paper_database, **admin_args()) as conn:
        # Adversarial administrator corruption of an isolated test fixture only.
        conn.execute("ALTER TABLE paper_journal DISABLE TRIGGER paper_journal_immutable")
        conn.execute(
            "UPDATE paper_journal SET " + mutation + " WHERE account_ref=%s",
            (b.account.account_ref,),
        )
        conn.execute("ALTER TABLE paper_journal ENABLE TRIGGER paper_journal_immutable")
    with pytest.raises(ValueError, match="CORRUPT"):
        store.journal(b.account.account_ref)
    with pytest.raises(ValueError, match="CORRUPT"):
        submit(b, store)


def test_paper_durable_write_failure_rolls_back_all_authority_records(paper_core):
    b, store, _, _ = paper_core
    b.account = store.account(b.account.account_ref)
    intent = b.rebind()

    def fail_after_intent(connection, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO paper_intent"):
            raise psycopg.errors.DiskFull("SYNTHETIC_DURABLE_WRITE_REFUSAL")

    event.listen(store.engine, "after_cursor_execute", fail_after_intent)
    try:
        with pytest.raises(DBAPIError) as refusal:
            store.authorize(intent, b.policy, b.market, b.spec, b.release, now=b.now)
        assert isinstance(refusal.value.orig, psycopg.errors.DiskFull)
        assert str(refusal.value.orig) == "SYNTHETIC_DURABLE_WRITE_REFUSAL"
    finally:
        event.remove(store.engine, "after_cursor_execute", fail_after_intent)
    assert not store.reservations(b.account.account_ref)
    with store.engine.connect() as conn:
        for table in ("paper_intent", "paper_authorization", "paper_reservation", "paper_outbox"):
            assert (
                conn.execute(
                    text(f"SELECT count(*) FROM {table} WHERE intent_hash=:hash"),
                    {"hash": intent.content_hash()},
                ).scalar_one()
                == 0
            )
    # Synthetic refusal proves transaction rollback; this does not fill the owner's disk.


def test_paper_unavailable_database_cannot_create_authority(paper_database, paper_core):
    b, store, _, _ = paper_core
    suffix = uuid4().hex[:20]
    missing_database = "auvexo_test_" + suffix
    missing_login = "auvexo_pw_" + suffix
    credential = replace(
        load_credentials(paper_database, "auvexo_paper"),
        database=missing_database,
        username=missing_login,
    )
    with psycopg.connect(dbname="postgres", **admin_args()) as conn:
        assert not conn.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname=%s)",
            (missing_database,),
        ).fetchone()[0]
        assert not conn.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=%s)", (missing_login,)
        ).fetchone()[0]
    before = snapshot(paper_database)
    account_before = store.account(b.account.account_ref).canonical_bytes()
    journal_before = store.journal(b.account.account_ref)
    with pytest.raises(PaperIdentityError, match="^PAPER_IDENTITY_CONNECTION_UNAVAILABLE$"):
        unavailable = engine_for(missing_database, "auvexo_paper", credential=credential)
        PaperStore(unavailable).authorize(
            b.intent, b.policy, b.market, b.spec, b.release, now=b.now
        )
    assert store.account(b.account.account_ref).canonical_bytes() == account_before
    assert store.journal(b.account.account_ref) == journal_before
    assert snapshot(paper_database) == before


def filled_open(bundle, store, truth, epoch):
    intent, approved = submit(bundle, store)
    assert approved.decision.status == "APPROVED"
    store.dispatch(intent.content_hash(), epoch, truth, now=bundle.now)
    truth.fill(
        intent.content_hash(),
        intent.quantity,
        intent.entry,
        account_ref=bundle.account.account_ref,
        now=bundle.now,
    )
    assert store.reconcile(bundle.account.account_ref, now=bundle.now)
    return intent, approved


def refreshed_market(bundle, now, price):
    return type(bundle.market).model_validate(
        bundle.market.model_dump()
        | dict(
            snapshot_id=uuid4(),
            as_of=now,
            available_at=now,
            fx_as_of=now,
            bid=Decimal(price),
            ask=Decimal(price),
        )
    )


@pytest.mark.parametrize("attack", ("same_instrument", "cross_instrument", "cross_account"))
def test_paper_open_reference_attack_never_changes_existing_position(paper_core, attack):
    b, store, truth, epoch = paper_core
    original, _ = filled_open(b, store, truth, epoch)
    before = tuple(p.canonical_bytes() for p in store.account(b.account.account_ref).positions)
    ref = paper_position_ref(b.account.account_ref, original.intent_id)
    if attack == "cross_account":
        other = fixture_bundle(account_ref="paper.other." + uuid4().hex)
        store.initialize(other.account, other.policy, other.release, now=other.now)
        other_epoch = store.acquire_writer(other.account.account_ref, now=other.now)
        assert store.reconcile(other.account.account_ref, now=other.now)
        store.resume(other.account.account_ref, actor="owner.fixture", now=other.now)
        other_intent, _ = filled_open(other, store, truth, other_epoch)
        ref = paper_position_ref(other.account.account_ref, other_intent.intent_id)
    b.account = store.account(b.account.account_ref)
    valid = b.rebind(intent_id=uuid4(), logical_key="attack." + uuid4().hex)
    changes = dict(position_ref=ref, stop=Decimal("49999"))
    if attack == "cross_instrument":
        changes["instrument_id"] = "paper.spot.ETHUSD"
    with pytest.raises(ValueError, match="OPEN_REQUIRES_NEW_POSITION"):
        PaperIntent.model_validate(valid.model_dump() | changes)
    forged = valid.model_copy(update=changes)
    with pytest.raises(ValueError, match="OPEN_REQUIRES_NEW_POSITION"):
        store.authorize(forged, b.policy, b.market, b.spec, b.release, now=b.now)
    with pytest.raises(ValueError):
        truth.record_order(forged, now=b.now, writer_epoch=epoch)
    with pytest.raises(DBAPIError) as invalid_open, store.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO paper_intent "
                "(intent_hash,account_ref,logical_key,action,payload,recorded_at,"
                "generated_position_ref) "
                "VALUES (:h,:a,:l,'OPEN',:p,:at,:ref)"
            ),
            dict(
                h=forged.content_hash(),
                a=forged.account_ref,
                l=forged.logical_key,
                p=forged.canonical_bytes().decode(),
                at=b.now,
                ref=paper_position_ref(forged.account_ref, forged.intent_id),
            ),
        )
    assert invalid_open.value.orig.sqlstate == "23514"
    assert (
        tuple(p.canonical_bytes() for p in store.account(b.account.account_ref).positions) == before
    )


def test_paper_distinct_opens_and_uuid_reuse_have_domain_and_database_protection(paper_core):
    b, store, truth, epoch = paper_core
    first, _ = filled_open(b, store, truth, epoch)
    before = tuple(p.canonical_bytes() for p in store.account(b.account.account_ref).positions)
    b.account = store.account(b.account.account_ref)
    duplicate = b.rebind(intent_id=first.intent_id, logical_key="uuid.reuse.new.logical")
    denied = store.authorize(duplicate, b.policy, b.market, b.spec, b.release, now=b.now)
    assert denied.decision.status == "DENIED"
    assert PaperReason.DUPLICATE_INTENT in denied.decision.reasons
    assert (
        tuple(p.canonical_bytes() for p in store.account(b.account.account_ref).positions) == before
    )
    with pytest.raises(DBAPIError) as collision, store.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO paper_intent "
                "(intent_hash,account_ref,logical_key,action,payload,recorded_at,"
                "generated_position_ref) "
                "VALUES (:hash,:account,:logical,'OPEN',:payload,:now,:position)"
            ),
            dict(
                hash=duplicate.content_hash(),
                account=b.account.account_ref,
                logical=duplicate.logical_key,
                payload=duplicate.canonical_bytes().decode(),
                now=b.now,
                position=paper_position_ref(b.account.account_ref, duplicate.intent_id),
            ),
        )
    assert collision.value.orig.sqlstate == "23505"
    from auvexo_alpha.domain.contracts import MoneyAction

    duplicate_close = b.rebind(
        intent_id=first.intent_id,
        logical_key="uuid.reuse.close",
        action=MoneyAction.CLOSE,
        side="SELL",
        position_ref=paper_position_ref(b.account.account_ref, first.intent_id),
    )
    with pytest.raises(DBAPIError) as duplicate_uuid, store.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO paper_intent "
                "(intent_hash,account_ref,logical_key,action,payload,recorded_at,"
                "generated_position_ref) "
                "VALUES (:h,:a,:l,'CLOSE',:p,:at,NULL)"
            ),
            dict(
                h=duplicate_close.content_hash(),
                a=duplicate_close.account_ref,
                l=duplicate_close.logical_key,
                p=duplicate_close.canonical_bytes().decode(),
                at=b.now,
            ),
        )
    assert duplicate_uuid.value.orig.sqlstate == "23505"
    assert duplicate_uuid.value.orig.diag.constraint_name == "paper_intent_account_uuid"
    second, _ = filled_open(b, store, truth, epoch)
    positions = store.account(b.account.account_ref).positions
    assert {p.position_ref for p in positions} == {
        paper_position_ref(b.account.account_ref, first.intent_id),
        paper_position_ref(b.account.account_ref, second.intent_id),
    }
    assert len(positions) == 2 and positions[0].quantity == positions[1].quantity == Decimal("0.01")
    assert all(p.stop_price == Decimal("49000") for p in positions)


def _uuid_collision_worker(arguments):
    database, bundle, identity, index, barrier = arguments
    engine = engine_for(database, "auvexo_paper")
    try:
        store = PaperStore(engine)
        bundle.account = store.account(bundle.account.account_ref)
        intent = bundle.rebind(intent_id=identity, logical_key="uuid.collision." + str(index))
        barrier.wait(timeout=30)
        decision = store.authorize(
            intent, bundle.policy, bundle.market, bundle.spec, bundle.release, now=bundle.now
        ).decision
        return decision.status
    finally:
        engine.dispose()


@pytest.mark.parametrize("pool_type", (ThreadPoolExecutor, ProcessPoolExecutor))
def test_paper_concurrent_same_uuid_different_keys_commit_exactly_once(
    paper_database, paper_core, pool_type
):
    b, store, _, _ = paper_core
    context = get_context("spawn")
    with context.Manager() as manager:
        barrier, identity = manager.Barrier(4), uuid4()
        jobs = [(paper_database, deepcopy(b), identity, i, barrier) for i in range(4)]
        options = {"mp_context": context} if pool_type is ProcessPoolExecutor else {}
        with pool_type(max_workers=4, **options) as pool:
            assert list(pool.map(_uuid_collision_worker, jobs)).count("APPROVED") == 1
    assert len(store.reservations(b.account.account_ref)) == 1
    with store.engine.connect() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM paper_intent WHERE account_ref=:a "
                    "AND payload::jsonb->>'intent_id'=:id"
                ),
                {"a": b.account.account_ref, "id": str(identity)},
            ).scalar_one()
            == 1
        )


@pytest.mark.parametrize("arrival", ("fill_then_reject", "reject_then_fill"))
@pytest.mark.parametrize("restart", (False, True))
@pytest.mark.parametrize("fault", ("NONE", "LOST_RESPONSE"))
def test_paper_rejected_with_fill_is_unknown_until_independent_terminal_proof(
    paper_core, arrival, restart, fault
):
    b, store, truth, epoch = paper_core
    intent, approved = submit(b, store)
    store.dispatch(intent.content_hash(), epoch, truth, now=b.now, fault=fault)
    event_id = "contradiction.fill." + uuid4().hex

    def fill():
        return truth.fill(
            intent.content_hash(),
            "0.004",
            intent.entry,
            account_ref=b.account.account_ref,
            now=b.now,
            event_id=event_id,
        )

    def reject():
        return truth.status(
            intent.content_hash(), "REJECTED", account_ref=b.account.account_ref, now=b.now
        )

    if arrival == "fill_then_reject":
        fill()
        fill()
        reject()
    else:
        reject()
        fill()
        fill()
    if restart:
        store.engine.dispose()
        store = PaperStore(store.engine, owner_engine=store.owner_engine)
        epoch = store.acquire_writer(b.account.account_ref, now=b.now)
    assert not store.reconcile(b.account.account_ref, now=b.now)
    assert store.outbox(intent.content_hash())["state"] == "UNKNOWN"
    account = store.account(b.account.account_ref)
    assert account.unknown_orders and not account.reconciled and account.kill != KillLevel.K0
    assert sum(p.quantity for p in account.positions) == Decimal("0.004")
    reservations = store.reservations(b.account.account_ref)
    assert sum(r.quantity for r in reservations) >= Decimal("0.006")
    actual_risk = sum(
        p.quantity * p.multiplier * abs(p.entry_price - p.stop_price) * p.adverse_fx
        + p.modeled_costs
        for p in account.positions
    )
    assert (
        actual_risk + sum(r.modeled_loss for r in reservations) >= approved.reservation.modeled_loss
    )
    with pytest.raises(ValueError):
        store.dispatch(intent.content_hash(), epoch, truth, now=b.now)
    with pytest.raises(ValueError):
        store.resume(b.account.account_ref, actor="owner.fixture", now=b.now)
    assert not store.reconcile(b.account.account_ref, now=b.now)
    truth.resolve(
        intent.content_hash(),
        "CANCELED",
        Decimal("0.004"),
        account_ref=b.account.account_ref,
        now=b.now,
        evidence_hash="3" * 64,
    )
    assert store.reconcile(b.account.account_ref, now=b.now)
    assert store.outbox(intent.content_hash())["state"] == "CANCELED"
    assert not store.reservations(b.account.account_ref)
    assert sum(p.quantity for p in store.account(b.account.account_ref).positions) == Decimal(
        "0.004"
    )
    assert store.account(b.account.account_ref).kill != KillLevel.K0
    assert any("REJECTED_WITH_FILL" in str(e["data"]) for e in store.journal(b.account.account_ref))
    # New contradictory authoritative facts invalidate an earlier finality proof.
    truth.fill(
        intent.content_hash(), "0.001", intent.entry, account_ref=b.account.account_ref, now=b.now
    )
    assert not store.reconcile(b.account.account_ref, now=b.now)
    assert store.outbox(intent.content_hash())["state"] == "UNKNOWN"
    assert sum(p.quantity for p in store.account(b.account.account_ref).positions) == Decimal(
        "0.005"
    )


def daily_breach_setup(bundle, store, truth, epoch):
    intent, _ = filled_open(bundle, store, truth, epoch)
    midnight = (bundle.now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    before = midnight - timedelta(seconds=1)
    truth.mark(bundle.account.account_ref, refreshed_market(bundle, before, "38000"), now=before)
    assert store.reconcile(bundle.account.account_ref, now=before)
    account = store.account(bundle.account.account_ref)
    assert account.day_start_equity - (account.equity - account.day_net_flows) > Decimal("100")
    assert account.kill == KillLevel.K2
    assert any("DAILY" in str(e["data"]).upper() for e in store.journal(bundle.account.account_ref))
    return intent, before, midnight


@pytest.mark.parametrize("restart", (False, True))
def test_paper_mark_loss_latches_before_midnight_until_explicit_healthy_owner_resume(
    paper_core, restart
):
    b, store, truth, epoch = paper_core
    _, before, midnight = daily_breach_setup(b, store, truth, epoch)
    breached = store.account(b.account.account_ref)
    with pytest.raises(ValueError, match="LOSS_LIMIT"):
        store.resume(b.account.account_ref, actor="owner.fixture", now=before)
    truth.adjustment(b.account.account_ref, "1000", now=before)
    assert store.reconcile(b.account.account_ref, now=before)
    with pytest.raises(ValueError, match="LOSS_LIMIT"):
        store.resume(b.account.account_ref, actor="owner.fixture", now=before)
    truth.mark(b.account.account_ref, refreshed_market(b, midnight, "38000"), now=midnight)
    assert store.reconcile(b.account.account_ref, now=midnight)
    store.roll_day(b.account.account_ref, now=midnight)
    rolled = store.account(b.account.account_ref)
    assert rolled.day_start_at == midnight and rolled.kill == KillLevel.K2
    assert rolled.high_water_equity == breached.high_water_equity
    if restart:
        store.engine.dispose()
        store = PaperStore(store.engine, owner_engine=store.owner_engine)
        epoch = store.acquire_writer(b.account.account_ref, now=midnight)
        assert store.reconcile(b.account.account_ref, now=midnight)
    after = midnight + timedelta(seconds=1)
    truth.mark(b.account.account_ref, refreshed_market(b, after, "38000"), now=after)
    assert store.reconcile(b.account.account_ref, now=after)
    assert store.account(b.account.account_ref).kill == KillLevel.K2
    b.now = after
    b.market = refreshed_market(b, after, "38000")
    b.spec = type(b.spec).model_validate(b.spec.model_dump() | {"observed_at": after})
    b.intent = b.intent.model_copy(
        update={
            "created_at": after,
            "expires_at": after + timedelta(seconds=30),
            "entry": Decimal("38000"),
            "stop": Decimal("37000"),
        }
    )
    _, denied = submit(b, store)
    assert (
        denied.decision.status == "DENIED" and PaperReason.KILL_BLOCKED in denied.decision.reasons
    )
    store.resume(b.account.account_ref, actor="owner.fixture", now=after)
    assert store.account(b.account.account_ref).kill == KillLevel.K0
    _, approved = submit(b, store)
    assert approved.decision.status == "APPROVED"


def test_paper_rollover_does_not_clear_unresolved_unknown_cause(paper_core):
    b, store, truth, epoch = paper_core
    unknown, approved = submit(b, store)
    assert approved.decision.status == "APPROVED"
    store.dispatch(unknown.content_hash(), epoch, truth, now=b.now, fault="LOST_RESPONSE")
    midnight = (b.now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    truth.mark(b.account.account_ref, refreshed_market(b, midnight, "50000"), now=midnight)
    assert not store.reconcile(b.account.account_ref, now=midnight)
    with pytest.raises(ValueError):
        store.roll_day(b.account.account_ref, now=midnight)
    with pytest.raises(ValueError):
        store.resume(b.account.account_ref, actor="owner.fixture", now=midnight)
    assert store.account(b.account.account_ref).unknown_orders
    assert store.reservations(b.account.account_ref)


def test_paper_rollover_cannot_clear_drawdown_cause_with_daily_baseline(paper_core):
    b, store, truth, epoch = paper_core
    filled_open(b, store, truth, epoch)
    midnight = (b.now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    before = midnight - timedelta(seconds=1)
    truth.mark(b.account.account_ref, refreshed_market(b, before, "1"), now=before)
    assert store.reconcile(b.account.account_ref, now=before)
    account = store.account(b.account.account_ref)
    assert account.high_water_equity - account.equity > Decimal("500")
    assert account.kill == KillLevel.K2
    truth.mark(b.account.account_ref, refreshed_market(b, midnight, "1"), now=midnight)
    assert store.reconcile(b.account.account_ref, now=midnight)
    store.roll_day(b.account.account_ref, now=midnight)
    after = store.account(b.account.account_ref)
    assert after.day_start_equity == after.equity
    assert after.high_water_equity == account.high_water_equity
    assert after.kill == KillLevel.K2
    with pytest.raises(ValueError, match="LOSS_LIMIT"):
        store.resume(b.account.account_ref, actor="owner.fixture", now=midnight)


def test_paper_concurrent_midnight_mark_roll_and_open_cannot_escape_loss_latch(paper_core):
    b, store, truth, epoch = paper_core
    _, _, midnight = daily_breach_setup(b, store, truth, epoch)
    truth.mark(b.account.account_ref, refreshed_market(b, midnight, "38000"), now=midnight)
    barrier = Barrier(3)
    b.now = midnight
    b.market = refreshed_market(b, midnight, "38000")
    b.spec = type(b.spec).model_validate(b.spec.model_dump() | {"observed_at": midnight})
    b.account = store.account(b.account.account_ref)
    intent = b.rebind(
        intent_id=uuid4(),
        logical_key="midnight.race",
        created_at=midnight,
        expires_at=midnight + timedelta(seconds=30),
        entry=Decimal("38000"),
        stop=Decimal("37000"),
    )

    def mark_and_reconcile():
        barrier.wait(timeout=20)
        return store.reconcile(b.account.account_ref, now=midnight)

    def rollover():
        barrier.wait(timeout=20)
        try:
            store.roll_day(b.account.account_ref, now=midnight)
            return "ROLLED"
        except ValueError as failure:
            assert "UTC" in str(failure)
            return "FRESH_BOUNDARY_REFUSED"

    def opening():
        barrier.wait(timeout=20)
        return store.authorize(intent, b.policy, b.market, b.spec, b.release, now=midnight).decision

    with ThreadPoolExecutor(max_workers=3) as pool:
        pending = [pool.submit(mark_and_reconcile), pool.submit(rollover), pool.submit(opening)]
        outcomes = [future.result(timeout=30) for future in pending]
    assert outcomes[2].status == "DENIED"
    assert store.account(b.account.account_ref).kill >= KillLevel.K2
    assert not store.reservations(b.account.account_ref)


@pytest.mark.parametrize("boundary", ("contradiction_reconcile", "daily_reconcile", "day_roll"))
def test_paper_failure_during_risk_state_write_rolls_back_projection_and_journal(
    paper_core, boundary
):
    b, store, truth, epoch = paper_core
    if boundary == "contradiction_reconcile":
        intent, _ = submit(b, store)
        store.dispatch(intent.content_hash(), epoch, truth, now=b.now)
        truth.fill(
            intent.content_hash(),
            "0.004",
            intent.entry,
            account_ref=b.account.account_ref,
            now=b.now,
        )
        truth.status(
            intent.content_hash(), "REJECTED", account_ref=b.account.account_ref, now=b.now
        )

        def operation():
            return store.reconcile(b.account.account_ref, now=b.now)
    else:
        _, _, midnight = daily_breach_setup(b, store, truth, epoch)
        truth.mark(b.account.account_ref, refreshed_market(b, midnight, "38000"), now=midnight)
        if boundary == "day_roll":
            assert store.reconcile(b.account.account_ref, now=midnight)

            def operation():
                return store.roll_day(b.account.account_ref, now=midnight)
        else:

            def operation():
                return store.reconcile(b.account.account_ref, now=midnight)

    def projection_rows():
        with store.engine.connect() as conn:
            return [
                conn.execute(
                    text(
                        f"SELECT row_to_json(t)::text FROM {table} t "
                        "WHERE account_ref=:a ORDER BY row_to_json(t)::text"
                    ),
                    {"a": b.account.account_ref},
                ).all()
                for table in ("paper_account", "paper_reservation", "paper_outbox", "paper_journal")
            ]

    before = projection_rows()

    def fail_after_account(connection, cursor, statement, parameters, context, many):
        if statement.startswith("UPDATE paper_account"):
            raise psycopg.errors.DiskFull("SYNTHETIC_RISK_STATE_COMMIT_FAILURE")

    event.listen(store.engine, "after_cursor_execute", fail_after_account)
    try:
        with pytest.raises(DBAPIError) as refusal:
            operation()
        assert isinstance(refusal.value.orig, psycopg.errors.DiskFull)
        assert str(refusal.value.orig) == "SYNTHETIC_RISK_STATE_COMMIT_FAILURE"
    finally:
        event.remove(store.engine, "after_cursor_execute", fail_after_account)
    assert projection_rows() == before
    operation()
    account = store.account(b.account.account_ref)
    if boundary == "contradiction_reconcile":
        assert account.unknown_orders and not account.reconciled
        assert store.reservations(b.account.account_ref)
    else:
        assert account.kill >= KillLevel.K2


def financial_projection_bytes(account):
    """Health/lease metadata is separate from financial and original mark fields."""
    payload = account.model_dump(mode="json")
    fields = (
        "cash",
        "equity",
        "high_water_equity",
        "day_start_equity",
        "day_start_at",
        "day_net_flows",
        "net_flows_since_high_water",
        "positions",
    )
    return dumps(
        {key: payload[key] for key in fields}, sort_keys=True, separators=(",", ":")
    ).encode()


def marked_position(bundle, store, truth, epoch, *, fx="1.01"):
    filled_open(bundle, store, truth, epoch)
    instant = bundle.now + timedelta(seconds=1)
    market = refreshed_market(bundle, instant, "40000")
    market = type(market).model_validate(market.model_dump() | {"adverse_fx": Decimal(fx)})
    event_id = "mark.retention." + uuid4().hex
    truth.mark(bundle.account.account_ref, market, now=instant, event_id=event_id)
    assert store.reconcile(bundle.account.account_ref, now=instant)
    account = store.account(bundle.account.account_ref)
    assert account.positions[0].mark_price == Decimal("40000")
    assert account.positions[0].mark_as_of == instant
    assert account.positions[0].fx_as_of == instant
    assert account.positions[0].adverse_fx == Decimal(fx)
    fact = next(e for e in truth.events(bundle.account.account_ref) if e["event_id"] == event_id)
    assert account.positions[0].mark_available_at == market.available_at
    assert account.positions[0].mark_snapshot_hash == market.content_hash()
    assert account.positions[0].mark_fact_hash == fact["content_hash"]
    assert account.kill == KillLevel.K2
    return instant, market, event_id, financial_projection_bytes(account)


@pytest.mark.parametrize("restart", (False, True))
@pytest.mark.parametrize("fx", ("1.01", "0.99"))
def test_paper_stale_mark_and_fx_retain_exact_financial_bytes_across_replay(
    paper_core, restart, fx
):
    b, store, truth, epoch = paper_core
    fresh, market, _, expected = marked_position(b, store, truth, epoch, fx=fx)
    stale = fresh + timedelta(seconds=3)
    if restart:
        store.engine.dispose()
        store = PaperStore(store.engine, owner_engine=store.owner_engine)
        store.acquire_writer(b.account.account_ref, now=stale)
    count = len(truth.events(b.account.account_ref))
    for _ in range(3):
        assert not store.reconcile(b.account.account_ref, now=stale)
        account = store.account(b.account.account_ref)
        assert financial_projection_bytes(account) == expected
        assert account.kill == KillLevel.K2 and not account.reconciled
        assert account.positions[0].mark_as_of == market.as_of
        assert account.positions[0].fx_as_of == market.fx_as_of
    assert len(truth.events(b.account.account_ref)) == count
    b.account = store.account(b.account.account_ref)
    intent = b.rebind(
        intent_id=uuid4(),
        logical_key="stale.denied",
        created_at=stale,
        expires_at=stale + timedelta(seconds=30),
    )
    denied = store.authorize(intent, b.policy, b.market, b.spec, b.release, now=stale)
    assert denied.decision.status == "DENIED"
    assert PaperReason.ACCOUNT_UNRECONCILED in denied.decision.reasons
    assert financial_projection_bytes(store.account(b.account.account_ref)) == expected


def test_paper_fx_can_become_stale_before_price_without_reverting_conversion(paper_core):
    b, store, truth, epoch = paper_core
    filled_open(b, store, truth, epoch)
    fresh = b.now + timedelta(seconds=1)
    market = refreshed_market(b, fresh, "40000")
    market = type(market).model_validate(market.model_dump() | {"fx_as_of": b.now})
    truth.mark(b.account.account_ref, market, now=fresh)
    assert store.reconcile(b.account.account_ref, now=fresh)
    expected = financial_projection_bytes(store.account(b.account.account_ref))
    fx_stale = fresh + timedelta(seconds=2)
    assert (fx_stale - market.as_of).total_seconds() == b.policy.max_market_age_seconds
    assert (fx_stale - market.fx_as_of).total_seconds() > b.policy.max_fx_age_seconds
    assert not store.reconcile(b.account.account_ref, now=fx_stale)
    account = store.account(b.account.account_ref)
    assert financial_projection_bytes(account) == expected
    assert account.positions[0].adverse_fx == Decimal("1.01")
    assert account.positions[0].fx_as_of == b.now
    assert account.kill == KillLevel.K2


@pytest.mark.parametrize("older_event", ("duplicate_same_fact", "older_mark"))
def test_paper_duplicate_or_older_market_fact_cannot_rewind_latest_observed_mark(
    paper_core, older_event
):
    b, store, truth, epoch = paper_core
    fresh, market, event_id, expected = marked_position(b, store, truth, epoch)
    later = fresh + timedelta(microseconds=1)
    if older_event == "duplicate_same_fact":
        truth.mark(b.account.account_ref, market, now=fresh, event_id=event_id)
    else:
        old = refreshed_market(b, b.now - timedelta(seconds=1), "49000")
        truth.mark(b.account.account_ref, old, now=later)
    assert store.reconcile(b.account.account_ref, now=later)
    assert financial_projection_bytes(store.account(b.account.account_ref)) == expected
    assert not store.reconcile(b.account.account_ref, now=fresh + timedelta(seconds=3))
    assert financial_projection_bytes(store.account(b.account.account_ref)) == expected


def test_paper_later_valid_mark_changes_valuation_once_without_clearing_loss_latch(paper_core):
    b, store, truth, epoch = paper_core
    fresh, _, _, old_financial = marked_position(b, store, truth, epoch)
    stale = fresh + timedelta(seconds=3)
    assert not store.reconcile(b.account.account_ref, now=stale)
    newer = refreshed_market(b, stale, "39000")
    truth.mark(b.account.account_ref, newer, now=stale)
    assert store.reconcile(b.account.account_ref, now=stale)
    account = store.account(b.account.account_ref)
    assert account.positions[0].mark_price == Decimal("39000")
    assert account.positions[0].mark_as_of == stale
    assert account.equity == Decimal("9887.1325")
    new_financial = financial_projection_bytes(account)
    assert new_financial != old_financial and account.kill == KillLevel.K2
    assert store.reconcile(b.account.account_ref, now=stale)
    assert financial_projection_bytes(store.account(b.account.account_ref)) == new_financial
    with pytest.raises(ValueError, match="LOSS_LIMIT"):
        store.resume(b.account.account_ref, actor="owner.fixture", now=stale)


@pytest.mark.parametrize(
    "attack",
    ("future", "wrong_instrument", "wrong_account", "same_time_conflict", "same_time_fx_conflict"),
)
def test_paper_invalid_or_conflicting_mark_is_refused_without_financial_mutation(
    paper_core, attack
):
    b, store, truth, epoch = paper_core
    fresh, market, _, expected = marked_position(b, store, truth, epoch)
    target = b.account.account_ref
    changes = {"snapshot_id": uuid4()}
    if attack == "future":
        changes.update(
            as_of=fresh + timedelta(seconds=1),
            available_at=fresh + timedelta(seconds=1),
            fx_as_of=fresh + timedelta(seconds=1),
        )
    elif attack == "wrong_instrument":
        changes["instrument_id"] = "paper.spot.UNRELATED"
    elif attack == "wrong_account":
        target = "paper.unregistered." + uuid4().hex
    elif attack == "same_time_conflict":
        changes.update(bid=Decimal("45000"), ask=Decimal("45000"))
    else:
        changes["adverse_fx"] = Decimal("1.02")
    invalid = type(market).model_validate(market.model_dump() | changes)
    event_count = len(truth.events(b.account.account_ref))
    with pytest.raises(ValueError):
        truth.mark(target, invalid, now=fresh)
    assert len(truth.events(b.account.account_ref)) == event_count
    assert financial_projection_bytes(store.account(b.account.account_ref)) == expected
    if attack == "future":
        assert not store.reconcile(b.account.account_ref, now=fresh + timedelta(seconds=3))
        assert financial_projection_bytes(store.account(b.account.account_ref)) == expected


@pytest.mark.parametrize("timestamps", ("missing", "stale"))
def test_paper_missing_conversion_without_prior_usable_mark_remains_unpriceable(
    paper_core, timestamps
):
    from auvexo_alpha.domain.paper import PaperPosition

    b, store, truth, _ = paper_core
    external = PaperPosition(
        position_ref="external.unpriceable.fixture",
        instrument_id=b.intent.instrument_id,
        bucket="crypto",
        quantity=Decimal("0.002"),
        entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
        stop_price=Decimal("49000"),
        mark_as_of=None if timestamps == "missing" else b.now - timedelta(seconds=10),
        fx_as_of=None if timestamps == "missing" else b.now - timedelta(seconds=10),
    )
    truth.external_position(b.account.account_ref, external, now=b.now)
    assert not store.reconcile(b.account.account_ref, now=b.now)
    before = financial_projection_bytes(store.account(b.account.account_ref))
    assert store.account(b.account.account_ref).positions[0].mark_as_of == external.mark_as_of
    assert store.account(b.account.account_ref).positions[0].fx_as_of == external.fx_as_of
    missing = type(b.market).model_validate(
        b.market.model_dump() | {"adverse_fx": None, "fx_as_of": None}
    )
    with pytest.raises(ValueError):
        truth.mark(b.account.account_ref, missing, now=b.now)
    assert not store.reconcile(b.account.account_ref, now=b.now + timedelta(seconds=3))
    assert financial_projection_bytes(store.account(b.account.account_ref)) == before
    _, denied = submit(b, store)
    assert denied.decision.status == "DENIED"


@pytest.mark.parametrize("arrival", ("market_then_external", "external_then_market"))
@pytest.mark.parametrize("conflict", ("price", "fx"))
def test_paper_same_timestamp_market_external_conflict_preserves_accepted_truth(
    paper_core, arrival, conflict
):
    from auvexo_alpha.domain.paper import PaperPosition

    b, store, truth, epoch = paper_core
    filled_open(b, store, truth, epoch)
    instant = b.now + timedelta(seconds=1)
    market = refreshed_market(b, instant, "40000")
    external = PaperPosition(
        position_ref="external.conflicting.mark.fixture",
        instrument_id=b.intent.instrument_id,
        bucket="crypto",
        quantity=Decimal("0.002"),
        entry_price=Decimal("50000"),
        mark_price=Decimal("45000") if conflict == "price" else market.bid,
        stop_price=Decimal("39000"),
        adverse_fx=Decimal("1.02") if conflict == "fx" else market.adverse_fx,
        mark_as_of=instant,
        mark_available_at=instant,
        fx_as_of=instant,
    )

    def append_market():
        truth.mark(b.account.account_ref, market, now=instant)

    def append_external():
        truth.external_position(b.account.account_ref, external, now=instant)

    first, conflicting = (
        (append_market, append_external)
        if arrival == "market_then_external"
        else (append_external, append_market)
    )
    first()
    store.reconcile(b.account.account_ref, now=instant)
    expected = financial_projection_bytes(store.account(b.account.account_ref))
    events = truth.events(b.account.account_ref)
    with pytest.raises(ValueError, match="CONFLICTING_VIRTUAL_MARK_TIMESTAMP"):
        conflicting()
    assert truth.events(b.account.account_ref) == events
    assert financial_projection_bytes(store.account(b.account.account_ref)) == expected
    store.reconcile(b.account.account_ref, now=instant)
    assert financial_projection_bytes(store.account(b.account.account_ref)) == expected


def test_paper_baseline_mark_requires_independent_position_scope_and_refuses_other_instrument(
    paper_core,
):
    from auvexo_alpha.domain.paper import PaperPosition

    _, store, truth, _ = paper_core
    b = fixture_bundle(account_ref="paper.baseline." + uuid4().hex)
    position = PaperPosition(
        position_ref="baseline.independently.confirmed.fixture",
        instrument_id=b.intent.instrument_id,
        bucket="crypto",
        quantity=Decimal("0.002"),
        entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
        stop_price=Decimal("49000"),
        adverse_fx=Decimal("1.01"),
        mark_as_of=b.now,
        mark_available_at=b.now,
        fx_as_of=b.now,
    )
    b.account = type(b.account).model_validate(
        b.account.model_dump() | {"cash": Decimal("9899"), "positions": (position,)}
    )
    store.initialize(b.account, b.policy, b.release, now=b.now)
    store.acquire_writer(b.account.account_ref, now=b.now)
    assert store.reconcile(b.account.account_ref, now=b.now)
    baseline = financial_projection_bytes(store.account(b.account.account_ref))
    instant = b.now + timedelta(seconds=1)
    market = refreshed_market(b, instant, "51000")
    with pytest.raises(ValueError, match="VIRTUAL_MARK_INSTRUMENT_SCOPE_DENIED"):
        truth.mark(b.account.account_ref, market, now=instant)
    assert truth.events(b.account.account_ref) == []
    assert financial_projection_bytes(store.account(b.account.account_ref)) == baseline

    truth.external_position(b.account.account_ref, position, now=instant)
    truth.mark(b.account.account_ref, market, now=instant)
    store.reconcile(b.account.account_ref, now=instant)
    account = store.account(b.account.account_ref)
    assert len(account.positions) == 1
    assert account.positions[0].mark_price == Decimal("51000")
    assert account.positions[0].mark_as_of == instant
    assert account.positions[0].fx_as_of == instant
    assert account.positions[0].adverse_fx == Decimal("1.01")
    assert account.equity == Decimal("10002.02")
    accepted = financial_projection_bytes(account)
    events = truth.events(b.account.account_ref)
    unrelated = type(market).model_validate(
        market.model_dump() | {"snapshot_id": uuid4(), "instrument_id": "paper.spot.UNRELATED"}
    )
    with pytest.raises(ValueError, match="VIRTUAL_MARK_INSTRUMENT_SCOPE_DENIED"):
        truth.mark(b.account.account_ref, unrelated, now=instant)
    assert truth.events(b.account.account_ref) == events
    assert financial_projection_bytes(store.account(b.account.account_ref)) == accepted


@pytest.mark.parametrize("late_mark", ("older", "missing_timestamps"))
def test_paper_delayed_external_observation_cannot_erase_newer_observed_mark(paper_core, late_mark):
    from auvexo_alpha.domain.paper import PaperPosition

    b, store, truth, _ = paper_core
    fresh = b.now + timedelta(seconds=1)
    external = PaperPosition(
        position_ref="external.retained.mark.fixture",
        instrument_id=b.intent.instrument_id,
        bucket="crypto",
        quantity=Decimal("0.002"),
        entry_price=Decimal("50000"),
        mark_price=Decimal("40000"),
        stop_price=Decimal("39000"),
        adverse_fx=Decimal("1.01"),
        mark_as_of=fresh,
        mark_available_at=fresh,
        fx_as_of=fresh,
    )
    truth.external_position(b.account.account_ref, external, now=fresh)
    store.reconcile(b.account.account_ref, now=fresh)
    accepted = store.account(b.account.account_ref)
    assert accepted.positions[0].mark_price == Decimal("40000")
    expected = financial_projection_bytes(accepted)
    later = fresh + timedelta(microseconds=1)
    delayed = type(external).model_validate(
        external.model_dump()
        | {
            "mark_price": Decimal("49000"),
            "adverse_fx": Decimal("1.02"),
            "mark_as_of": b.now if late_mark == "older" else None,
            "fx_as_of": b.now if late_mark == "older" else None,
            "mark_available_at": b.now if late_mark == "older" else None,
        }
    )
    truth.external_position(b.account.account_ref, delayed, now=later)
    store.reconcile(b.account.account_ref, now=later)
    account = store.account(b.account.account_ref)
    assert financial_projection_bytes(account) == expected
    assert account.positions[0] == accepted.positions[0]
    assert account.positions[0].mark_as_of == fresh
    assert account.positions[0].fx_as_of == fresh
    assert account.positions[0].adverse_fx == Decimal("1.01")
    assert not store.reconcile(b.account.account_ref, now=fresh + timedelta(seconds=3))
    assert financial_projection_bytes(store.account(b.account.account_ref)) == expected


def test_paper_reconciliation_clock_before_observed_truth_is_refused_without_rewind(paper_core):
    b, store, truth, epoch = paper_core
    fresh, _, _, expected = marked_position(b, store, truth, epoch)
    events = truth.events(b.account.account_ref)
    with pytest.raises(ValueError, match="PAPER_RECONCILIATION_CLOCK_BEFORE_TRUTH"):
        store.reconcile(b.account.account_ref, now=fresh - timedelta(microseconds=1))
    assert truth.events(b.account.account_ref) == events
    assert financial_projection_bytes(store.account(b.account.account_ref)) == expected


def test_paper_external_position_reference_cannot_change_instrument_or_inherit_mark(paper_core):
    from auvexo_alpha.domain.paper import PaperPosition

    b, store, truth, _ = paper_core
    external = PaperPosition(
        position_ref="external.instrument.bound.fixture",
        instrument_id=b.intent.instrument_id,
        bucket="crypto",
        quantity=Decimal("0.002"),
        entry_price=Decimal("50000"),
        mark_price=Decimal("40000"),
        stop_price=Decimal("39000"),
        adverse_fx=Decimal("1.01"),
        mark_as_of=b.now,
        mark_available_at=b.now,
        fx_as_of=b.now,
    )
    truth.external_position(b.account.account_ref, external, now=b.now)
    store.reconcile(b.account.account_ref, now=b.now)
    expected = financial_projection_bytes(store.account(b.account.account_ref))
    events = truth.events(b.account.account_ref)
    forged = type(external).model_validate(
        external.model_dump() | {"instrument_id": "paper.spot.ETHUSD"}
    )
    with pytest.raises(ValueError, match="VIRTUAL_POSITION_INSTRUMENT_SCOPE_DENIED"):
        truth.external_position(b.account.account_ref, forged, now=b.now)
    assert truth.events(b.account.account_ref) == events
    assert financial_projection_bytes(store.account(b.account.account_ref)) == expected
