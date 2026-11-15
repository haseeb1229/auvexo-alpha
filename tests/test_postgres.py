"""Mandatory real PostgreSQL tests. Missing setup fails rather than skipping."""

import os
import re
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from pydantic import SecretStr

from auvexo_alpha.config import Settings
from auvexo_alpha.infrastructure.database import SCHEMA_REVISION, DatabaseProbe, make_engine
from tools.disposable_pg import harness_args

pytestmark = pytest.mark.integration


def connection_args(role: str = "admin") -> dict[str, Any]:
    """Arguments for the disposable test cluster only; see tools/disposable_pg.py.

    The operational ports are refused and the server's disposable-cluster marker is
    proven before any test can write. There is no fallback to local secret files.
    """
    database = os.environ.get("TEST_PG_DATABASE", "auvexo_test")
    # These tests write, and some rows are append-only. A mis-set variable must never point
    # them at a development or operational database on the same cluster.
    if not re.fullmatch(r"auvexo_test(_[a-z0-9]{1,32})?", database):
        pytest.fail("TEST_PG_DATABASE must name a disposable auvexo_test database")
    try:
        args = harness_args(role)
    except (RuntimeError, ValueError, psycopg.Error) as error:
        pytest.fail(f"Disposable PostgreSQL test cluster required: {type(error).__name__}: {error}")
    return args | {"dbname": database}


def test_r025_p1_actual_postgres_schema_and_defaults() -> None:
    with psycopg.connect(**connection_args()) as conn:
        assert conn.execute("SHOW server_version").fetchone()[0].startswith("17.")
        assert (
            conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == SCHEMA_REVISION
        )
        assert conn.execute(
            "SELECT execution_enabled,binance_live_derivatives FROM foundation_policy"
        ).fetchone() == (False, "BLOCKED_BY_POLICY")


def test_r025_p1_rollback_unique_and_constraints() -> None:
    event_id = uuid4()
    with psycopg.connect(**connection_args()) as conn:
        statement = "INSERT INTO developer_event VALUES (%s,%s,%s,now(),%s)"
        conn.execute(statement, (event_id, "1.0", "TEST_FIXTURE", "0" * 64))
        with pytest.raises(psycopg.errors.UniqueViolation), conn.transaction():
            conn.execute(statement, (event_id, "1.0", "TEST_FIXTURE", "0" * 64))
        with pytest.raises(psycopg.errors.InvalidTextRepresentation), conn.transaction():
            conn.execute(statement, ("not-a-uuid", "1.0", "TEST_FIXTURE", "0" * 64))
        for version, kind, digest in [
            ("2.0", "TEST_FIXTURE", "0" * 64),
            ("1.0", "TRADE", "0" * 64),
            ("1.0", "DEV_CHECK", "invalid"),
        ]:
            with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
                conn.execute(statement, (uuid4(), version, kind, digest))
        conn.rollback()
        assert (
            conn.execute("SELECT 1 FROM developer_event WHERE event_id=%s", (event_id,)).fetchone()
            is None
        )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE foundation_policy SET execution_enabled=true",
        "DELETE FROM foundation_policy",
        "TRUNCATE foundation_policy",
        "UPDATE developer_event SET content_hash=content_hash",
        "DELETE FROM developer_event",
        "TRUNCATE developer_event",
    ],
)
def test_r025_p1_append_only_even_for_migrator(statement: str) -> None:
    with psycopg.connect(**connection_args()) as conn:
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute(statement)
        conn.rollback()


def test_r023_p1_app_cannot_mutate_or_create() -> None:
    with psycopg.connect(**connection_args("app")) as conn:
        for statement in [
            "UPDATE foundation_policy SET execution_enabled=true",
            "INSERT INTO developer_event VALUES "
            "(gen_random_uuid(),'1.0','DEV_CHECK',now(),repeat('0',64))",
            "CREATE TABLE unauthorized (id integer)",
        ]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                conn.execute(statement)


def test_r027_p1_real_readiness_and_disconnect() -> None:
    args = connection_args("app")
    settings = Settings(
        database_password=SecretStr(str(args["password"])),
        api_token=SecretStr("synthetic-test-token-" * 3),
        database_name=str(args["dbname"]),
        database_port=int(args["port"]),
    )
    engine = make_engine(settings)
    try:
        assert DatabaseProbe(engine).ready()
    finally:
        engine.dispose()
    bad = Settings.model_validate(settings.model_dump() | {"database_name": "auvexo_test_missing"})
    engine = make_engine(bad)
    try:
        assert not DatabaseProbe(engine).ready()
    finally:
        engine.dispose()
