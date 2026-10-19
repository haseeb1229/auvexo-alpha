"""Security-first real PostgreSQL proof for directly authenticated PAPER service pools."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
from json import dumps
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
from paper_fixtures import fixture_bundle
from psycopg import sql
from sqlalchemy import URL, create_engine, text
from sqlalchemy.exc import DBAPIError

from auvexo_alpha.infrastructure.paper_identity import PaperIdentityError
from auvexo_alpha.infrastructure.paper_store import PaperStore
from auvexo_alpha.infrastructure.paper_truth import PaperTruth
from tools import paper_local

pytestmark = pytest.mark.integration

GROUPS = ("auvexo_paper", "auvexo_paper_owner", "auvexo_paper_truth")
DENIED_STARTUP = (ValueError, RuntimeError)


def test_identity_non_utc_pool_drift_refuses_checkout_and_reconnect_is_utc(identity_database):
    engine = paper_local.engine_for(identity_database, "auvexo_paper")
    credential = paper_local.load_credentials(identity_database, "auvexo_paper")
    try:
        with engine.begin() as conn:
            assert_identity(conn, credential)
            conn.execute(text("SET TIME ZONE 'Asia/Karachi'"))
        with pytest.raises(PaperIdentityError, match="^PAPER_IDENTITY_SESSION_TIMEZONE_DENIED$"):
            with engine.connect():
                pass
        engine.dispose()
        with engine.connect() as conn:
            assert_identity(conn, credential)
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def identity_database():
    with paper_local.isolated_database() as name:
        paper_local.require_migration(name)
        yield name


@pytest.fixture(scope="module")
def identity_fixture(identity_database):
    bundle = fixture_bundle(account_ref="paper.identity." + uuid4().hex)
    runtime = paper_local.engine_for(identity_database, "auvexo_paper")
    owner = paper_local.engine_for(identity_database, "auvexo_paper_owner")
    try:
        PaperStore(runtime, owner_engine=owner).initialize(
            bundle.account, bundle.policy, bundle.release, now=bundle.now
        )
    finally:
        runtime.dispose()
        owner.dispose()
    return bundle


def assert_identity(connection, credential):
    assert connection.execute(text("SELECT current_setting('TimeZone')")).scalar_one() == "UTC"
    row = connection.execute(
        text(
            "SELECT session_user,current_user,rolsuper,rolcreatedb,rolcreaterole,"
            "rolreplication,rolbypassrls,rolcanlogin,"
            "pg_has_role(session_user,'auvexo_admin','MEMBER') "
            "FROM pg_roles WHERE rolname=session_user"
        )
    ).one()
    assert row == (
        credential.username,
        credential.username,
        False,
        False,
        False,
        False,
        False,
        True,
        False,
    )
    assert row[0] != "auvexo_admin"
    memberships = connection.execute(
        text(
            "SELECT parent.rolname,membership.admin_option,membership.inherit_option,"
            "membership.set_option FROM pg_auth_members membership "
            "JOIN pg_roles child ON child.oid=membership.member "
            "JOIN pg_roles parent ON parent.oid=membership.roleid "
            "WHERE child.rolname=session_user ORDER BY parent.rolname"
        )
    ).all()
    assert memberships == [(credential.role, False, True, False)]


def allowed_write(connection, group, bundle):
    if group == "auvexo_paper":
        payload = '{"evidence_kind":"SYNTHETIC_IDENTITY_BOUNDARY"}'
        connection.execute(
            text("INSERT INTO paper_denial VALUES (:id,:account,:intent,:hash,:payload,:now)"),
            dict(
                id=str(uuid4()),
                account=bundle.account.account_ref,
                intent=bundle.intent.content_hash(),
                hash=sha256(payload.encode()).hexdigest(),
                payload=payload,
                now=bundle.now,
            ),
        )
    elif group == "auvexo_paper_owner":
        policy = type(bundle.policy).model_validate(
            bundle.policy.model_dump() | {"version": "identity.fixture." + uuid4().hex}
        )
        connection.execute(
            text("INSERT INTO paper_policy VALUES (:hash,:payload,:now)"),
            dict(
                hash=policy.content_hash(),
                payload=policy.canonical_bytes().decode(),
                now=bundle.now,
            ),
        )
    else:
        # A fresh virtual namespace gives this zero-flow fact an empty prior chain.
        account = "paper.identity.permission." + uuid4().hex
        event_id = str(uuid4())
        payload = dumps(
            dict(
                data={"amount": "0"},
                previous_hash="0" * 64,
                account_ref=account,
                kind="ADJUSTMENT",
                intent_hash=None,
                event_id=event_id,
                recorded_at=bundle.now.isoformat(timespec="microseconds").replace("+00:00", "Z"),
            ),
            sort_keys=True,
            separators=(",", ":"),
        )
        connection.execute(
            text(
                "INSERT INTO paper_truth_event "
                "(event_id,account_ref,kind,content_hash,payload,recorded_at) "
                "VALUES (:id,:account,'ADJUSTMENT',:hash,:payload,:now)"
            ),
            dict(
                id=event_id,
                account=account,
                hash=sha256(payload.encode()).hexdigest(),
                payload=payload,
                now=bundle.now,
            ),
        )


FORBIDDEN = (
    "UPDATE pg_catalog.pg_settings SET setting='replica' WHERE name='session_replication_role'",
    "UPDATE foundation_policy SET execution_enabled=true",
    "INSERT INTO research_study VALUES ('identity.forbidden',repeat('0',64),'{}',now())",
    "INSERT INTO research_trial VALUES "
    "('identity.forbidden','identity.forbidden','OOS',repeat('0',64),repeat('0',64),1,now())",
    "INSERT INTO research_event VALUES "
    "('identity.forbidden','identity.forbidden','HOLDOUT_OPEN',repeat('0',64),'{}',now())",
    "UPDATE alembic_version SET version_num='forbidden'",
    "CREATE SCHEMA identity_forbidden_schema",
    "CREATE TABLE identity_forbidden_table (id integer)",
    "CREATE TEMP TABLE identity_forbidden_temp (x integer)",
    "ALTER TABLE foundation_policy ADD COLUMN identity_forbidden integer",
    "CREATE ROLE identity_forbidden_admin SUPERUSER",
    "GRANT auvexo_admin TO CURRENT_USER",
    "SET ROLE auvexo_admin",
    "SET SESSION AUTHORIZATION auvexo_admin",
)


@pytest.mark.parametrize("group", GROUPS)
def test_identity_connect_commit_rollback_permission_error_and_pool_reuse(
    identity_database, identity_fixture, group
):
    credential = paper_local.load_credentials(identity_database, group)
    engine = paper_local.engine_for(identity_database, group)
    assert engine.url.username == credential.username
    assert engine.url.username != "auvexo_admin"
    try:
        with engine.connect() as conn:
            assert_identity(conn, credential)
            conn.rollback()
            with conn.begin():
                assert_identity(conn, credential)
                allowed_write(conn, group, identity_fixture)
            assert_identity(conn, credential)
            conn.rollback()
            allowed_write(conn, group, identity_fixture)
            conn.rollback()
            assert_identity(conn, credential)
            conn.rollback()
            for statement in FORBIDDEN:
                with pytest.raises(DBAPIError) as denied:
                    conn.execute(text(statement))
                assert denied.value.orig.sqlstate == "42501"
                conn.rollback()
                assert_identity(conn, credential)
                allowed_write(conn, group, identity_fixture)
                conn.commit()
            # RESET cannot uncover an elevated authenticated session.
            conn.execute(text("RESET ROLE"))
            conn.execute(text("RESET SESSION AUTHORIZATION"))
            conn.commit()
            assert_identity(conn, credential)
            first_backend = conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
        with engine.connect() as conn:
            assert conn.execute(text("SELECT pg_backend_pid()")).scalar_one() == first_backend
            assert_identity(conn, credential)
            allowed_write(conn, group, identity_fixture)
            conn.commit()
        for _ in range(5):
            with engine.begin() as conn:
                assert_identity(conn, credential)
                allowed_write(conn, group, identity_fixture)
        engine.dispose()
        with engine.connect() as conn:
            assert_identity(conn, credential)
            assert conn.execute(text("SELECT pg_backend_pid()")).scalar_one() != first_backend
            allowed_write(conn, group, identity_fixture)
            conn.commit()
    finally:
        engine.dispose()


@pytest.mark.parametrize("group", GROUPS)
def test_identity_four_concurrent_connections_remain_least_privilege(
    identity_database, identity_fixture, group
):
    credential = paper_local.load_credentials(identity_database, group)
    engine = paper_local.engine_for(identity_database, group)
    barrier = Barrier(4)

    def worker(_):
        with engine.begin() as conn:
            assert_identity(conn, credential)
            backend = conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
            barrier.wait(timeout=20)
            allowed_write(conn, group, identity_fixture)
            return backend

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            assert len(set(pool.map(worker, range(4)))) == 4
        with engine.connect() as conn:
            assert_identity(conn, credential)
    finally:
        engine.dispose()


def assert_startup_denied(database, group, credential=None):
    engine = None
    try:
        with pytest.raises(DENIED_STARTUP, match="^(PAPER_|EXPLICIT_PAPER_)"):
            engine = paper_local.engine_for(database, group, credential=credential)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
    finally:
        if engine is not None:
            engine.dispose()


@pytest.mark.parametrize(
    "change",
    (
        "wrong_password",
        "empty_password",
        "wrong_database",
        "wrong_role",
        "wrong_user",
        "wrong_host",
        "wrong_port",
        "admin_credential",
    ),
)
def test_identity_invalid_credentials_fail_closed_without_admin_fallback(identity_database, change):
    credential = paper_local.load_credentials(identity_database, "auvexo_paper")
    changes = {
        "wrong_password": dict(password="synthetic-invalid-password"),
        "empty_password": dict(password=""),
        "wrong_database": dict(database="auvexo_test_" + uuid4().hex[:20]),
        "wrong_role": dict(role="auvexo_paper_owner"),
        "wrong_user": dict(username="identity_missing_" + uuid4().hex[:20]),
        "wrong_host": dict(host="127.0.0.2"),
        "wrong_port": dict(port=credential.port + 1),
    }
    if change == "admin_credential":
        altered = replace(
            credential, username="auvexo_admin", password=str(paper_local.admin_args()["password"])
        )
    else:
        altered = replace(credential, **changes[change])
    assert "password=" not in repr(altered)
    assert_startup_denied(identity_database, "auvexo_paper", altered)


def test_identity_missing_manifest_and_unprovisioned_database_fail_closed(
    identity_database, tmp_path, monkeypatch
):
    with monkeypatch.context() as patch:
        patch.setattr(paper_local, "credential_path", lambda name: tmp_path / "absent.json")
        assert_startup_denied(identity_database, "auvexo_paper")
    with paper_local.isolated_database() as unprovisioned:
        assert_startup_denied(unprovisioned, "auvexo_paper")


def test_identity_provisioning_idempotent_and_admin_engine_injection_refused(identity_database):
    credential = paper_local.load_credentials(identity_database, "auvexo_paper")
    paper_local.provision_services(identity_database)
    assert (
        paper_local.load_credentials(identity_database, "auvexo_paper").username
        == credential.username
    )
    engine = paper_local.engine_for(identity_database, "auvexo_paper", credential=credential)
    try:
        with engine.connect() as conn:
            assert_identity(conn, credential)
    finally:
        engine.dispose()
    assert_startup_denied(identity_database, None)
    admin_engine = create_engine(
        paper_local.admin_database_url(identity_database), hide_parameters=True
    )
    try:
        with pytest.raises(PaperIdentityError, match="^PAPER_IDENTITY_"):
            PaperStore(admin_engine)
        with pytest.raises(PaperIdentityError, match="^PAPER_IDENTITY_"):
            PaperTruth(admin_engine)
    finally:
        admin_engine.dispose()


@pytest.mark.parametrize("group", GROUPS)
@pytest.mark.parametrize(
    "mutation",
    (
        "NOLOGIN",
        "SUPERUSER",
        "CREATEDB",
        "CREATEROLE",
        "REPLICATION",
        "BYPASSRLS",
        "REVOKE_MEMBERSHIP",
        "ADMIN_MEMBERSHIP",
        "EXPIRED_LOGIN",
        "MEMBERSHIP_ADMIN_OPTION",
        "MEMBERSHIP_NOINHERIT",
        "MEMBERSHIP_SET",
    ),
)
def test_identity_live_role_drift_rejects_existing_pool_checkout(
    identity_database, group, mutation
):
    credential = paper_local.load_credentials(identity_database, group)
    engine = paper_local.engine_for(identity_database, group)
    prior_expiry = None
    try:
        with engine.connect() as conn:
            assert_identity(conn, credential)
        with psycopg.connect(dbname=identity_database, **paper_local.admin_args()) as admin:
            if mutation == "REVOKE_MEMBERSHIP":
                admin.execute(
                    sql.SQL("REVOKE {} FROM {}").format(
                        sql.Identifier(group), sql.Identifier(credential.username)
                    )
                )
            elif mutation == "ADMIN_MEMBERSHIP":
                admin.execute(
                    sql.SQL("GRANT auvexo_admin TO {}").format(sql.Identifier(credential.username))
                )
            elif mutation == "EXPIRED_LOGIN":
                prior_expiry = admin.execute(
                    "SELECT rolvaliduntil::text FROM pg_roles WHERE rolname=%s",
                    (credential.username,),
                ).fetchone()[0]
                admin.execute(
                    sql.SQL("ALTER ROLE {} VALID UNTIL '2000-01-01 00:00:00+00'").format(
                        sql.Identifier(credential.username)
                    )
                )
            elif mutation.startswith("MEMBERSHIP_"):
                options = {
                    "MEMBERSHIP_ADMIN_OPTION": "ADMIN TRUE, INHERIT TRUE, SET FALSE",
                    "MEMBERSHIP_NOINHERIT": "ADMIN FALSE, INHERIT FALSE, SET FALSE",
                    "MEMBERSHIP_SET": "ADMIN FALSE, INHERIT TRUE, SET TRUE",
                }[mutation]
                admin.execute(
                    sql.SQL("GRANT {} TO {} WITH " + options).format(
                        sql.Identifier(group), sql.Identifier(credential.username)
                    )
                )
            else:
                admin.execute(
                    sql.SQL("ALTER ROLE {} " + mutation).format(sql.Identifier(credential.username))
                )
        try:
            with (
                pytest.raises(PaperIdentityError, match="^PAPER_IDENTITY_"),
                engine.connect() as conn,
            ):
                conn.execute(text("SELECT 1"))
        finally:
            with psycopg.connect(dbname=identity_database, **paper_local.admin_args()) as admin:
                admin.execute(
                    sql.SQL(
                        "ALTER ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(credential.username))
                )
                admin.execute(
                    sql.SQL("GRANT {} TO {} WITH ADMIN FALSE, INHERIT TRUE, SET FALSE").format(
                        sql.Identifier(group), sql.Identifier(credential.username)
                    )
                )
                if mutation == "ADMIN_MEMBERSHIP":
                    admin.execute(
                        sql.SQL("REVOKE auvexo_admin FROM {}").format(
                            sql.Identifier(credential.username)
                        )
                    )
                if mutation == "EXPIRED_LOGIN":
                    admin.execute(
                        sql.SQL("ALTER ROLE {} VALID UNTIL {}").format(
                            sql.Identifier(credential.username),
                            sql.Literal(prior_expiry or "infinity"),
                        )
                    )
        engine.dispose()
        with engine.connect() as conn:
            assert_identity(conn, credential)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("group", "table"),
    (
        ("auvexo_paper", "paper_intent"),
        ("auvexo_paper_owner", "paper_policy"),
        ("auvexo_paper_truth", "paper_truth_event"),
    ),
)
def test_identity_required_grant_revocation_rejects_existing_pool(identity_database, group, table):
    credential = paper_local.load_credentials(identity_database, group)
    engine = paper_local.engine_for(identity_database, group)
    try:
        with engine.connect() as conn:
            assert_identity(conn, credential)
        with psycopg.connect(dbname=identity_database, **paper_local.admin_args()) as admin:
            admin.execute(
                sql.SQL("REVOKE INSERT ON {} FROM {}").format(
                    sql.Identifier(table), sql.Identifier(group)
                )
            )
        try:
            with (
                pytest.raises(PaperIdentityError, match="^PAPER_IDENTITY_"),
                engine.connect() as conn,
            ):
                conn.execute(text("SELECT 1"))
        finally:
            with psycopg.connect(dbname=identity_database, **paper_local.admin_args()) as admin:
                admin.execute(
                    sql.SQL("GRANT INSERT ON {} TO {}").format(
                        sql.Identifier(table), sql.Identifier(group)
                    )
                )
        engine.dispose()
        with engine.connect() as conn:
            assert_identity(conn, credential)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("grant", "revoke", "reason"),
    (
        (
            "INSERT ON paper_truth_event",
            "INSERT ON paper_truth_event",
            "CROSS_SCOPE_GRANT_DENIED",
        ),
        (
            "UPDATE (execution_enabled) ON foundation_policy",
            "UPDATE (execution_enabled) ON foundation_policy",
            "COLUMN_OR_TRIGGER_GRANT_DENIED",
        ),
        (
            "INSERT ON paper_intent",
            "INSERT ON paper_intent",
            "CROSS_SCOPE_GRANT_DENIED",
        ),
        (
            "REFERENCES ON paper_intent",
            "REFERENCES ON paper_intent",
            "COLUMN_OR_TRIGGER_GRANT_DENIED",
        ),
        (
            "REFERENCES (intent_hash) ON paper_intent",
            "REFERENCES (intent_hash) ON paper_intent",
            "COLUMN_OR_TRIGGER_GRANT_DENIED",
        ),
        ("TRIGGER ON paper_intent", "TRIGGER ON paper_intent", "COLUMN_OR_TRIGGER_GRANT_DENIED"),
    ),
)
def test_identity_extra_direct_table_column_or_delegable_grants_reject_warmed_pool(
    identity_database, grant, revoke, reason
):
    credential = paper_local.load_credentials(identity_database, "auvexo_paper")
    engine = paper_local.engine_for(identity_database, "auvexo_paper")
    try:
        with engine.connect() as conn:
            assert_identity(conn, credential)
        with psycopg.connect(dbname=identity_database, **paper_local.admin_args()) as admin:
            suffix = " WITH GRANT OPTION" if grant == "INSERT ON paper_intent" else ""
            admin.execute(
                sql.SQL("GRANT " + grant + " TO {}" + suffix).format(
                    sql.Identifier(credential.username)
                )
            )
        try:
            with (
                pytest.raises(PaperIdentityError, match="^PAPER_IDENTITY_" + reason + "$"),
                engine.connect() as conn,
            ):
                conn.execute(text("SELECT 1"))
        finally:
            # Only the uniquely provisioned LOGIN receives or loses these direct grants.
            # Its inherited group grants, including normal paper_intent INSERT, stay intact.
            with psycopg.connect(dbname=identity_database, **paper_local.admin_args()) as admin:
                admin.execute(
                    sql.SQL("REVOKE " + revoke + " FROM {}").format(
                        sql.Identifier(credential.username)
                    )
                )
        engine.dispose()
        with engine.connect() as conn:
            assert_identity(conn, credential)
    finally:
        engine.dispose()


def test_identity_stale_backend_reconnects_as_same_unprivileged_login(identity_database):
    credential = paper_local.load_credentials(identity_database, "auvexo_paper")
    engine = paper_local.engine_for(identity_database, "auvexo_paper")
    try:
        with engine.connect() as conn:
            assert_identity(conn, credential)
            backend = conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
            conn.rollback()
        with psycopg.connect(dbname=identity_database, **paper_local.admin_args()) as admin:
            assert admin.execute("SELECT pg_terminate_backend(%s)", (backend,)).fetchone() == (
                True,
            )
        with engine.connect() as conn:
            assert_identity(conn, credential)
            assert conn.execute(text("SELECT pg_backend_pid()")).scalar_one() != backend
    finally:
        engine.dispose()


@pytest.mark.parametrize("query", ({"host": "127.0.0.2"}, {"options": "-c role=auvexo_admin"}))
def test_identity_constructor_refuses_url_driver_overrides_before_connect(identity_database, query):
    credential = paper_local.load_credentials(identity_database, "auvexo_paper")
    url = URL.create(
        "postgresql+psycopg",
        username=credential.username,
        password=credential.password,
        host=credential.host,
        port=credential.port,
        database=credential.database,
        query=query,
    )
    engine = create_engine(url, hide_parameters=True)
    try:
        with pytest.raises(PaperIdentityError, match="^PAPER_IDENTITY_.*(ENDPOINT|QUERY)"):
            PaperStore(engine)
    finally:
        engine.dispose()


@pytest.mark.parametrize("override", ("host_alias", "admin_session"))
def test_identity_actual_connected_endpoint_cannot_override_advertised_url(
    identity_database, override
):
    credential = paper_local.load_credentials(identity_database, "auvexo_paper")
    url = URL.create(
        "postgresql+psycopg",
        username=credential.username,
        password=credential.password,
        host=credential.host,
        port=credential.port,
        database=credential.database,
    )
    # A deliberately hostile Engine may advertise an acceptable URL while supplying
    # different DBAPI arguments; the actual authenticated connection must be checked.
    options = (
        {"host": "localhost"}
        if override == "host_alias"
        else {"user": "auvexo_admin", "password": str(paper_local.admin_args()["password"])}
    )
    engine = create_engine(url, hide_parameters=True, connect_args=options)
    try:
        with pytest.raises(PaperIdentityError, match="^PAPER_IDENTITY_CONNECTED_ENDPOINT_DENIED$"):
            PaperStore(engine)
    finally:
        engine.dispose()


def test_identity_constructor_cannot_confuse_runtime_owner_and_truth_engines(identity_database):
    runtime = paper_local.engine_for(identity_database, "auvexo_paper")
    owner = paper_local.engine_for(identity_database, "auvexo_paper_owner")
    truth = paper_local.engine_for(identity_database, "auvexo_paper_truth")
    try:
        with pytest.raises(PaperIdentityError, match="^PAPER_IDENTITY_"):
            PaperStore(truth)
        with pytest.raises(PaperIdentityError, match="^PAPER_IDENTITY_"):
            PaperStore(runtime, owner_engine=truth)
        with pytest.raises(PaperIdentityError, match="^PAPER_IDENTITY_"):
            PaperTruth(owner)
    finally:
        for engine in (runtime, owner, truth):
            engine.dispose()


@pytest.mark.parametrize("mutation", ("SCHEMA_CREATE", "SCHEMA_OWNER", "TABLE_INSERT"))
def test_identity_nonpublic_namespace_or_table_authority_rejects_warmed_pool(
    identity_database, mutation
):
    credential = paper_local.load_credentials(identity_database, "auvexo_paper")
    engine = paper_local.engine_for(identity_database, "auvexo_paper")
    namespace = "identity_scope_" + uuid4().hex
    reason = (
        "CROSS_SCOPE_GRANT_DENIED"
        if mutation == "TABLE_INSERT"
        else "NAMESPACE_OR_OWNERSHIP_DENIED"
    )
    try:
        with engine.connect() as conn:
            assert_identity(conn, credential)
        try:
            with psycopg.connect(dbname=identity_database, **paper_local.admin_args()) as admin:
                admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(namespace)))
                admin.execute(
                    sql.SQL("CREATE TABLE {}.fixture(id integer)").format(sql.Identifier(namespace))
                )
                if mutation == "SCHEMA_CREATE":
                    admin.execute(
                        sql.SQL("GRANT CREATE ON SCHEMA {} TO {}").format(
                            sql.Identifier(namespace), sql.Identifier(credential.username)
                        )
                    )
                elif mutation == "SCHEMA_OWNER":
                    admin.execute(
                        sql.SQL("ALTER SCHEMA {} OWNER TO {}").format(
                            sql.Identifier(namespace), sql.Identifier(credential.username)
                        )
                    )
                else:
                    admin.execute(
                        sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                            sql.Identifier(namespace), sql.Identifier(credential.username)
                        )
                    )
                    admin.execute(
                        sql.SQL("GRANT INSERT ON {}.fixture TO {}").format(
                            sql.Identifier(namespace), sql.Identifier(credential.username)
                        )
                    )
            with (
                pytest.raises(PaperIdentityError, match="^PAPER_IDENTITY_" + reason + "$"),
                engine.connect() as conn,
            ):
                conn.execute(text("SELECT 1"))
        finally:
            with psycopg.connect(dbname=identity_database, **paper_local.admin_args()) as admin:
                # The only cascading target is the fresh UUID namespace created above.
                admin.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(namespace))
                )
        engine.dispose()
        with engine.connect() as conn:
            assert_identity(conn, credential)
    finally:
        engine.dispose()


def test_identity_unallowlisted_privileged_definer_execute_rejects_warmed_pool(identity_database):
    credential = paper_local.load_credentials(identity_database, "auvexo_paper")
    engine = paper_local.engine_for(identity_database, "auvexo_paper")
    namespace = "identity_definer_" + uuid4().hex
    try:
        with engine.connect() as conn:
            assert_identity(conn, credential)
        try:
            with psycopg.connect(dbname=identity_database, **paper_local.admin_args()) as admin:
                admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(namespace)))
                # This adversarial fixture must never be invoked. It represents an
                # unexpected admin-owned EXECUTE capability outside the narrow allowlist.
                admin.execute(
                    sql.SQL(
                        "CREATE FUNCTION {}.privileged_fixture() RETURNS void "
                        "LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$ "
                        "BEGIN EXECUTE format('GRANT CREATE ON SCHEMA public TO %I',session_user); "
                        "END; $$"
                    ).format(sql.Identifier(namespace))
                )
                admin.execute(
                    sql.SQL("REVOKE ALL ON FUNCTION {}.privileged_fixture() FROM PUBLIC").format(
                        sql.Identifier(namespace)
                    )
                )
                admin.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                        sql.Identifier(namespace), sql.Identifier(credential.username)
                    )
                )
                admin.execute(
                    sql.SQL("GRANT EXECUTE ON FUNCTION {}.privileged_fixture() TO {}").format(
                        sql.Identifier(namespace), sql.Identifier(credential.username)
                    )
                )
            with (
                pytest.raises(PaperIdentityError, match="^PAPER_IDENTITY_SECURITY_DEFINER_DENIED$"),
                engine.connect() as conn,
            ):
                conn.execute(text("SELECT 1"))
        finally:
            with psycopg.connect(dbname=identity_database, **paper_local.admin_args()) as admin:
                admin.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(namespace))
                )
        engine.dispose()
        with engine.connect() as conn:
            assert_identity(conn, credential)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "privilege", ("UPDATE", "USAGE WITH GRANT OPTION", "SELECT WITH GRANT OPTION")
)
def test_identity_sequence_rewrite_or_delegation_rejects_warmed_pool(identity_database, privilege):
    credential = paper_local.load_credentials(identity_database, "auvexo_paper")
    engine = paper_local.engine_for(identity_database, "auvexo_paper")
    operation = privilege.split()[0]
    delegation = " WITH GRANT OPTION" if "WITH GRANT OPTION" in privilege else ""
    try:
        with engine.connect() as conn:
            assert_identity(conn, credential)
        with psycopg.connect(dbname=identity_database, **paper_local.admin_args()) as admin:
            admin.execute(
                sql.SQL(
                    "GRANT "
                    + operation
                    + " ON SEQUENCE paper_journal_sequence_seq TO {}"
                    + delegation
                ).format(sql.Identifier(credential.username))
            )
        try:
            with (
                pytest.raises(PaperIdentityError, match="^PAPER_IDENTITY_SEQUENCE_GRANT_DENIED$"),
                engine.connect() as conn,
            ):
                conn.execute(text("SELECT 1"))
        finally:
            # Removing only the direct LOGIN grant preserves normal group USAGE/SELECT.
            with psycopg.connect(dbname=identity_database, **paper_local.admin_args()) as admin:
                admin.execute(
                    sql.SQL(
                        "REVOKE " + operation + " ON SEQUENCE paper_journal_sequence_seq FROM {}"
                    ).format(sql.Identifier(credential.username))
                )
        engine.dispose()
        with engine.connect() as conn:
            assert_identity(conn, credential)
    finally:
        engine.dispose()


def test_identity_temporary_database_grant_rejects_warmed_pool(identity_database):
    credential = paper_local.load_credentials(identity_database, "auvexo_paper")
    engine = paper_local.engine_for(identity_database, "auvexo_paper")
    try:
        with engine.connect() as conn:
            assert_identity(conn, credential)
        with psycopg.connect(dbname=identity_database, **paper_local.admin_args()) as admin:
            admin.execute(
                sql.SQL("GRANT TEMPORARY ON DATABASE {} TO {}").format(
                    sql.Identifier(identity_database), sql.Identifier(credential.username)
                )
            )
        try:
            with (
                pytest.raises(
                    PaperIdentityError, match="^PAPER_IDENTITY_NAMESPACE_OR_OWNERSHIP_DENIED$"
                ),
                engine.connect() as conn,
            ):
                conn.execute(text("SELECT 1"))
        finally:
            with psycopg.connect(dbname=identity_database, **paper_local.admin_args()) as admin:
                admin.execute(
                    sql.SQL("REVOKE TEMPORARY ON DATABASE {} FROM {}").format(
                        sql.Identifier(identity_database), sql.Identifier(credential.username)
                    )
                )
        engine.dispose()
        with engine.connect() as conn:
            assert_identity(conn, credential)
    finally:
        engine.dispose()


def test_identity_owned_service_roles_are_removed_when_credential_manifest_is_lost():
    with paper_local.isolated_database() as database:
        paper_local.require_migration(database)
        usernames = [paper_local.load_credentials(database, group).username for group in GROUPS]
        assert len(set(usernames)) == 3
        # Only this newly provisioned test database's private manifest is removed.
        # Cleanup must use its in-memory ownership record without inventing identities.
        paper_local.credential_path(database).unlink()
        assert_startup_denied(database, "auvexo_paper")
    with psycopg.connect(dbname="postgres", **paper_local.admin_args()) as admin:
        assert (
            admin.execute(
                "SELECT rolname FROM pg_roles WHERE rolname=ANY(%s)", (usernames,)
            ).fetchall()
            == []
        )
