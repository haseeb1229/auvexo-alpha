"""Real-PostgreSQL evidence for P-3 and P-8 to P-14 (ADR-032 OBV2-02, OBV2-07 to OBV2-11).

Synthetic engineering fixtures only; nothing here is market evidence.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest
from paper_fixtures import PaperFixture, fixture_bundle
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from auvexo_alpha.domain.contracts import MoneyAction
from auvexo_alpha.domain.paper import (
    PaperAccountSnapshot,
    PaperPolicy,
    PaperReason,
    spec_terms_hash,
)
from auvexo_alpha.domain.paper_lifecycle import KillLevel
from auvexo_alpha.infrastructure.database import SCHEMA_REVISION
from auvexo_alpha.infrastructure.paper_store import PaperStore
from auvexo_alpha.infrastructure.paper_truth import PaperTruth
from tools.paper_local import admin_args, engine_for, isolated_database, require_migration

pytestmark = pytest.mark.integration


@dataclass
class Core:
    b: PaperFixture
    store: PaperStore
    truth: PaperTruth
    epoch: int
    database: str

    @property
    def ref(self) -> str:
        return self.b.account.account_ref

    def submit(self, *, now: datetime | None = None, **changes: object):  # type: ignore[no-untyped-def]
        self.b.account = self.store.account(self.ref)
        intent = self.b.rebind(intent_id=uuid4(), logical_key="guard." + uuid4().hex, **changes)
        result = self.store.authorize(
            intent,
            self.b.policy,
            self.b.market,
            self.b.spec,
            self.b.release,
            now=now or self.b.now,
        )
        return intent, result

    def kinds(self) -> list[str]:
        return [event["kind"] for event in self.store.journal(self.ref)]


@pytest.fixture(scope="module")
def database() -> Iterator[str]:
    with isolated_database() as name:
        require_migration(name)
        yield name


@pytest.fixture
def engines(database: str) -> Iterator[tuple[Engine, Engine, Engine]]:
    runtime = engine_for(database, "auvexo_paper")
    owner = engine_for(database, "auvexo_paper_owner")
    simulator = engine_for(database, "auvexo_paper_truth")
    try:
        yield runtime, owner, simulator
    finally:
        runtime.dispose()
        owner.dispose()
        simulator.dispose()


def start(database: str, engines: tuple[Engine, Engine, Engine], b: PaperFixture) -> Core:
    runtime, owner, simulator = engines
    store = PaperStore(runtime, owner_engine=owner)
    truth = PaperTruth(simulator)
    store.initialize(b.account, b.policy, b.release, now=b.now)
    epoch = store.acquire_writer(b.account.account_ref, now=b.now)
    assert store.reconcile(b.account.account_ref, now=b.now)
    store.resume(b.account.account_ref, actor="owner.fixture", now=b.now)
    b.account = store.account(b.account.account_ref)
    return Core(b, store, truth, epoch, database)


@pytest.fixture
def core(database: str, engines: tuple[Engine, Engine, Engine]) -> Core:
    return start(database, engines, fixture_bundle(account_ref="paper.guard." + uuid4().hex))


def open_and_fill(core: Core, quantity: str = "0.01") -> str:
    intent, result = core.submit()
    assert result.decision.status == "APPROVED", result.decision.reasons
    core.store.dispatch(intent.content_hash(), core.epoch, core.truth, now=core.b.now)
    core.truth.fill(
        intent.content_hash(), quantity, intent.entry, account_ref=core.ref, now=core.b.now
    )
    assert core.store.reconcile(core.ref, now=core.b.now)
    return core.store.account(core.ref).positions[0].position_ref


def admin(database: str) -> psycopg.Connection:
    return psycopg.connect(dbname=database, **admin_args())


# --- Migration 0007 objects -------------------------------------------------------------


def test_migration_0007_objects_present(database: str) -> None:
    assert SCHEMA_REVISION == "0007_paper_state_guards"
    with admin(database) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (
            SCHEMA_REVISION,
        )
        triggers = {
            row[0]
            for row in conn.execute(
                "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal "
                "AND tgname LIKE 'paper_%transition_guard'"
            )
        }
        assert triggers == {
            "paper_account_transition_guard",
            "paper_outbox_transition_guard",
            "paper_reservation_transition_guard",
        }
        indexes = {row[0] for row in conn.execute("SELECT indexname FROM pg_indexes")}
        assert {"paper_intent_account_logical_key", "paper_journal_intent"} <= indexes
        check = conn.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname='paper_truth_event_kind_check'"
        ).fetchone()
        assert check is not None and "SPEC_OBSERVATION" in check[0]


# --- P-12: database transition guards ---------------------------------------------------


def forge(conn, account_ref: str, kind: str, data: dict[str, object], now: datetime) -> None:  # type: ignore[no-untyped-def]
    """A chain-valid journal row written directly by the runtime role, as a faulty or hostile
    runtime could: the 0007 guard judges the update it justifies, P-13 replay its content."""
    PaperStore._append(conn, account_ref, kind, data, now)


def save(conn, account: PaperAccountSnapshot, cursor: int | None = None) -> None:  # type: ignore[no-untyped-def]
    conn.execute(
        text(
            "UPDATE paper_account SET payload=:p,writer_epoch=:e,kill_level=:k,reconciled=:r,"
            "truth_cursor=COALESCE(:c,truth_cursor) WHERE account_ref=:a"
        ),
        {
            "p": account.canonical_bytes().decode(),
            "e": account.epoch,
            "k": account.kill.value,
            "r": account.reconciled,
            "c": cursor,
            "a": account.account_ref,
        },
    )


@pytest.mark.parametrize(
    ("kind", "changes", "cursor", "message"),
    [
        (None, {"kill": KillLevel.K3}, None, "UNJOURNALED"),
        (None, {"day_net_flows": Decimal("5")}, None, "UNJOURNALED"),
        ("KILL_STATE", {"high_water_equity": Decimal("20000")}, None, "NOT_ALLOWED"),
        ("KILL_STATE", {"day_start_equity": Decimal("1")}, None, "NOT_ALLOWED"),
        ("RECONCILIATION", {"day_start_equity": Decimal("1")}, 0, "NOT_ALLOWED"),
        ("WRITER_ACQUIRED_PAUSE_NEW", {"epoch": "+2", "kill": KillLevel.K1}, None, "WRITER"),
        ("RECONCILIATION", {"kill": KillLevel.K0}, 999_999, "CURSOR_TARGET_UNKNOWN"),
        ("UTC_DAY_ROLLOVER", {"day_start_equity": Decimal("1")}, None, "DAY_ROLL_INVALID"),
        ("OWNER_PAPER_RESUME", {}, None, "OWNER"),
    ],
)
def test_runtime_role_cannot_rewrite_account_outside_journaled_transitions(
    core: Core,
    kind: str | None,
    changes: dict[str, object],
    cursor: int | None,
    message: str,
) -> None:
    before = core.store.account(core.ref)
    payload = before.model_dump() | changes
    if changes.get("epoch") == "+2":
        payload["epoch"] = before.epoch + 2
    if "day_start_equity" in changes and kind == "UTC_DAY_ROLLOVER":
        payload["day_start_at"] = before.day_start_at + timedelta(days=1)
        payload["as_of"] = before.as_of + timedelta(days=1)
        payload["reconciled_at"] = before.reconciled_at
    forged = PaperAccountSnapshot.model_validate(payload)
    with pytest.raises(DBAPIError, match=message), core.store.engine.begin() as conn:
        if kind is not None:
            data: dict[str, object] = {"account": forged}
            if cursor is not None:
                data["truth_cursor"] = cursor
            forge(conn, core.ref, kind, data, core.b.now)
        save(conn, forged, cursor)
    assert core.store.account(core.ref) == before
    assert core.store.ledger_replay(core.ref).mismatch_count == 0


def test_truth_cursor_advances_only_to_an_existing_truth_event(core: Core) -> None:
    core.truth.adjustment(core.ref, "1", now=core.b.now)
    sequence = int(core.truth.events(core.ref)[-1]["sequence"])
    before = core.store.account(core.ref)
    data = {"account": before, "truth_cursor": sequence + 1}
    with pytest.raises(DBAPIError, match="CURSOR_TARGET_UNKNOWN"):
        with core.store.engine.begin() as conn:
            forge(conn, core.ref, "RECONCILIATION", data, core.b.now)
            save(conn, before, sequence + 1)
    # An existing target is accepted by the database, but the forged reconciliation claims
    # to consume a +1 adjustment without booking it; the independent replay counts that.
    with core.store.engine.begin() as conn:
        forge(conn, core.ref, "RECONCILIATION", data | {"truth_cursor": sequence}, core.b.now)
        save(conn, before, sequence)
    replay = core.store.ledger_replay(core.ref)
    assert replay.mismatch_count > 0
    assert any(field.endswith(".cash") or field.endswith(".equity") for field in replay.mismatches)


def test_outbox_and_reservation_cannot_change_without_their_journal_event(core: Core) -> None:
    intent, _ = core.submit()
    ih = intent.content_hash()
    with pytest.raises(DBAPIError, match="OUTBOX_TRANSITION_UNJOURNALED"):
        with core.store.engine.begin() as conn:
            conn.execute(
                text("UPDATE paper_outbox SET state='EXPIRED' WHERE intent_hash=:i"), {"i": ih}
            )
    with pytest.raises(DBAPIError, match="RESERVATION_TRANSITION_UNJOURNALED"):
        with core.store.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE paper_reservation SET payload=jsonb_set(payload::jsonb,"
                    "'{quantity}','\"0\"')::text WHERE intent_hash=:i"
                ),
                {"i": ih},
            )
    with pytest.raises(DBAPIError, match="IDENTITY_OR_REWIND"):
        with core.store.engine.begin() as conn:
            conn.execute(
                text("UPDATE paper_outbox SET writer_epoch=writer_epoch+1 WHERE intent_hash=:i"),
                {"i": ih},
            )
    assert core.store.outbox(ih)["state"] == "RESERVED"


def test_database_logical_key_uniqueness_equals_the_kernel(core: Core) -> None:
    intent, result = core.submit()
    assert result.decision.status == "APPROVED"
    # The kernel refuses any reuse of a logical key; so does the database, across actions.
    close = intent.model_copy(
        update={"intent_id": uuid4(), "action": MoneyAction.CLOSE, "side": "SELL"}
    )
    with pytest.raises(IntegrityError, match="paper_intent_account_logical_key"):
        with core.store.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO paper_intent (intent_hash,account_ref,logical_key,action,"
                    "payload,recorded_at) VALUES (:i,:a,:l,'CLOSE',:p,now())"
                ),
                {
                    "i": close.content_hash(),
                    "a": core.ref,
                    "l": close.logical_key,
                    "p": close.canonical_bytes().decode(),
                },
            )


# --- P-11: writer fencing on every write path -------------------------------------------


def test_writer_fencing_covers_every_runtime_write_path(core: Core) -> None:
    stale = core.store
    newer = PaperStore(core.store.engine, owner_engine=core.store.owner_engine)
    epoch = newer.acquire_writer(core.ref, now=core.b.now)
    assert epoch == core.epoch + 1
    intent = core.b.rebind(intent_id=uuid4(), logical_key="fence." + uuid4().hex)
    args = (intent, core.b.policy, core.b.market, core.b.spec, core.b.release)
    with pytest.raises(ValueError, match="STALE_PAPER_WRITER"):
        stale.authorize(*args, now=core.b.now)
    with pytest.raises(ValueError, match="STALE_PAPER_WRITER"):
        stale.reconcile(core.ref, now=core.b.now)
    with pytest.raises(ValueError, match="STALE_PAPER_WRITER"):
        stale.roll_flat_boundary(core.ref, now=core.b.now + timedelta(days=1))
    with pytest.raises(ValueError, match="STALE_PAPER_WRITER"):
        stale.roll_day(core.ref, now=core.b.now + timedelta(days=1))
    with pytest.raises(ValueError, match="STALE_PAPER_WRITER"):
        stale.authorize(*args, now=core.b.now, epoch=core.epoch)
    # A caller holding no epoch may reconcile (writer-independent) but never authorize.
    observer = PaperStore(core.store.engine)
    with pytest.raises(ValueError, match="PAPER_WRITER_EPOCH_REQUIRED"):
        observer.authorize(*args, now=core.b.now)
    assert observer.reconcile(core.ref, now=core.b.now)
    # Raising a kill level is fail-closed and stays available to the superseded writer.
    stale.set_kill(core.ref, KillLevel.K2, actor="runtime.stale.fixture", now=core.b.now)
    assert core.store.account(core.ref).kill == KillLevel.K2
    assert newer.authorize(*args, now=core.b.now).decision.status == "DENIED"
    assert "AUTHORIZED" not in core.kinds()


# --- P-8: reservation expiry ------------------------------------------------------------


def test_undispatched_reservation_released_at_expiry_after_crash(core: Core) -> None:
    intent, result = core.submit()
    ih = intent.content_hash()
    assert result.reservation is not None
    # Crash between authorize and dispatch: the process is gone, a new writer starts.
    restarted = PaperStore(core.store.engine, owner_engine=core.store.owner_engine)
    epoch = restarted.acquire_writer(core.ref, now=core.b.now)
    just_before = intent.expires_at - timedelta(microseconds=1)
    restarted.reconcile(core.ref, now=just_before)
    assert restarted.outbox(ih)["state"] == "RESERVED"
    assert len(restarted.reservations(core.ref)) == 1
    restarted.reconcile(core.ref, now=intent.expires_at)
    assert restarted.outbox(ih)["state"] == "EXPIRED"
    assert restarted.reservations(core.ref) == ()
    released = [
        event
        for event in restarted.journal(core.ref)
        if event["kind"] == "RECONCILED_ORDER" and event["intent_hash"] == ih
    ]
    assert len(released) == 1
    assert released[0]["data"]["reason"] == "RESERVATION_EXPIRED_UNDISPATCHED"
    assert released[0]["data"]["reservation"]["state"] == "RELEASED"
    # Idempotent: a later reconciliation journals nothing more for it, never re-opens it.
    restarted.reconcile(core.ref, now=intent.expires_at + timedelta(seconds=1))
    assert (
        len(
            [
                e
                for e in restarted.journal(core.ref)
                if e["kind"] == "RECONCILED_ORDER" and e["intent_hash"] == ih
            ]
        )
        == 1
    )
    assert restarted.outbox(ih)["state"] == "EXPIRED"
    with pytest.raises(ValueError):
        restarted.claim(ih, epoch, now=intent.expires_at - timedelta(seconds=1))
    assert restarted.outbox(ih)["attempts"] == 0
    assert restarted.ledger_replay(core.ref).mismatch_count == 0


# --- P-9: invalid truth is quarantined -------------------------------------------------


def test_invalid_account_fact_quarantined_once_then_reconciliation_proceeds(core: Core) -> None:
    before = core.store.account(core.ref)
    core.truth.adjustment(core.ref, "-20000", now=core.b.now)
    assert not core.store.reconcile(core.ref, now=core.b.now)
    account = core.store.account(core.ref)
    assert account.kill == KillLevel.K1 and account.cash == before.cash
    quarantine = [e for e in core.store.journal(core.ref) if e["kind"] == "TRUTH_QUARANTINE"]
    assert len(quarantine) == 1
    assert quarantine[0]["data"]["reason"] == "ValueError:VIRTUAL_NEGATIVE_CASH"
    assert quarantine[0]["data"]["truth_kind"] == "ADJUSTMENT"
    # Never deleted: the fact remains in truth; it is excluded, not erased.
    assert (
        core.truth.events(core.ref)[-1]["content_hash"]
        == quarantine[0]["data"]["truth_content_hash"]
    )
    assert core.store.reconcile(core.ref, now=core.b.now)
    assert core.kinds().count("TRUTH_QUARANTINE") == 1
    assert core.store.account(core.ref).kill == KillLevel.K1
    assert core.store.ledger_replay(core.ref).mismatch_count == 0


def test_invalid_order_fact_holds_worst_case_capacity_as_unknown(core: Core) -> None:
    intent, result = core.submit()
    ih = intent.content_hash()
    core.store.dispatch(ih, core.epoch, core.truth, now=core.b.now)
    core.truth.fill(ih, "0.02", intent.entry, account_ref=core.ref, now=core.b.now)
    for _ in range(2):
        assert not core.store.reconcile(core.ref, now=core.b.now)
    assert core.store.outbox(ih)["state"] == "UNKNOWN"
    reservation = core.store.reservations(core.ref)[0]
    assert reservation.state == "UNKNOWN"
    assert result.authorization is not None
    assert reservation.quantity == result.authorization.exposure.quantity
    account = core.store.account(core.ref)
    assert account.unknown_orders and account.kill >= KillLevel.K1 and not account.positions
    assert core.kinds().count("TRUTH_QUARANTINE") == 1
    assert core.store.ledger_replay(core.ref).mismatch_count == 0


# --- P-10: flat-boundary day roll -------------------------------------------------------


def next_day(core: Core, hour: int = 17) -> datetime:
    return (core.b.now + timedelta(days=1)).replace(hour=hour, minute=57)


def test_flat_boundary_roll_accepted_with_proof(core: Core) -> None:
    before = core.store.account(core.ref)
    later = next_day(core)
    epoch = core.store.acquire_writer(core.ref, now=later)
    assert core.store.reconcile(core.ref, now=later)
    core.store.roll_flat_boundary(core.ref, now=later)
    rolled = core.store.account(core.ref)
    assert rolled.day_start_at == later.replace(hour=0, minute=0)
    assert rolled.day_start_equity == before.equity and rolled.day_net_flows == 0
    assert rolled.kill == KillLevel.K1 and rolled.epoch == epoch
    event = core.store.journal(core.ref)[-1]
    assert event["kind"] == "FLAT_BOUNDARY_ROLL"
    proof = event["data"]["proof"]
    assert proof["rule"] == "FLAT_NO_FACT_SINCE_PRIOR_DAY_RECONCILIATION"
    assert Decimal(proof["journaled_equity"]) == before.equity
    with pytest.raises(ValueError, match="UTC_DAY_NOT_ADVANCED"):
        core.store.roll_flat_boundary(core.ref, now=later + timedelta(minutes=1))
    assert core.store.ledger_replay(core.ref).mismatch_count == 0


def _refusal(core: Core, later: datetime, expected: set[str]) -> None:
    before = core.store.account(core.ref)
    with pytest.raises(ValueError, match="FLAT_BOUNDARY_ROLL_REFUSED") as refused:
        core.store.roll_flat_boundary(core.ref, now=later)
    reasons = set(str(refused.value).split(":", 1)[1].split(","))
    assert expected <= reasons
    after = core.store.account(core.ref)
    assert after.day_start_at == before.day_start_at
    assert after.kill >= KillLevel.K1
    event = core.store.journal(core.ref)[-1]
    assert event["kind"] == "KILL_STATE"
    assert set(event["data"]["reasons"]) == reasons
    assert core.store.ledger_replay(core.ref).mismatch_count == 0


def test_flat_roll_refused_without_reconciliation_since_midnight(core: Core) -> None:
    _refusal(core, next_day(core), {"NOT_RECONCILED_SINCE_MIDNIGHT"})


def test_flat_roll_refused_after_a_fact_since_prior_day(core: Core) -> None:
    core.truth.adjustment(core.ref, "5", now=core.b.now + timedelta(hours=1))
    later = next_day(core)
    assert core.store.reconcile(core.ref, now=later)
    _refusal(core, later, {"TRUTH_AFTER_PRIOR_DAY_RECONCILIATION"})


def test_flat_roll_refused_with_unknown_order_and_reservation(core: Core) -> None:
    intent, _ = core.submit()
    core.store.dispatch(
        intent.content_hash(), core.epoch, core.truth, now=core.b.now, fault="LOST_RESPONSE"
    )
    later = next_day(core)
    assert not core.store.reconcile(core.ref, now=later)
    _refusal(core, later, {"UNKNOWN_ORDER", "ACTIVE_RESERVATION", "NOT_RECONCILED"})


def test_flat_roll_refused_with_open_position(core: Core) -> None:
    open_and_fill(core)
    later = next_day(core)
    market = core.b.market.model_copy(
        update={"snapshot_id": uuid4(), "as_of": later, "available_at": later, "fx_as_of": later}
    )
    core.truth.mark(core.ref, market, now=later)
    assert core.store.reconcile(core.ref, now=later)
    _refusal(core, later, {"NOT_FLAT"})


def _midnight(instant: datetime) -> datetime:
    return instant.replace(hour=0, minute=0, second=0, microsecond=0)


def test_flat_roll_at_the_current_database_day_is_accepted(core: Core) -> None:
    # The fixture account's day is 2026-10-18; rolling at the real current instant starts
    # the day that has begun on the database clock, the latest day the guard admits.
    current = datetime.now(UTC)
    core.store.acquire_writer(core.ref, now=current)
    assert core.store.reconcile(core.ref, now=current)
    core.store.roll_flat_boundary(core.ref, now=current)
    assert core.store.account(core.ref).day_start_at == _midnight(current)
    assert core.store.journal(core.ref)[-1]["kind"] == "FLAT_BOUNDARY_ROLL"
    assert core.store.ledger_replay(core.ref).mismatch_count == 0


def test_flat_roll_to_a_future_midnight_is_refused_by_the_database(core: Core) -> None:
    """A writer whose `now` runs ahead (a wrong clock or a hostile caller) passes every
    application check, but the database refuses to start a day that has not begun."""
    future = _midnight(datetime.now(UTC)) + timedelta(days=1, hours=17, minutes=57)
    core.store.acquire_writer(core.ref, now=future)
    assert core.store.reconcile(core.ref, now=future)
    before = core.store.account(core.ref)
    with pytest.raises(DBAPIError, match="PAPER_DAY_ROLL_INVALID"):
        core.store.roll_flat_boundary(core.ref, now=future)
    assert core.store.account(core.ref) == before
    assert core.store.journal(core.ref)[-1]["kind"] == "RECONCILIATION"
    assert core.store.ledger_replay(core.ref).mismatch_count == 0


@pytest.mark.parametrize("kind", ["FLAT_BOUNDARY_ROLL", "UTC_DAY_ROLLOVER"])
@pytest.mark.parametrize(
    ("day_offset", "recorded_offset"),
    [
        # Tomorrow's midnight, journaled at that future instant: replay would agree.
        (timedelta(days=1), timedelta(days=1, seconds=1)),
        # Tomorrow's midnight, journaled now: the day has not begun.
        (timedelta(days=1), timedelta(0)),
        # The day of a journaled instant two minutes ahead of the database clock.
        (None, timedelta(minutes=2)),
    ],
)
def test_forged_roll_cannot_start_a_day_ahead_of_the_database_clock(
    core: Core, kind: str, day_offset: timedelta | None, recorded_offset: timedelta
) -> None:
    """The runtime role writes the roll itself, after a reconciliation at a future instant
    (the store accepts the caller's time there), so only the new clock bound can refuse."""
    current = datetime.now(UTC)
    recorded_at = current + recorded_offset
    day_start = _midnight(current) + day_offset if day_offset else _midnight(recorded_at)
    assert core.store.reconcile(core.ref, now=max(recorded_at, day_start))
    before = core.store.account(core.ref)
    forged = PaperAccountSnapshot.model_validate(
        before.model_dump()
        | {
            "day_start_at": day_start,
            "day_start_equity": before.equity,
            "day_net_flows": Decimal("0"),
        }
    )
    with pytest.raises(DBAPIError, match="PAPER_DAY_ROLL_INVALID"):
        with core.store.engine.begin() as conn:
            forge(conn, core.ref, kind, {"account": forged}, recorded_at)
            save(conn, forged)
    assert core.store.account(core.ref) == before
    assert core.store.ledger_replay(core.ref).mismatch_count == 0


@pytest.mark.parametrize("kind", ["FLAT_BOUNDARY_ROLL", "UTC_DAY_ROLLOVER"])
def test_forged_roll_shape_at_the_current_day_is_admitted_and_replays(
    core: Core, kind: str
) -> None:
    """Control for the refusals above: the same runtime-written shape, for the day that has
    begun and journaled at the current instant, passes the guard and replays cleanly."""
    current = datetime.now(UTC)
    assert core.store.reconcile(core.ref, now=current)
    before = core.store.account(core.ref)
    admitted = PaperAccountSnapshot.model_validate(
        before.model_dump()
        | {
            "day_start_at": _midnight(current),
            "day_start_equity": before.equity,
            "day_net_flows": Decimal("0"),
        }
        | ({"as_of": current} if kind == "UTC_DAY_ROLLOVER" else {})
    )
    with core.store.engine.begin() as conn:
        forge(conn, core.ref, kind, {"account": admitted}, current)
        save(conn, admitted)
    assert core.store.account(core.ref).day_start_at == _midnight(current)
    assert core.store.ledger_replay(core.ref).mismatch_count == 0


def test_flat_roll_refused_with_unconsumed_truth(core: Core) -> None:
    later = next_day(core)
    assert core.store.reconcile(core.ref, now=later)
    core.truth.adjustment(core.ref, "1", now=later)
    _refusal(core, later, {"TRUTH_AFTER_RECONCILIATION"})


# --- P-3: trusted inputs ----------------------------------------------------------------


def trusted_bundle() -> PaperFixture:
    instant = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=2)
    b = fixture_bundle(account_ref="paper.trusted." + uuid4().hex, now=instant)
    b.intent = b.intent.model_copy(update={"expires_at": instant + timedelta(minutes=5)})
    # Test-only widened freshness so a slow host cannot fail a timing bound; the trust
    # checks under test do not depend on these ages.
    b.policy = PaperPolicy.model_validate(
        b.policy.model_dump()
        | {
            "input_trust": "STORE_VERIFIED",
            "pinned_spec_terms": (spec_terms_hash(b.spec),),
            "max_store_clock_skew_ms": 5000,
            "max_market_age_seconds": 60,
            "max_fx_age_seconds": 60,
            "max_account_age_seconds": 60,
        }
    )
    return b


