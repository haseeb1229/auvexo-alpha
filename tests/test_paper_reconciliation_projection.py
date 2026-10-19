"""Real-PG pending-truth denials retain the latest locked safety projection."""

from datetime import timedelta
from decimal import Decimal
from json import dumps
from uuid import uuid4

import psycopg
import pytest
from paper_fixtures import fixture_bundle
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError

from auvexo_alpha.domain.contracts import MoneyAction
from auvexo_alpha.domain.paper import PaperAccountSnapshot, PaperReason
from auvexo_alpha.domain.paper_lifecycle import KillLevel
from auvexo_alpha.infrastructure.paper_store import PaperStore
from auvexo_alpha.infrastructure.paper_truth import PaperTruth
from tools.paper_local import engine_for, isolated_database, require_migration, snapshot

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def projection_database():
    with isolated_database() as database:
        require_migration(database)
        yield database


@pytest.fixture
def projection_factory(projection_database):
    runtime = engine_for(projection_database, "auvexo_paper")
    owner = engine_for(projection_database, "auvexo_paper_owner")
    simulator = engine_for(projection_database, "auvexo_paper_truth")
    store = PaperStore(runtime, owner_engine=owner)
    truth = PaperTruth(simulator)

    def create(loss):
        bundle = fixture_bundle(account_ref="paper.projection." + uuid4().hex)
        if loss != "none":
            bundle.account = PaperAccountSnapshot.model_validate(
                bundle.account.model_dump()
                | {
                    "cash": Decimal("9800"),
                    "equity": Decimal("9800"),
                    "day_start_equity": (
                        Decimal("9800") if loss == "drawdown" else Decimal("10000")
                    ),
                    "high_water_equity": (
                        Decimal("10000") if loss == "daily" else Decimal("11000")
                    ),
                }
            )
        store.initialize(bundle.account, bundle.policy, bundle.release, now=bundle.now)
        store.acquire_writer(bundle.account.account_ref, now=bundle.now)
        assert store.reconcile(bundle.account.account_ref, now=bundle.now)
        if loss == "none":
            store.resume(bundle.account.account_ref, actor="owner.fixture", now=bundle.now)
        bundle.account = store.account(bundle.account.account_ref)
        assert bundle.account.reconciled
        assert bundle.account.kill == (KillLevel.K0 if loss == "none" else KillLevel.K2)
        bundle.intent = bundle.rebind(intent_id=uuid4(), logical_key="projection." + uuid4().hex)
        return bundle, store, truth

    try:
        yield create
    finally:
        runtime.dispose()
        owner.dispose()
        simulator.dispose()


def authorize(bundle, store, intent=None):
    return store.authorize(
        intent or bundle.intent,
        bundle.policy,
        bundle.market,
        bundle.spec,
        bundle.release,
        now=bundle.now,
    )


def cursor_state(store, account_ref):
    with store.engine.connect() as conn:
        row = conn.execute(
            text("SELECT payload,truth_cursor FROM paper_account WHERE account_ref=:a"),
            {"a": account_ref},
        ).one()
        maximum = conn.scalar(
            text("SELECT COALESCE(max(sequence),0) FROM paper_truth_event WHERE account_ref=:a"),
            {"a": account_ref},
        )
    return PaperAccountSnapshot.model_validate_json(row[0]), row[1], maximum


def assert_no_authority(store, account_ref):
    with store.engine.connect() as conn:
        for table in ("paper_intent", "paper_reservation", "paper_outbox"):
            assert (
                conn.scalar(
                    text(f"SELECT count(*) FROM {table} WHERE account_ref=:a"), {"a": account_ref}
                )
                == 0
            )
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM paper_authorization a JOIN paper_intent i "
                    "ON i.intent_hash=a.intent_hash WHERE i.account_ref=:account"
                ),
                {"account": account_ref},
            )
            == 0
        )
    assert not store.reservations(account_ref)


