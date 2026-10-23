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
            pool_size=1,
            max_overflow=0,
            connect_args={"options": "-c timezone=UTC"},
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


def _assert_attestation_refused(engine, bundle):
    projection = PostgresTerminalReads(engine, bundle.account.account_ref)
    queries = []

    def record(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        paper = projection.paper(now=bundle.now)
        journal = projection.journal(now=bundle.now)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert paper.freshness.state == journal.freshness.state == "UNAVAILABLE"
    assert paper.balance is None and paper.reservations == () and journal.events == ()
    assert not any("FROM public.paper_" in q for q in queries)


def test_terminal_pg_attestation_exact_login_and_four_selects(read_projection):
    database, role, engine, _, b = read_projection
    with engine.connect() as c:
        assert c.exec_driver_sql(
            "SELECT session_user,current_user,current_database(),host(inet_server_addr()),"
            "inet_server_port(),current_setting('TimeZone')"
        ).one() == (role, role, database, "127.0.0.1", 55432, "UTC")
        tables = (
            c.exec_driver_sql(
                "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f') "
                "AND has_table_privilege(current_user,c.oid,'SELECT') ORDER BY c.relname"
            )
            .scalars()
            .all()
        )
    assert tables == ["paper_account", "paper_journal", "paper_outbox", "paper_reservation"]
    assert (
        PostgresTerminalReads(engine, b.account.account_ref).paper(now=b.now).freshness.state
        == "AVAILABLE"
    )


@pytest.mark.parametrize(
    "attribute",
    ["SUPERUSER", "CREATEDB", "CREATEROLE", "REPLICATION", "BYPASSRLS", "INHERIT", "NOLOGIN"],
)
def test_terminal_pg_attestation_role_attributes(read_projection, attribute):
    database, role, engine, _, b = read_projection
    with psycopg.connect(dbname=database, autocommit=True, **admin_args()) as c:
        c.execute(sql.SQL("ALTER ROLE {} " + attribute).format(sql.Identifier(role)))
    try:
        _assert_attestation_refused(engine, b)
    finally:
        with psycopg.connect(dbname=database, autocommit=True, **admin_args()) as c:
            c.execute(
                sql.SQL(
                    "ALTER ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOREPLICATION NOBYPASSRLS NOINHERIT"
                ).format(sql.Identifier(role))
            )


@pytest.mark.parametrize(
    "privilege,table",
    [
        ("SELECT", "data_manifest"),
        ("SELECT", "research_trial"),
        ("SELECT", "paper_truth_event"),
        ("SELECT (feed_key)", "data_event"),
        ("INSERT", "data_event"),
        ("UPDATE", "data_event"),
        ("DELETE", "data_event"),
        ("TRUNCATE", "data_event"),
        ("TRIGGER", "data_event"),
        ("REFERENCES", "data_event"),
        ("MAINTAIN", "data_event"),
        ("UPDATE (feed_key)", "data_event"),
    ],
)
def test_terminal_pg_attestation_extra_application_privileges(read_projection, privilege, table):
    database, role, engine, _, b = read_projection
    with psycopg.connect(dbname=database, autocommit=True, **admin_args()) as c:
        c.execute(
            sql.SQL("GRANT " + privilege + " ON public.{} TO {}").format(
                sql.Identifier(table), sql.Identifier(role)
            )
        )
    try:
        _assert_attestation_refused(engine, b)
    finally:
        with psycopg.connect(dbname=database, autocommit=True, **admin_args()) as c:
            c.execute(
                sql.SQL("REVOKE " + privilege + " ON public.{} FROM {}").format(
                    sql.Identifier(table), sql.Identifier(role)
                )
            )


def test_terminal_pg_attestation_missing_required_select(read_projection):
    database, role, engine, _, b = read_projection
    with psycopg.connect(dbname=database, autocommit=True, **admin_args()) as c:
        c.execute(
            sql.SQL("REVOKE SELECT ON public.paper_journal FROM {}").format(sql.Identifier(role))
        )
    try:
        _assert_attestation_refused(engine, b)
    finally:
        with psycopg.connect(dbname=database, autocommit=True, **admin_args()) as c:
            c.execute(
                sql.SQL("GRANT SELECT ON public.paper_journal TO {}").format(sql.Identifier(role))
            )


@pytest.mark.parametrize(
    "kind",
    [
        "schema_create",
        "schema_owner",
        "table_owner",
        "sequence_owner",
        "sequence_usage",
        "view_select",
        "materialized_select",
        "public_select",
        "grant_option",
    ],
)
def test_terminal_pg_attestation_schema_ownership_and_objects(read_projection, kind):
    database, role, engine, _, b = read_projection
    name = "read_scope_" + uuid4().hex[:16]
    with psycopg.connect(dbname=database, autocommit=True, **admin_args()) as c:
        if kind == "schema_create":
            c.execute(sql.SQL("GRANT CREATE ON SCHEMA public TO {}").format(sql.Identifier(role)))
        elif kind == "schema_owner":
            c.execute(
                sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(
                    sql.Identifier(name), sql.Identifier(role)
                )
            )
        elif kind == "table_owner":
            c.execute(sql.SQL("CREATE TABLE public.{}(id integer)").format(sql.Identifier(name)))
            c.execute(
                sql.SQL("ALTER TABLE public.{} OWNER TO {}").format(
                    sql.Identifier(name), sql.Identifier(role)
                )
            )
        elif kind.startswith("sequence"):
            c.execute(sql.SQL("CREATE SEQUENCE public.{}").format(sql.Identifier(name)))
            action = (
                "ALTER SEQUENCE public.{} OWNER TO {}"
                if kind == "sequence_owner"
                else "GRANT USAGE ON SEQUENCE public.{} TO {}"
            )
            c.execute(sql.SQL(action).format(sql.Identifier(name), sql.Identifier(role)))
        elif kind in ("view_select", "materialized_select", "public_select"):
            prefix = "MATERIALIZED " if kind == "materialized_select" else ""
            c.execute(
                sql.SQL("CREATE " + prefix + "VIEW public.{} AS SELECT 1 AS id").format(
                    sql.Identifier(name)
                )
            )
            target = sql.SQL("PUBLIC") if kind == "public_select" else sql.Identifier(role)
            c.execute(
                sql.SQL("GRANT SELECT ON public.{} TO {}").format(sql.Identifier(name), target)
            )
        else:
            c.execute(
                sql.SQL("GRANT SELECT ON public.paper_account TO {} WITH GRANT OPTION").format(
                    sql.Identifier(role)
                )
            )
    try:
        _assert_attestation_refused(engine, b)
    finally:
        with psycopg.connect(dbname=database, autocommit=True, **admin_args()) as c:
            if kind == "schema_create":
                c.execute(
                    sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(sql.Identifier(role))
                )
            elif kind == "schema_owner":
                c.execute(sql.SQL("DROP SCHEMA {}").format(sql.Identifier(name)))
            elif kind == "grant_option":
                c.execute(
                    sql.SQL(
                        "REVOKE GRANT OPTION FOR SELECT ON public.paper_account FROM {}"
                    ).format(sql.Identifier(role))
                )
            else:
                category = (
                    "SEQUENCE"
                    if kind.startswith("sequence")
                    else "TABLE"
                    if kind == "table_owner"
                    else "MATERIALIZED VIEW"
                    if kind == "materialized_select"
                    else "VIEW"
                )
                c.execute(sql.SQL("DROP " + category + " public.{}").format(sql.Identifier(name)))


@pytest.mark.parametrize("drift", ["membership", "current_user"])
def test_terminal_pg_attestation_set_role_capable_membership(read_projection, drift):
    database, role, engine, _, b = read_projection
    group = "read_expand_" + uuid4().hex[:20]
    with psycopg.connect(dbname=database, autocommit=True, **admin_args()) as c:
        c.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(group)))
        c.execute(
            sql.SQL("GRANT SELECT ON public.research_trial TO {}").format(sql.Identifier(group))
        )
        c.execute(
            sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE").format(
                sql.Identifier(group), sql.Identifier(role)
            )
        )
    try:
        with engine.connect() as c:
            assert not c.exec_driver_sql(
                "SELECT has_table_privilege(current_user,'public.research_trial','SELECT')"
            ).scalar_one()
            if drift == "current_user":
                c.exec_driver_sql('SET ROLE "' + group + '"')
                c.commit()
                assert c.exec_driver_sql("SELECT session_user,current_user").one() == (role, group)
        _assert_attestation_refused(engine, b)
    finally:
        with engine.connect() as c:
            c.exec_driver_sql("RESET ROLE")
            c.commit()
        with psycopg.connect(dbname=database, autocommit=True, **admin_args()) as c:
            c.execute(
                sql.SQL("REVOKE {} FROM {}").format(sql.Identifier(group), sql.Identifier(role))
            )
            c.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(group)))
            c.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(group)))