def test_store_verified_authorization_requires_stored_mark_spec_and_clock(
    database: str, engines: tuple[Engine, Engine, Engine]
) -> None:
    core = start(database, engines, trusted_bundle())
    now = datetime.now(UTC)
    _, missing = core.submit(now=now)
    assert {PaperReason.MARKET_UNVERIFIED, PaperReason.SPEC_UNOBSERVED} <= set(
        missing.decision.reasons
    )
    core.truth.observe_spec(core.ref, core.b.spec, now=now)
    core.truth.mark(core.ref, core.b.market, now=now)
    # Unconsumed facts are not trusted: reconcile first.
    assert core.store.reconcile(core.ref, now=now)
    store_time = datetime.now(UTC)
    _, approved = core.submit(now=store_time)
    assert approved.decision.status == "APPROVED", approved.decision.reasons
    _, skewed = core.submit(now=store_time + timedelta(seconds=6))
    assert PaperReason.CLOCK_UNTRUSTED in skewed.decision.reasons
    original_market, original_spec = core.b.market, core.b.spec
    core.b.market = original_market.model_copy(update={"snapshot_id": uuid4()})
    _, unmarked = core.submit(now=datetime.now(UTC))
    assert set(unmarked.decision.reasons) == {PaperReason.MARKET_UNVERIFIED}
    core.b.market = original_market
    core.b.spec = original_spec.model_copy(
        update={"observed_at": original_spec.observed_at + timedelta(seconds=1)}
    )
    _, unobserved = core.submit(now=datetime.now(UTC))
    assert set(unobserved.decision.reasons) == {PaperReason.SPEC_UNOBSERVED}
    core.b.spec = original_spec.model_copy(update={"min_notional": Decimal("2")})
    observed_at = datetime.now(UTC)
    core.truth.observe_spec(core.ref, core.b.spec, now=observed_at)
    assert core.store.reconcile(core.ref, now=observed_at)
    _, drifted = core.submit(now=datetime.now(UTC))
    assert set(drifted.decision.reasons) == {PaperReason.SPEC_UNPINNED}


