"""Generated, migrated and dropped PostgreSQL databases for integration tests (DB-2).

Every database is named ``auvexo_test_<12 hex>``, validated before any statement, migrated
to the main-chain head and dropped afterwards, so no test leaves permanent rows behind in
a shared database. The cluster itself comes from the test environment (a disposable local
cluster or the hosted CI service); the operational ports are always refused.
"""

import os
import re
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import URL, Engine, create_engine, event
from test_postgres import connection_args

GENERATED = re.compile(r"auvexo_test_[0-9a-f]{12}")
OPERATIONAL_PORTS = (55432, 55433)
ROOT = Path(__file__).resolve().parents[1]


def admin_arguments() -> dict[str, object]:
    args = connection_args()
    if args["port"] in OPERATIONAL_PORTS:
        pytest.fail("PostgreSQL tests run only against a disposable cluster or hosted CI")
    return args | {"dbname": "postgres"}


def database_exists(name: str) -> bool:
    with psycopg.connect(**admin_arguments(), autocommit=True) as admin:
        return (
            admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (name,)).fetchone()
            is not None
        )


def engine_for(name: str, role: str | None = None, **options: object) -> Engine:
    """Admin login to the generated database, optionally narrowed with SET ROLE."""
    args = admin_arguments()
    engine = create_engine(
        URL.create(
            "postgresql+psycopg",
            username=str(args["user"]),
            password=str(args["password"]),
            host="127.0.0.1",
            port=int(str(args["port"])),
            database=name,
        ),
        hide_parameters=True,
        connect_args={"options": "-c statement_timeout=30000 -c lock_timeout=10000"},
        **options,
    )
    if role is not None:

        @event.listens_for(engine, "connect")
        def narrow(connection, record):
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))

    return engine


def writer_engine(name: str) -> Engine:
    """The data-writer LOGIN identity (member of auvexo_ingest) on a generated database."""
    password = os.environ.get("TEST_PG_DATA_WRITER_PASSWORD")
    if not password:
        pytest.fail("TEST_PG_DATA_WRITER_PASSWORD is required for data-writer tests")
    args = admin_arguments()
    return create_engine(
        URL.create(
            "postgresql+psycopg",
            username="auvexo_data_writer",
            password=password,
            host="127.0.0.1",
            port=int(str(args["port"])),
            database=name,
        ),
        hide_parameters=True,
        connect_args={"options": "-c statement_timeout=60000 -c lock_timeout=10000"},
    )


@contextmanager
def generated_database() -> Iterator[str]:
    name = "auvexo_test_" + uuid4().hex[:12]
    if not GENERATED.fullmatch(name):
        raise ValueError("GENERATED_DATABASE_NAME_INVALID")
    args = admin_arguments()
    with psycopg.connect(**args, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            admin.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name))
            )
            roles = [
                row[0]
                for row in admin.execute(
                    "SELECT rolname FROM pg_roles WHERE rolname IN "
                    "('auvexo_data_writer','auvexo_app')"
                )
            ]
            for role in roles:
                admin.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        sql.Identifier(name), sql.Identifier(role)
                    )
                )
            dsn = URL.create(
                "postgresql+psycopg",
                username=str(args["user"]),
                password=str(args["password"]),
                host="127.0.0.1",
                port=int(str(args["port"])),
                database=name,
            ).render_as_string(hide_password=False)
            migrated = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=ROOT,
                env=os.environ | {"AUVEXO_MIGRATION_DSN": dsn},
                capture_output=True,
                timeout=300,
                check=False,
            )
            if migrated.returncode:
                output = (migrated.stdout + migrated.stderr).decode(errors="replace")
                pytest.fail("migration failed\n" + output.replace(str(args["password"]), "***"))
            yield name
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