@pytest.mark.parametrize("wrong_database", [False, True])
def test_terminal_pg_attestation_actual_session_not_url(read_projection, wrong_database):
    database, role, engine, _, b = read_projection
    with isolated_database() as other:

        def creator():
            raw = psycopg.connect(dbname=other if wrong_database else database, **admin_args())
            raw.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
            raw.execute("SET TIME ZONE 'UTC'")
            raw.commit()
            return raw

        deceptive = create_engine(engine.url, creator=creator, hide_parameters=True)
        try:
            with deceptive.connect() as c:
                assert c.exec_driver_sql(
                    "SELECT session_user,current_user,current_database()"
                ).one() == ("auvexo_admin", role, other if wrong_database else database)
            _assert_attestation_refused(deceptive, b)
        finally:
            deceptive.dispose()


@pytest.mark.parametrize(
    "setting,value", [("timezone", "Asia/Karachi"), ("search_path", "pg_catalog,public")]
)
def test_terminal_pg_attestation_session_assumptions(read_projection, setting, value):
    _, _, engine, _, b = read_projection
    with engine.connect() as c:
        c.exec_driver_sql("SET " + setting + " TO '" + value + "'")
        c.commit()
    try:
        _assert_attestation_refused(engine, b)
    finally:
        with engine.connect() as c:
            c.exec_driver_sql("SET TIME ZONE 'UTC'")
            c.exec_driver_sql("SET search_path TO public")
            c.commit()