def test_store_verified_claim_refuses_untrusted_clock(
    database: str, engines: tuple[Engine, Engine, Engine]
) -> None:
    core = start(database, engines, trusted_bundle())
    now = datetime.now(UTC)
    core.truth.observe_spec(core.ref, core.b.spec, now=now)
    core.truth.mark(core.ref, core.b.market, now=now)
    assert core.store.reconcile(core.ref, now=now)
    intent, approved = core.submit(now=datetime.now(UTC))
    assert approved.decision.status == "APPROVED"
    with pytest.raises(ValueError, match="FRESHNESS_DENIED"):
        core.store.claim(
            intent.content_hash(), core.epoch, now=datetime.now(UTC) + timedelta(seconds=6)
        )
    assert core.store.claim(intent.content_hash(), core.epoch, now=datetime.now(UTC))


def test_legacy_policy_keeps_caller_supplied_inputs(core: Core) -> None:
    assert core.b.policy.input_trust == "CALLER_SUPPLIED"
    _, result = core.submit()
    assert result.decision.status == "APPROVED"


# --- P-13: ledger replay ---------------------------------------------------------------


def test_full_cycle_replays_with_zero_mismatches(core: Core) -> None:
    ref = open_and_fill(core)
    marked = core.b.now + timedelta(seconds=1)
    core.b.market = core.b.market.model_copy(
        update={
            "snapshot_id": uuid4(),
            "as_of": marked,
            "available_at": marked,
            "fx_as_of": marked,
            "bid": Decimal("50100"),
            "ask": Decimal("50100"),
        }
    )
    core.truth.mark(core.ref, core.b.market, now=marked)
    core.truth.adjustment(core.ref, "-100", now=marked)
    core.b.now = marked
    assert core.store.reconcile(core.ref, now=marked)
    close, result = core.submit(
        action=MoneyAction.CLOSE, side="SELL", quantity=Decimal("0.01"), position_ref=ref
    )
    assert result.decision.status == "APPROVED", result.decision.reasons
    core.store.dispatch(close.content_hash(), core.epoch, core.truth, now=marked)
    core.truth.fill(close.content_hash(), "0.01", "50100", account_ref=core.ref, now=marked)
    assert core.store.reconcile(core.ref, now=marked)
    account = core.store.account(core.ref)
    assert account.positions == ()
    # Open: 505 notional + 1.7675 fee. Close at 50100*1.01: +506.01 - 1.7675 fee
    # (505 entry notional * 35 bps). Withdrawal -100. 10000-506.7675+504.2425-100.
    assert account.cash == account.equity == Decimal("9897.475")
    replay = core.store.ledger_replay(core.ref)
    assert replay.mismatch_count == 0, replay.mismatches
    assert replay.truth_events == len(core.truth.events(core.ref))