def assert_projection(store, before, *, kill, cursor):
    durable, actual_cursor, maximum = cursor_state(store, before.account_ref)
    assert actual_cursor == cursor < maximum
    assert not durable.reconciled
    assert durable.kill == kill
    excluded = {"kill", "reconciled"}
    assert durable.model_dump(exclude=excluded) == before.model_dump(exclude=excluded)
    latest = next(
        row["data"]["account"]
        for row in reversed(store.journal(before.account_ref))
        if "account" in row["data"]
    )
    assert PaperAccountSnapshot.model_validate_json(dumps(latest)) == durable
    assert store.account(before.account_ref) == durable
    assert_no_authority(store, before.account_ref)


@pytest.mark.parametrize("loss", ("none", "daily", "drawdown", "both"))
@pytest.mark.parametrize("pending_count", (1, 3))
def test_p4_pending_truth_loss_denials_preserve_latest_projection_until_real_reconciliation(
    projection_factory, loss, pending_count
):
    b, store, truth = projection_factory(loss)
    before, cursor, _ = cursor_state(store, b.account.account_ref)
    for _ in range(pending_count):
        truth.adjustment(b.account.account_ref, "0", now=b.now)
    assert len(truth.events(b.account.account_ref)) == pending_count
    reasons = {PaperReason.ACCOUNT_UNRECONCILED}
    if loss in ("daily", "both"):
        reasons.add(PaperReason.DAILY_LOSS_CAP)
    if loss in ("drawdown", "both"):
        reasons.add(PaperReason.DRAWDOWN_CAP)
    kill = KillLevel.K1 if loss == "none" else KillLevel.K2
    for _ in range(3):
        result = authorize(b, store)
        assert result.decision.status == "DENIED"
        assert reasons.issubset(result.decision.reasons)
        assert result.authorization is result.reservation is None
        assert_projection(store, before, kill=kill, cursor=cursor)
        with pytest.raises(ValueError, match="PAPER_RECONCILIATION_REQUIRED"):
            store.resume(b.account.account_ref, actor="owner.fixture", now=b.now)
    # Successful parsing validates every canonical envelope/hash/previous-hash link.
    denials = [row for row in store.journal(b.account.account_ref) if row["kind"] == "DENIED"]
    assert len(denials) == 3
    assert all(row["data"]["decision"]["status"] == "DENIED" for row in denials)
    assert store.reconcile(b.account.account_ref, now=b.now)
    consumed, actual_cursor, maximum = cursor_state(store, b.account.account_ref)
    assert actual_cursor == maximum and actual_cursor > cursor
    assert consumed.reconciled and consumed.kill == kill
    assert_no_authority(store, b.account.account_ref)
    if loss == "none":
        store.resume(b.account.account_ref, actor="owner.fixture", now=b.now)
        assert store.account(b.account.account_ref).kill == KillLevel.K0
    else:
        with pytest.raises(ValueError, match="PAPER_LOSS_LIMIT_STILL_ACTIVE"):
            store.resume(b.account.account_ref, actor="owner.fixture", now=b.now)


