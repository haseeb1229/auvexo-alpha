"""Isolated, one-shot synthetic PAPER verification databases; never touches DEV."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy import URL, create_engine
from sqlalchemy.engine import Engine

from auvexo_alpha.infrastructure.paper_identity import enforce_paper_engine

if __package__:
    from tools.local_db import write_private
else:
    from local_db import write_private

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
PAPER_GROUPS = ("auvexo_paper", "auvexo_paper_owner", "auvexo_paper_truth")
ROLE_PREFIXES = {"auvexo_paper": "pw", "auvexo_paper_owner": "po", "auvexo_paper_truth": "pt"}
_OWNED_LOGINS: dict[str, set[str]] = {}


@dataclass(frozen=True)
class PaperCredential:
    username: str
    password: str = field(repr=False)
    database: str
    role: str
    host: str = "127.0.0.1"
    port: int = 55432


def _validate_database(name: str) -> None:
    if not re.fullmatch(r"auvexo_(test|restore)_[a-f0-9]{20}", name):
        raise ValueError("ISOLATED_PAPER_DATABASE_REQUIRED")


def _port() -> int:
    value = os.environ.get("TEST_PG_PORT", "55432")
    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 65535:
        raise ValueError("INVALID_LOCAL_POSTGRES_PORT")
    return int(value)


def _service_port() -> int:
    if _port() != 55432:
        raise ValueError("PAPER_VERIFIED_LOCAL_PORT_REQUIRED")
    return 55432


def credential_path(name: str) -> Path:
    _validate_database(name)
    return LOCAL / "paper-identities" / (name + ".json")


def _username(name: str, role: str) -> str:
    _validate_database(name)
    if role not in PAPER_GROUPS:
        raise ValueError("EXPLICIT_PAPER_GROUP_REQUIRED")
    return f"auvexo_{ROLE_PREFIXES[role]}_{name.rsplit('_', 1)[1]}"


def load_credentials(name: str, role: str) -> PaperCredential:
    """Dedicated credential only. Missing or malformed state has no admin fallback."""
    expected = _username(name, role)
    try:
        payload = json.loads(credential_path(name).read_text())
        if set(payload) != {"version", "database", "host", "port", "roles"} or (
            payload["version"] != 1
            or payload["database"] != name
            or payload["host"] != "127.0.0.1"
            or type(payload["port"]) is not int
            or payload["port"] != _service_port()
            or set(payload["roles"]) != set(PAPER_GROUPS)
        ):
            raise ValueError("INVALID_PAPER_CREDENTIAL_MANIFEST")
        record = payload["roles"][role]
        if (
            set(record) != {"username", "password"}
            or record["username"] != expected
            or (
                not isinstance(record["password"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", record["password"])
            )
        ):
            raise ValueError("INVALID_PAPER_CREDENTIAL_MANIFEST")
        return PaperCredential(expected, record["password"], name, role, port=_service_port())
    except (OSError, KeyError, TypeError, ValueError):
        raise RuntimeError("PAPER_CREDENTIAL_UNAVAILABLE_OR_INVALID") from None


def admin_args() -> dict[str, object]:
    """Read credentials only into process memory; never include them in output."""
    password = os.environ.get("TEST_PG_ADMIN_PASSWORD")
    if not password:
        source = LOCAL / "dev-secrets.json"
        if source.exists():
            password = json.loads(source.read_text())["admin"]
    if not password:
        raise RuntimeError("Real isolated PostgreSQL setup required; no test was skipped")
    return dict(
        host="127.0.0.1",
        port=_port(),
        user="auvexo_admin",
        password=password,
        connect_timeout=3,
    )


def safe_window() -> None:
    """Reserve the daily collector qualification window in Pakistan (UTC+05)."""
    from datetime import UTC, datetime, timedelta

    local = datetime.now(UTC) + timedelta(hours=5)
    if (22, 45) <= (local.hour, local.minute) < (23, 20):
        raise RuntimeError("PHASE2_PRIORITY_WINDOW: no PAPER database/benchmark work")


def admin_database_url(name: str) -> URL:
    """Bounded migration connection, never injected into a PAPER service."""
    _validate_database(name)
    args = admin_args()
    return URL.create(
        "postgresql+psycopg",
        username=str(args["user"]),
        password=str(args["password"]),
        host=str(args["host"]),
        port=int(args["port"]),
        database=name,
    )


def engine_for(
    name: str,
    role: str | None = None,
    *,
    credential: PaperCredential | None = None,
) -> Engine:
    _validate_database(name)
    if role not in PAPER_GROUPS:
        raise ValueError("EXPLICIT_PAPER_GROUP_REQUIRED")
    identity = credential or load_credentials(name, role)
    if (
        identity.username != _username(name, role)
        or identity.role != role
        or identity.database != name
        or identity.host != "127.0.0.1"
        or identity.port != _service_port()
        or not identity.password
    ):
        raise ValueError("PAPER_CREDENTIAL_BINDING_DENIED")
    url = URL.create(
        "postgresql+psycopg",
        username=identity.username,
        password=identity.password,
        host=identity.host,
        port=identity.port,
        database=identity.database,
    )
    engine = create_engine(
        url,
        hide_parameters=True,
        connect_args={
            "connect_timeout": 3,
            "options": "-c statement_timeout=10000 -c timezone=UTC",
        },
        pool_size=4,
        max_overflow=4,
        pool_pre_ping=True,
    )
    try:
        enforce_paper_engine(engine, role, expected_login=identity.username, expected_database=name)
    except (ValueError, RuntimeError):
        engine.dispose()
        raise
    return engine


def migrate(name: str, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    safe_window()
    environment = os.environ.copy()
    environment["AUVEXO_MIGRATION_DSN"] = admin_database_url(name).render_as_string(
        hide_password=False
    )
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        timeout=120,
        check=False,
    )


@contextmanager
def isolated_database(*, prefix: str = "auvexo_test") -> Iterator[str]:
    safe_window()
    if prefix not in ("auvexo_test", "auvexo_restore"):
        raise ValueError("ISOLATED_DATABASE_PREFIX_REQUIRED")
    name = prefix + "_" + uuid4().hex[:20]
    with psycopg.connect(dbname="postgres", autocommit=True, **admin_args()) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        admin.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name)))
        _OWNED_LOGINS[name] = set()
        try:
            yield name
        finally:
            # Only this generated database can be removed, never DEV/shared TEST.
            if not re.fullmatch(r"auvexo_(test|restore)_[a-f0-9]{20}", name):
                raise RuntimeError("UNSAFE_DATABASE_CLEANUP")
            safe_window()
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            # Ownership comes from successful provisioning in this context, not a
            # credential file that a negative test may remove or corrupt.
            for username in sorted(_OWNED_LOGINS[name]):
                admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(username)))
            del _OWNED_LOGINS[name]
            path = credential_path(name)
            if path.exists():
                path.unlink()


def require_migration(name: str) -> None:
    result = migrate(name, "upgrade", "head")
    if result.returncode:
        # Migration stderr can contain connection strings; retain it only ignored/local.
        LOCAL.mkdir(exist_ok=True)
        (LOCAL / "paper-migration-failure.log").write_bytes(result.stdout + result.stderr)
        raise RuntimeError("PAPER_MIGRATION_FAILED: private .local log retained")
    provision_services(name)


def _verify_role(conn: psycopg.Connection, username: str, group: str | None) -> None:
    record = conn.execute(
        "SELECT oid,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,"
        "rolcanlogin,rolinherit FROM pg_roles WHERE rolname=%s",
        (username,),
    ).fetchone()
    if record is None or any(record[1:6]) or record[6] != (group is not None) or not record[7]:
        raise RuntimeError("PAPER_ROLE_ATTRIBUTES_INVALID")
    memberships = conn.execute(
        "SELECT r.rolname,m.admin_option,m.inherit_option,m.set_option FROM pg_auth_members m "
        "JOIN pg_roles r ON r.oid=m.roleid WHERE m.member=%s ORDER BY 1",
        (record[0],),
    ).fetchall()
    expected = [] if group is None else [(group, False, True, False)]
    if memberships != expected:
        raise RuntimeError("PAPER_ROLE_MEMBERSHIPS_INVALID")
    if conn.execute(
        "SELECT EXISTS(SELECT 1 FROM pg_class WHERE relowner=%s) OR "
        "EXISTS(SELECT 1 FROM pg_namespace WHERE nspowner=%s) OR "
        "EXISTS(SELECT 1 FROM pg_proc WHERE proowner=%s) OR "
        "EXISTS(SELECT 1 FROM pg_database WHERE datdba=%s)",
        (record[0], record[0], record[0], record[0]),
    ).fetchone()[0]:
        raise RuntimeError("PAPER_ROLE_OBJECT_OWNERSHIP_FORBIDDEN")
    forbidden = conn.execute(
        "SELECT EXISTS(SELECT 1 FROM pg_tables WHERE schemaname='public' "
        "AND (tablename='foundation_policy' OR tablename LIKE 'research_%%') AND "
        "(has_table_privilege(%s,quote_ident(schemaname)||'.'||quote_ident(tablename),"
        "'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') OR "
        "has_any_column_privilege(%s,quote_ident(schemaname)||'.'||quote_ident(tablename),"
        "'INSERT,UPDATE,REFERENCES')))",
        (username, username),
    ).fetchone()
    if forbidden != (False,):
        raise RuntimeError("PAPER_ROLE_FOUNDATION_RESEARCH_PRIVILEGE_FORBIDDEN")


def provision_services(name: str) -> None:
    """Provision only this isolated DB's owned identities; existing drift stops."""
    _validate_database(name)
    _service_port()
    safe_window()
    path = credential_path(name)
    created: set[str] = set()
    with psycopg.connect(dbname=name, **admin_args()) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,20801502))", (name,))
        exists = path.exists()
        for group in PAPER_GROUPS:
            _verify_role(conn, group, None)
        identities = []
        for group in PAPER_GROUPS:
            identity = (
                load_credentials(name, group)
                if exists
                else PaperCredential(
                    _username(name, group), secrets.token_hex(32), name, group, port=_service_port()
                )
            )
            present = conn.execute(
                "SELECT 1 FROM pg_roles WHERE rolname=%s", (identity.username,)
            ).fetchone()
            if not exists:
                if present:
                    raise RuntimeError("UNOWNED_PAPER_LOGIN_COLLISION")
                conn.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN PASSWORD {} INHERIT NOSUPERUSER "
                        "NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(identity.username), sql.Literal(identity.password))
                )
                conn.execute(
                    sql.SQL("GRANT {} TO {} WITH INHERIT TRUE, SET FALSE").format(
                        sql.Identifier(group), sql.Identifier(identity.username)
                    )
                )
                conn.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        sql.Identifier(name), sql.Identifier(identity.username)
                    )
                )
                created.add(identity.username)
            elif not present:
                raise RuntimeError("PROVISIONED_PAPER_LOGIN_MISSING")
            _verify_role(conn, identity.username, group)
            allowed = conn.execute(
                "SELECT has_database_privilege(%s,%s,'CONNECT'),"
                "has_schema_privilege(%s,'public','CREATE')",
                (identity.username, name, identity.username),
            ).fetchone()
            if allowed != (True, False):
                raise RuntimeError("PAPER_EFFECTIVE_PRIVILEGES_INVALID")
            identities.append(identity)
        if not exists:
            path.parent.mkdir(parents=True, exist_ok=True)
            write_private(
                path,
                json.dumps(
                    {
                        "version": 1,
                        "database": name,
                        "host": "127.0.0.1",
                        "port": _service_port(),
                        "roles": {
                            identity.role: {
                                "username": identity.username,
                                "password": identity.password,
                            }
                            for identity in identities
                        },
                    },
                    sort_keys=True,
                ),
            )
    # PostgreSQL role creation has committed before recording cleanup ownership.
    if name in _OWNED_LOGINS:
        _OWNED_LOGINS[name].update(created)
    # Repeated provisioning also proves the complete current service boundary,
    # including effective grants, through the same direct LOGIN attestation.
    for group in PAPER_GROUPS:
        service = engine_for(name, group)
        service.dispose()


def snapshot(name: str) -> dict[str, dict[str, object]]:
    """Stable hashes and counts for every PAPER table, migration and disabled policy."""
    result: dict[str, dict[str, object]] = {}
    with psycopg.connect(dbname=name, **admin_args()) as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                "AND (tablename LIKE 'paper_%' OR tablename IN "
                "('alembic_version','foundation_policy')) ORDER BY tablename"
            )
        ]
        for table in tables:
            rows = conn.execute(
                sql.SQL(
                    "SELECT row_to_json(t)::text FROM {} t ORDER BY row_to_json(t)::text"
                ).format(sql.Identifier(table))
            ).fetchall()
            payload = "\n".join(row[0] for row in rows).encode()
            result[table] = dict(rows=len(rows), sha256=hashlib.sha256(payload).hexdigest())
        triggers = conn.execute(
            "SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid) "
            "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
            "WHERE NOT t.tgisinternal AND c.relname LIKE 'paper_%' ORDER BY 1,2"
        ).fetchall()
        result["__triggers__"] = dict(
            rows=len(triggers), sha256=hashlib.sha256(json.dumps(triggers).encode()).hexdigest()
        )
    return result