@pytest.mark.parametrize(
    ("field", "value", "columns"),
    [
        ("cash", "10001", ()),
        ("equity", "10001", ()),
        ("day_start_equity", "1", ()),
        ("kill", "K0", ("kill_level",)),
    ],
)
def test_tampered_stored_account_is_counted_as_mismatch(
    core: Core, field: str, value: str, columns: tuple[str, ...]
) -> None:
    open_and_fill(core)
    if field == "kill":
        core.store.set_kill(core.ref, KillLevel.K2, actor="runtime.fixture", now=core.b.now)
    assert core.store.ledger_replay(core.ref).mismatch_count == 0
    with admin(core.database) as conn:
        conn.execute("ALTER TABLE paper_account DISABLE TRIGGER USER")
        try:
            conn.execute(
                "UPDATE paper_account SET payload=jsonb_set(payload::jsonb,%s,%s)::text"
                + (",kill_level=%s" if columns else "")
                + " WHERE account_ref=%s",
                ("{" + field + "}", json.dumps(value), *((value,) if columns else ()), core.ref),
            )
        finally:
            conn.execute("ALTER TABLE paper_account ENABLE TRIGGER USER")
    replay = core.store.ledger_replay(core.ref)
    assert "account." + field in replay.mismatches
    assert {"column." + column for column in columns} <= set(replay.mismatches)
    assert replay.mismatch_count == 1 + len(columns)
    with pytest.raises(ValueError, match="CORRUPT_PAPER_ACCOUNT"):
        core.store.account(core.ref)