def test_p4_consuming_truth_and_healthy_day_never_auto_clear_k2(projection_factory):
    b, store, truth = projection_factory("daily")
    truth.adjustment(b.account.account_ref, "0", now=b.now)
    assert authorize(b, store).decision.status == "DENIED"
    assert store.reconcile(b.account.account_ref, now=b.now)
    assert store.account(b.account.account_ref).kill == KillLevel.K2
    with pytest.raises(ValueError, match="PAPER_LOSS_LIMIT_STILL_ACTIVE"):
        store.resume(b.account.account_ref, actor="owner.fixture", now=b.now)
    midnight = (b.now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    assert store.reconcile(b.account.account_ref, now=midnight)
    store.roll_day(b.account.account_ref, now=midnight)
    healthy = store.account(b.account.account_ref)
    assert healthy.reconciled and healthy.kill == KillLevel.K2
    before = len(store.journal(b.account.account_ref))
    store.resume(b.account.account_ref, actor="owner.fixture", now=midnight)
    resumed = store.account(b.account.account_ref)
    assert resumed.kill == KillLevel.K0 and resumed.reconciled
    assert resumed.model_dump(exclude={"kill"}) == healthy.model_dump(exclude={"kill"})
    history = store.journal(b.account.account_ref)
    assert len(history) == before + 1 and history[-1]["kind"] == "OWNER_PAPER_RESUME"
    assert history[-1]["data"]["actor"] == "owner.fixture"
    assert_no_authority(store, b.account.account_ref)


def test_p4_amend_after_pending_truth_loss_denial_cannot_relax_or_issue_authority(
    projection_factory,
):
    b, store, truth = projection_factory("daily")
    before, cursor, _ = cursor_state(store, b.account.account_ref)
    truth.adjustment(b.account.account_ref, "0", now=b.now)
    assert authorize(b, store).decision.status == "DENIED"
    amendment = b.rebind(
        intent_id=uuid4(), logical_key="projection.amend." + uuid4().hex, action=MoneyAction.AMEND
    )
    result = authorize(b, store, amendment)
    assert result.decision.status == "DENIED"
    assert PaperReason.ACCOUNT_UNRECONCILED in result.decision.reasons
    assert result.authorization is result.reservation is None
    assert_projection(store, before, kill=KillLevel.K2, cursor=cursor)


@pytest.mark.parametrize("boundary", ("after_first_save", "before_denial", "denial_journal"))
def test_p4_pending_truth_loss_projection_failure_rolls_back_entire_transaction(
    projection_database, projection_factory, boundary
):
    b, store, truth = projection_factory("both")
    truth.adjustment(b.account.account_ref, "0", now=b.now)
    before = snapshot(projection_database)
    prior, cursor, _ = cursor_state(store, b.account.account_ref)
    fired = []

    def fail_at_boundary(connection, db_cursor, statement, parameters, context, many):
        reached = (
            (boundary == "after_first_save" and statement.startswith("UPDATE paper_account"))
            or (boundary == "before_denial" and statement.startswith("INSERT INTO paper_denial"))
            or (
                boundary == "denial_journal"
                and statement.startswith("INSERT INTO paper_journal")
                and parameters.get("k") == "DENIED"
            )
        )
        if reached and not fired:
            fired.append(boundary)
            raise psycopg.errors.DiskFull("SYNTHETIC_PROJECTION_ATOMIC_ROLLBACK")

    hook = "after_cursor_execute" if boundary == "after_first_save" else "before_cursor_execute"
    event.listen(store.engine, hook, fail_at_boundary)
    try:
        if boundary == "after_first_save":
            # SQLAlchemy wraps driver exceptions raised by the post-execute hook.
            with pytest.raises(DBAPIError) as refusal:
                authorize(b, store)
            assert isinstance(refusal.value.orig, psycopg.errors.DiskFull)
            assert str(refusal.value.orig) == "SYNTHETIC_PROJECTION_ATOMIC_ROLLBACK"
        else:
            # The pre-execute hook runs before SQLAlchemy's driver exception handler.
            with pytest.raises(psycopg.errors.DiskFull) as refusal:
                authorize(b, store)
            assert str(refusal.value) == "SYNTHETIC_PROJECTION_ATOMIC_ROLLBACK"
    finally:
        event.remove(store.engine, hook, fail_at_boundary)
    assert fired == [boundary]
    assert snapshot(projection_database) == before
    unchanged, unchanged_cursor, _ = cursor_state(store, b.account.account_ref)
    assert unchanged == prior and unchanged_cursor == cursor
    assert_no_authority(store, b.account.account_ref)
    result = authorize(b, store)
    assert result.decision.status == "DENIED"
    assert_projection(store, prior, kill=KillLevel.K2, cursor=cursor)
