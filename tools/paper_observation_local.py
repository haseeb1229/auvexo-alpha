"""Bounded persistent observation provisioning. No START or scheduled-task registration."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy import URL, create_engine
from sqlalchemy.engine import Engine

from auvexo_alpha.infrastructure.paper_identity import enforce_paper_engine

if __package__:
    from tools.local_db import write_private
    from tools.paper_local import (
        PAPER_GROUPS,
        ROOT,
        PaperCredential,
        _verify_role,
        admin_args,
        safe_window,
    )
else:
    from local_db import write_private
    from paper_local import (
        PAPER_GROUPS,
        ROOT,
        PaperCredential,
        _verify_role,
        admin_args,
        safe_window,
    )

LOCAL = ROOT / ".local"
TAGS = {"auvexo_paper": "pw", "auvexo_paper_owner": "po", "auvexo_paper_truth": "pt"}
_CONTEXT_DATABASES: set[str] = set()
_OWNED_DATABASES: set[str] = set()
_OWNED_LOGINS: dict[str, set[str]] = {}
_OWNED_FILES: set[Path] = set()


def validate_name(name: str) -> None:
    if not re.fullmatch(r"auvexo_paperobs_[a-f0-9]{20}", name):
        raise ValueError("OBSERVATION_DATABASE_NAMESPACE_REQUIRED")


def credential_path(name: str) -> Path:
    validate_name(name)
    return LOCAL / "paper-identities" / (name + ".json")


def load_credentials(name: str, group: str) -> PaperCredential:
    validate_name(name)
    if group not in PAPER_GROUPS:
        raise ValueError("EXPLICIT_PAPER_GROUP_REQUIRED")
    try:
        data = json.loads(credential_path(name).read_text())
        username = "auvexo_" + TAGS[group] + "_" + name.rsplit("_", 1)[1]
        record = data["roles"][group]
        if (
            set(data) != {"version", "database", "host", "port", "roles"}
            or set(record) != {"username", "password"}
            or type(data["port"]) is not int
            or type(data["version"]) is not int
            or data["database"] != name
            or data["host"] != "127.0.0.1"
            or data["port"] != 55432
            or data["version"] != 1
            or set(data["roles"]) != set(PAPER_GROUPS)
            or record["username"] != username
            or not isinstance(record["password"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", record["password"])
        ):
            raise ValueError("INVALID_MANIFEST")
        return PaperCredential(username, record["password"], name, group)
    except (OSError, ValueError, KeyError, TypeError):
        raise RuntimeError("OBSERVATION_CREDENTIAL_UNAVAILABLE_OR_INVALID") from None


def engine_for(
    name: str, group: str | None = None, *, credential: PaperCredential | None = None
) -> Engine:
    validate_name(name)
    if group not in PAPER_GROUPS:
        raise ValueError("EXPLICIT_PAPER_GROUP_REQUIRED")
    identity = credential or load_credentials(name, group)
    if (
        identity.database != name
        or identity.host != "127.0.0.1"
        or identity.port != 55432
        or identity.role != group
        or identity.username != "auvexo_" + TAGS[group] + "_" + name.rsplit("_", 1)[1]
    ):
        raise ValueError("OBSERVATION_CREDENTIAL_BINDING_DENIED")
    engine = create_engine(
        URL.create(
            "postgresql+psycopg",
            username=identity.username,
            password=identity.password,
            host="127.0.0.1",
            port=55432,
            database=name,
        ),
        hide_parameters=True,
        pool_size=2,
        max_overflow=0,
        pool_timeout=3,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 3,
            "options": "-c timezone=UTC -c statement_timeout=10000",
        },
    )
    try:
        enforce_paper_engine(
            engine, group, expected_login=identity.username, expected_database=name
        )
    except (ValueError, RuntimeError):
        engine.dispose()
        raise
    return engine


def migrate(name: str) -> None:
    validate_name(name)
    safe_window()
    args = admin_args()
    if args["port"] != 55432:
        raise ValueError("OBSERVATION_VERIFIED_PORT_REQUIRED")
    url = URL.create(
        "postgresql+psycopg",
        username="auvexo_admin",
        password=str(args["password"]),
        host="127.0.0.1",
        port=55432,
        database=name,
    )
    environment = os.environ | {"AUVEXO_MIGRATION_DSN": url.render_as_string(hide_password=False)}
    for config, target in (("alembic.ini", "0005_paper_core"), ("alembic-observation.ini", "head")):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", config, "upgrade", target],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            timeout=120,
            check=False,
        )
        if result.returncode:
            LOCAL.mkdir(exist_ok=True)
            failure = (result.stdout + result.stderr).decode(errors="replace")
            failure = failure.replace(str(args["password"]), "[REDACTED]")
            (LOCAL / "observation-migration-failure.log").write_text(failure)
            raise RuntimeError("OBSERVATION_MIGRATION_FAILED_PRIVATE_LOG_RETAINED")


def provision_services(name: str) -> None:
    validate_name(name)
    safe_window()
    path = credential_path(name)
    exists = path.exists()
    identities = []
    created: set[str] = set()
    with psycopg.connect(dbname=name, **admin_args()) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,20802301))", (name,))
        for group in PAPER_GROUPS:
            _verify_role(conn, group, None)
            identity = (
                load_credentials(name, group)
                if exists
                else PaperCredential(
                    "auvexo_" + TAGS[group] + "_" + name.rsplit("_", 1)[1],
                    secrets.token_hex(32),
                    name,
                    group,
                )
            )
            present = conn.execute(
                "SELECT 1 FROM pg_roles WHERE rolname=%s", (identity.username,)
            ).fetchone()
            if not exists:
                if present:
                    raise RuntimeError("OBSERVATION_UNOWNED_LOGIN_COLLISION")
                conn.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN PASSWORD {} INHERIT NOSUPERUSER "
                        "NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(identity.username), sql.Literal(identity.password))
                )
                conn.execute(
                    sql.SQL("GRANT {} TO {} WITH INHERIT TRUE,SET FALSE").format(
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
                raise RuntimeError("OBSERVATION_PROVISIONED_LOGIN_MISSING")
            _verify_role(conn, identity.username, group)
            identities.append(identity)
        if not exists:
            path.parent.mkdir(exist_ok=True, parents=True)
            if name in _CONTEXT_DATABASES:
                _OWNED_FILES.add(path)
            write_private(
                path,
                json.dumps(
                    {
                        "version": 1,
                        "database": name,
                        "host": "127.0.0.1",
                        "port": 55432,
                        "roles": {
                            i.role: {"username": i.username, "password": i.password}
                            for i in identities
                        },
                    }
                ),
            )
    if name in _CONTEXT_DATABASES:
        _OWNED_LOGINS[name].update(created)
    for group in PAPER_GROUPS:
        engine = engine_for(name, group)
        engine.dispose()


def provision(name: str, *, create: bool = False) -> None:
    validate_name(name)
    safe_window()
    with psycopg.connect(dbname="postgres", autocommit=True, **admin_args()) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (name,)).fetchone()
        if exists and name not in _OWNED_DATABASES and not credential_path(name).is_file():
            raise RuntimeError("OBSERVATION_UNOWNED_DATABASE_COLLISION")
        if not exists:
            if not create:
                raise ValueError("OBSERVATION_DATABASE_NOT_PROVISIONED")
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            if name in _CONTEXT_DATABASES:
                _OWNED_DATABASES.add(name)
            conn.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name))
            )
    migrate(name)
    provision_services(name)


@contextmanager
def isolated_observation_database() -> Iterator[str]:
    """Test-only generated namespace; never invokes START or retains a genuine campaign."""
    name = "auvexo_paperobs_" + uuid4().hex[:20]
    _CONTEXT_DATABASES.add(name)
    _OWNED_LOGINS[name] = set()
    try:
        with psycopg.connect(dbname="postgres", **admin_args()) as conn:
            if conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (name,)).fetchone():
                raise RuntimeError("ISOLATED_OBSERVATION_NAMESPACE_COLLISION")
        provision(name, create=True)
        yield name
    finally:
        safe_window()
        with psycopg.connect(dbname="postgres", autocommit=True, **admin_args()) as conn:
            if name in _OWNED_DATABASES:
                conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
                _OWNED_DATABASES.remove(name)
            for login in sorted(_OWNED_LOGINS[name]):
                conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(login)))
            path = credential_path(name)
            if path in _OWNED_FILES:
                path.unlink(missing_ok=True)
                _OWNED_FILES.remove(path)
            del _OWNED_LOGINS[name]
            _CONTEXT_DATABASES.remove(name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("provision", "verify"))
    parser.add_argument("database")
    arguments = parser.parse_args()
    provision(arguments.database, create=arguments.action == "provision")
    print("Observation database PREPARED; task not registered; qualified dates=0")


if __name__ == "__main__":
    main()