@pytest.mark.parametrize(
    "key,value",
    [
        ("host", "localhost"),
        ("host", "192.0.2.1"),
        ("port", 5432),
        ("database", "auvexo_dev"),
        ("database", "auvexo_paperobs_" + "a" * 20),
        ("username", "auvexo_admin"),
        ("username", "auvexo_read_bad"),
        ("drivername", "postgresql+psycopg2"),
        ("password", ""),
        ("query", {"options": "-c role=auvexo_admin"}),
        ("query", {"host": "192.0.2.1"}),
    ],
)
def test_terminal_pg_attestation_constructor_configuration(read_projection, key, value):
    _, _, good, _, _ = read_projection
    engine = create_engine(good.url)
    engine.url = engine.url.set(**{key: value})
    try:
        with pytest.raises(ValueError):
            PostgresTerminalReads(engine, "paper.synthetic")
    finally:
        engine.dispose()


def test_terminal_pg_attestation_engine_override_and_account(read_projection):
    _, _, good, _, _ = read_projection
    with pytest.raises(ValueError):
        PostgresTerminalReads(good, "../not-an-account")
    engine = create_engine(good.url, execution_options={"isolation_level": "AUTOCOMMIT"})
    try:
        with pytest.raises(ValueError):
            PostgresTerminalReads(engine, "paper.synthetic")
    finally:
        engine.dispose()


def test_terminal_pg_attestation_reuse_failure_rollback_and_reconnect(read_projection):
    database, role, engine, _, b = read_projection
    projection = PostgresTerminalReads(engine, b.account.account_ref)
    assert projection.paper(now=b.now).freshness.state == "AVAILABLE"
    with engine.connect() as c:
        original_pid = c.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
        with pytest.raises(SQLAlchemyError):
            c.exec_driver_sql("SELECT * FROM public.research_trial")
    assert projection.paper(now=b.now).freshness.state == "AVAILABLE"
    with engine.connect() as c:
        assert c.exec_driver_sql("SELECT pg_backend_pid()").scalar_one() == original_pid
    with psycopg.connect(dbname=database, autocommit=True, **admin_args()) as c:
        c.execute(
            sql.SQL("GRANT SELECT ON public.research_trial TO {}").format(sql.Identifier(role))
        )
    try:
        _assert_attestation_refused(engine, b)
    finally:
        with psycopg.connect(dbname=database, autocommit=True, **admin_args()) as c:
            c.execute(
                sql.SQL("REVOKE SELECT ON public.research_trial FROM {}").format(
                    sql.Identifier(role)
                )
            )
    assert projection.paper(now=b.now).freshness.state == "AVAILABLE"
    engine.dispose()
    assert projection.paper(now=b.now).freshness.state == "AVAILABLE"
    with engine.connect() as c:
        assert c.exec_driver_sql("SELECT pg_backend_pid()").scalar_one() != original_pid


def test_terminal_pg_attestation_actual_database_with_correct_direct_login(read_projection):
    _, role, engine, _, b = read_projection
    with isolated_database() as other:
        require_migration(other)
        with psycopg.connect(dbname="postgres", autocommit=True, **admin_args()) as c:
            c.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(other), sql.Identifier(role)
                )
            )
        with psycopg.connect(dbname=other, autocommit=True, **admin_args()) as c:
            c.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
            c.execute(
                sql.SQL(
                    "GRANT SELECT ON public.paper_account,public.paper_reservation,"
                    "public.paper_outbox,public.paper_journal TO {}"
                ).format(sql.Identifier(role))
            )

        def creator():
            return psycopg.connect(
                host="127.0.0.1",
                port=55432,
                user=role,
                password=engine.url.password,
                dbname=other,
                options="-c timezone=UTC",
            )

        deceptive = create_engine(engine.url, creator=creator, hide_parameters=True)
        try:
            with deceptive.connect() as c:
                assert c.exec_driver_sql(
                    "SELECT session_user,current_user,current_database()"
                ).one() == (role, role, other)
            _assert_attestation_refused(deceptive, b)
        finally:
            deceptive.dispose()
