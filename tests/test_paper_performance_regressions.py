"""Real-PG safety equivalence for transaction-local and checkout roundtrip removal."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
from paper_fixtures import fixture_bundle
from psycopg import sql
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError

from auvexo_alpha.domain.paper import PaperReason
from auvexo_alpha.domain.paper_lifecycle import KillLevel
from auvexo_alpha.domain.paper_risk import assess_paper
from auvexo_alpha.infrastructure.paper_identity import PaperIdentityError
from auvexo_alpha.infrastructure.paper_store import PaperStore, _VerifiedJournal
from auvexo_alpha.infrastructure.paper_truth import PaperTruth
from tools.paper_local import (
    admin_args,
    engine_for,
    isolated_database,
    load_credentials,
    require_migration,
    snapshot,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def performance_database():
    with isolated_database() as name:
        require_migration(name)
        yield name


@pytest.fixture
def performance_core(performance_database):
    runtime = engine_for(performance_database, "auvexo_paper")
    owner = engine_for(performance_database, "auvexo_paper_owner")
    simulator = engine_for(performance_database, "auvexo_paper_truth")
    bundle = fixture_bundle(account_ref="paper.optimization." + uuid4().hex)
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


def proposal(bundle, store, **changes):
    bundle.account = store.account(bundle.account.account_ref)
    return bundle.rebind(intent_id=uuid4(), logical_key="optimization." + uuid4().hex, **changes)


def authorize(bundle, store, intent):
    return store.authorize(
        intent, bundle.policy, bundle.market, bundle.spec, bundle.release, now=bundle.now
    )


@pytest.mark.parametrize("branch", ("approved", "denied"))
def test_p4_one_verified_journal_per_authorization_and_fresh_next_transaction(
    performance_core, monkeypatch, branch
):
    b, store, _, _ = performance_core
    intent = proposal(b, store)
    if branch == "denied":
        intent = proposal(b, store, stop=Decimal("50001"))
    expected = assess_paper(intent, b.policy, b.market, b.spec, b.account, b.release, (), now=b.now)
    if expected.status == "DENIED":
        # Reviewed c0a470bb store boundary removes the kernel's diagnostic exposure
        # from denied submissions; every other decision field stays identical.
        expected = type(expected).model_validate(expected.model_dump() | {"exposure": None})
    original = PaperStore._journal
    checked = []

    def counted(connection, account_ref):
        checked.append((connection, connection.get_transaction(), account_ref))
        return original(connection, account_ref)

    monkeypatch.setattr(PaperStore, "_journal", staticmethod(counted))
    first = authorize(b, store, intent)
    assert first.decision == expected
    assert len(checked) == 1
    first_transaction = checked[0][1]
    second = authorize(b, store, intent)
    assert len(checked) == 2
    assert checked[1][1] is not first_transaction
    if branch == "approved":
        assert first.authorization and first.reservation
        assert second.decision.status == "DENIED"
        assert PaperReason.DUPLICATE_INTENT in second.decision.reasons
    else:
        assert first.authorization is first.reservation is None
        assert second.decision == first.decision
    monkeypatch.setattr(PaperStore, "_journal", staticmethod(original))
    journal = store.journal(b.account.account_ref)
    assert journal[-1]["kind"] == "DENIED"
    if branch == "approved":
        assert journal[-2]["kind"] == "AUTHORIZED"
        assert len(store.reservations(b.account.account_ref)) == 1
        assert store.outbox(intent.content_hash())["state"] == "RESERVED"
    else:
        assert not store.reservations(b.account.account_ref)


def test_p4_transaction_local_tail_preserves_multievent_loss_and_unconsumed_truth(performance_core):
    b, store, truth, epoch = performance_core
    intent = proposal(b, store)
    assert authorize(b, store, intent).decision.status == "APPROVED"
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
    assert store.account(b.account.account_ref).kill == KillLevel.K2
    pending = proposal(b, store)
    truth.adjustment(b.account.account_ref, "0", now=b.now)
    before = len(store.journal(b.account.account_ref))
    denied = authorize(b, store, pending)
    assert denied.decision.status == "DENIED"
    assert PaperReason.DAILY_LOSS_CAP in denied.decision.reasons
    assert PaperReason.ACCOUNT_UNRECONCILED in denied.decision.reasons
    journal = store.journal(b.account.account_ref)
    assert [row["kind"] for row in journal[before:]] == ["KILL_STATE", "KILL_STATE", "DENIED"]
    account = store.account(b.account.account_ref)
    assert account.kill == KillLevel.K2 and not account.reconciled
    assert account.equity == Decimal("9897.2325")
    assert not store.reservations(b.account.account_ref)


def test_p4_new_transaction_rechecks_corrupted_history_after_successful_authorization(
    performance_database, performance_core
):
    b, store, _, _ = performance_core
    intent = proposal(b, store)
    assert authorize(b, store, intent).decision.status == "APPROVED"
    next_intent = proposal(b, store)
    with psycopg.connect(dbname=performance_database, **admin_args()) as admin:
        admin.execute("ALTER TABLE paper_journal DISABLE TRIGGER paper_journal_immutable")
        admin.execute(
            "UPDATE paper_journal SET content_hash=repeat('0',64) WHERE account_ref=%s",
            (b.account.account_ref,),
        )
        admin.execute("ALTER TABLE paper_journal ENABLE TRIGGER paper_journal_immutable")
    before = snapshot(performance_database)
    with pytest.raises(ValueError, match="CORRUPT_PAPER_JOURNAL"):
        authorize(b, store, next_intent)
    assert snapshot(performance_database) == before


def test_p4_failed_journal_append_discards_local_tail_and_rolls_back_authority(
    performance_database, performance_core
):
    b, store, _, _ = performance_core
    intent = proposal(b, store)
    before = snapshot(performance_database)

    def fail_after_journal(connection, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO paper_journal"):
            raise psycopg.errors.DiskFull("SYNTHETIC_LOCAL_JOURNAL_TAIL_ROLLBACK")

    event.listen(store.engine, "after_cursor_execute", fail_after_journal)
    try:
        with pytest.raises(DBAPIError) as refusal:
            authorize(b, store, intent)
        assert isinstance(refusal.value.orig, psycopg.errors.DiskFull)
        assert str(refusal.value.orig) == "SYNTHETIC_LOCAL_JOURNAL_TAIL_ROLLBACK"
    finally:
        event.remove(store.engine, "after_cursor_execute", fail_after_journal)
    assert snapshot(performance_database) == before
    approved = authorize(b, store, intent)
    assert approved.decision.status == "APPROVED"
    assert len(store.reservations(b.account.account_ref)) == 1
    assert store.outbox(intent.content_hash())["state"] == "RESERVED"
    assert sum(row["kind"] == "AUTHORIZED" for row in store.journal(b.account.account_ref)) == 1


@pytest.mark.parametrize("escape", ("account", "connection", "new_transaction"))
def test_p4_verified_journal_context_cannot_escape_exact_transaction(performance_core, escape):
    b, store, _, _ = performance_core
    with store.engine.connect() as conn:
        transaction = conn.begin()
        store._lock(conn, b.account.account_ref)
        history = _VerifiedJournal(
            conn,
            conn.get_transaction(),
            b.account.account_ref,
            store._journal(conn, b.account.account_ref),
        )
        assert history.for_scope(conn, b.account.account_ref)
        if escape == "account":
            with pytest.raises(ValueError, match="PAPER_JOURNAL_CONTEXT_SCOPE_DENIED"):
                history.for_scope(conn, "paper.other.fixture")
        elif escape == "connection":
            with store.engine.begin() as other:
                with pytest.raises(ValueError, match="PAPER_JOURNAL_CONTEXT_SCOPE_DENIED"):
                    history.for_scope(other, b.account.account_ref)
        else:
            transaction.commit()
            with conn.begin():
                with pytest.raises(ValueError, match="PAPER_JOURNAL_CONTEXT_SCOPE_DENIED"):
                    history.for_scope(conn, b.account.account_ref)


def test_p4_reused_checkout_detects_all_committed_drift_in_original_reason_order(
    performance_database,
):
    group = "auvexo_paper"
    credential = load_credentials(performance_database, group)
    engine = engine_for(performance_database, group)
    try:
        with engine.connect() as conn:
            backend = conn.scalar(text("SELECT pg_backend_pid()"))
        with psycopg.connect(dbname=performance_database, **admin_args()) as admin:
            admin.execute(
                sql.SQL("ALTER ROLE {} CREATEDB").format(sql.Identifier(credential.username))
            )
            admin.execute(
                sql.SQL("GRANT auvexo_paper_truth TO {} WITH INHERIT TRUE, SET FALSE").format(
                    sql.Identifier(credential.username)
                )
            )
        with pytest.raises(
            PaperIdentityError, match="^PAPER_IDENTITY_SESSION_OR_ATTRIBUTES_DENIED$"
        ):
            with engine.connect():
                pytest.fail("Drifted pooled connection reached application code")
        with psycopg.connect(dbname=performance_database, **admin_args()) as admin:
            admin.execute(
                sql.SQL("ALTER ROLE {} NOCREATEDB").format(sql.Identifier(credential.username))
            )
        with pytest.raises(PaperIdentityError, match="^PAPER_IDENTITY_MEMBERSHIP_DENIED$"):
            with engine.connect():
                pytest.fail("Extra role membership reached application code")
    finally:
        with psycopg.connect(dbname=performance_database, **admin_args()) as admin:
            admin.execute(
                sql.SQL("ALTER ROLE {} NOCREATEDB").format(sql.Identifier(credential.username))
            )
            admin.execute(
                sql.SQL("REVOKE auvexo_paper_truth FROM {}").format(
                    sql.Identifier(credential.username)
                )
            )
        engine.dispose()
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT pg_backend_pid()")) != backend
        assert conn.scalar(text("SELECT current_user")) == credential.username
    engine.dispose()


def test_p4_transaction_local_history_keeps_duplicate_race_serialized(performance_core):
    b, store, _, _ = performance_core
    intent = proposal(b, store)
    barrier = Barrier(2)

    def competing_authorization():
        barrier.wait(timeout=20)
        return authorize(b, store, intent).decision

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: competing_authorization(), range(2)))
    assert sum(result.status == "APPROVED" for result in outcomes) == 1
    assert sum(PaperReason.DUPLICATE_INTENT in result.reasons for result in outcomes) == 1
    assert len(store.reservations(b.account.account_ref)) == 1
    assert sum(row["kind"] == "AUTHORIZED" for row in store.journal(b.account.account_ref)) == 1
