"""Real PostgreSQL, isolated synthetic read-only role; never operational campaign."""

import secrets
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest
from paper_fixtures import fixture_bundle
from psycopg import sql
from sqlalchemy import URL, create_engine, event
from sqlalchemy.exc import SQLAlchemyError

from auvexo_alpha.infrastructure.paper_store import PaperStore
from auvexo_alpha.infrastructure.terminal_paper import PostgresTerminalReads
from tools.paper_local import admin_args, engine_for, isolated_database, require_migration

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def read_projection():
    role = "auvexo_read_" + uuid4().hex[:20]
    password = secrets.token_hex(32)
    with isolated_database() as database:
        require_migration(database)
        with psycopg.connect(dbname="postgres", autocommit=True, **admin_args()) as conn:
            conn.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                ).format(sql.Identifier(role), sql.Literal(password))
            )
            conn.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(database), sql.Identifier(role)
                )
            )
        with psycopg.connect(dbname=database, autocommit=True, **admin_args()) as conn:
            conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
            conn.execute(
                sql.SQL(
                    "GRANT SELECT ON paper_account,paper_reservation,"
                    "paper_outbox,paper_journal TO {}"
                ).format(sql.Identifier(role))
            )
        engine = create_engine(
            URL.create(
                "postgresql+psycopg",
                username=role,
                password=password,
                host="127.0.0.1",
                port=int(admin_args()["port"]),
                database=database,
            ),
            hide_parameters=True,
        )
        runtime = engine_for(database, "auvexo_paper")
        owner = engine_for(database, "auvexo_paper_owner")
        b = fixture_bundle(account_ref="paper.read.synthetic")
        store = PaperStore(runtime, owner_engine=owner)
        store.initialize(b.account, b.policy, b.release, now=b.now)
        try:
            yield database, role, engine, store, b
        finally:
            engine.dispose()
            runtime.dispose()
            owner.dispose()
            with psycopg.connect(dbname=database, autocommit=True, **admin_args()) as conn:
                conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            with psycopg.connect(dbname="postgres", autocommit=True, **admin_args()) as conn:
                conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_terminal_pg_read_only_projection_preserves_ledger(read_projection):
    database, role, engine, store, b = read_projection
    projection = PostgresTerminalReads(engine, b.account.account_ref)
    with psycopg.connect(dbname=database, **admin_args()) as c:
        before = c.execute(
            "SELECT payload,writer_epoch,version,truth_cursor FROM paper_account"
        ).fetchall()
        journal_before = c.execute("SELECT count(*) FROM paper_journal").fetchone()
    queries = []

    def record(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        view = projection.paper(now=b.now)
        journal = projection.journal(now=b.now)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert view.freshness.state == "AVAILABLE" and view.balance == str(b.account.cash)
    assert view.active_reservations == 0 and view.kill == "K1"
    assert journal.events and all(len(e.evidence_hash) == 64 for e in journal.events)
    assert any("SET TRANSACTION READ ONLY" in q for q in queries)
    assert not any(
        q.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE", "TRUNCATE", "SELECT *"))
        for q in queries
    )
    with psycopg.connect(dbname=database, **admin_args()) as c:
        assert (
            c.execute(
                "SELECT payload,writer_epoch,version,truth_cursor FROM paper_account"
            ).fetchall()
            == before
        )
        assert c.execute("SELECT count(*) FROM paper_journal").fetchone() == journal_before
    with engine.connect() as c:
        with pytest.raises(SQLAlchemyError):
            c.exec_driver_sql("UPDATE paper_account SET reconciled=true")


def test_terminal_pg_stale_and_missing_not_empty_success(read_projection):
    _, _, engine, _, b = read_projection
    assert (
        PostgresTerminalReads(engine, b.account.account_ref)
        .paper(now=b.now + timedelta(minutes=10))
        .freshness.state
        == "STALE"
    )
    missing = PostgresTerminalReads(engine, "paper.missing").paper(now=b.now)
    assert (
        missing.freshness.state == "UNAVAILABLE"
        and missing.balance is None
        and missing.active_reservations is None
    )


def test_terminal_pg_write_privilege_denies_projection(read_projection):
    database, role, engine, _, b = read_projection
    with psycopg.connect(dbname=database, autocommit=True, **admin_args()) as c:
        c.execute(sql.SQL("GRANT UPDATE ON paper_account TO {}").format(sql.Identifier(role)))
    try:
        assert (
            PostgresTerminalReads(engine, b.account.account_ref).paper(now=b.now).freshness.state
            == "UNAVAILABLE"
        )
    finally:
        with psycopg.connect(dbname=database, autocommit=True, **admin_args()) as c:
            c.execute(
                sql.SQL("REVOKE UPDATE ON paper_account FROM {}").format(sql.Identifier(role))
            )


def test_terminal_pg_dependency_failure_redacted(read_projection):
    _, _, engine, _, b = read_projection

    def fail(*args, **kwargs):
        raise SQLAlchemyError("sensitive driver detail synthetic-only")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        paper = PostgresTerminalReads(engine, b.account.account_ref).paper(now=b.now)
        assert paper.freshness.state == "UNAVAILABLE" and "sensitive" not in paper.model_dump_json()
    finally:
        event.remove(engine, "before_cursor_execute", fail)


@pytest.mark.parametrize(
    "database,user",
    [
        ("auvexo_dev", "auvexo_read_" + "a" * 20),
        ("auvexo_paperobs_" + "a" * 20, "auvexo_read_" + "a" * 20),
        ("auvexo_test_" + "a" * 20, "auvexo_admin"),
    ],
)
def test_terminal_pg_identity_refuses_runtime_admin(database, user):
    engine = create_engine(URL.create("postgresql+psycopg", username=user, database=database))
    try:
        with pytest.raises(ValueError):
            PostgresTerminalReads(engine, "paper.synthetic")
    finally:
        engine.dispose()


def test_terminal_pg_reservation_projection_uses_existing_accepted_facts(read_projection):
    _, _, engine, store, original = read_projection
    b = fixture_bundle(account_ref="paper.read.reserved")
    store.initialize(b.account, b.policy, b.release, now=b.now)
    store.acquire_writer(b.account.account_ref, now=b.now)
    assert store.reconcile(b.account.account_ref, now=b.now)
    store.resume(b.account.account_ref, actor="owner.synthetic.readtest", now=b.now)
    b.account = store.account(b.account.account_ref)
    intent = b.rebind()
    approved = store.authorize(intent, b.policy, b.market, b.spec, b.release, now=b.now)
    assert approved.decision.status == "APPROVED"
    view = PostgresTerminalReads(engine, b.account.account_ref).paper(now=b.now)
    assert view.freshness.state == "AVAILABLE" and view.active_reservations == 1
    assert len(view.reservations) == 1
    assert view.reservations[0].intent_hash == intent.content_hash()
    assert view.reservations[0].state == "ACTIVE"
    assert view.pending[0].state == "RESERVED"
    assert "account_ref" not in view.model_dump_json()
