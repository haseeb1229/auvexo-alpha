"""Synthetic connection-bound migration seam negatives; native proof is separate."""

import runpy
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from alembic import context
from alembic.config import Config
from sqlalchemy import URL, Connection

from auvexo_alpha.infrastructure.oi_migrations import (
    migrate_oi_database,
    migration_target,
    validate_migration_connection,
)

ROOT = Path(__file__).resolve().parents[1]


def synthetic_connection(**changes):
    connection = MagicMock(spec=Connection)
    connection.closed = False
    connection.in_transaction.return_value = True
    connection.engine = MagicMock()
    connection.dialect = MagicMock()
    connection.engine.url = URL.create(
        **(
            {
                "drivername": "postgresql+psycopg",
                "host": "127.0.0.1",
                "port": 55433,
                "database": "auvexo_dev_oiresearch",
                "username": "auvexo_admin",
            }
            | changes
        )
    )
    connection.dialect.name = "postgresql"
    connection.dialect.driver = "psycopg"
    connection.execute.return_value.one.return_value = (
        "auvexo_admin",
        "auvexo_admin",
        "none",
        "auvexo_dev_oiresearch",
        "127.0.0.1",
        55433,
    )
    return connection


@pytest.mark.parametrize(
    "change",
    [
        {"host": "localhost"},
        {"host": "192.0.2.1"},
        {"username": "auvexo_app"},
        {"database": "auvexo_dev"},
        {"database": "auvexo_test_oi"},
        {"port": 55432},
        {"port": 55555},
        {"port": None},
        {"drivername": "postgresql+psycopg2"},
        {"drivername": "sqlite"},
        {"query": {"host": "127.0.0.1"}},
    ],
)
def test_supplied_connection_wrong_url_never_queries(change):
    connection = synthetic_connection(**change)
    with pytest.raises(ValueError, match="OI_MIGRATION_CONNECTION_INVALID"):
        validate_migration_connection(connection, {})
    connection.execute.assert_not_called()


@pytest.mark.parametrize(
    "actual",
    [
        ("auvexo_app", "auvexo_dev_oiresearch", "127.0.0.1", 55433),
        ("auvexo_admin", "auvexo_dev", "127.0.0.1", 55433),
        ("auvexo_admin", "auvexo_dev_oiresearch", "::1", 55433),
        ("auvexo_admin", "auvexo_dev_oiresearch", "127.0.0.1", 55432),
    ],
)
def test_actual_bound_connection_must_match_not_just_url(actual):
    connection = synthetic_connection()
    connection.execute.return_value.one.return_value = actual
    with pytest.raises(ValueError, match="OI_MIGRATION_CONNECTION_INVALID"):
        validate_migration_connection(connection, {})


@pytest.mark.parametrize("value", [None, object(), "connection", 1])
def test_actual_connection_object_required(value):
    with pytest.raises(ValueError, match="OI_MIGRATION_CONNECTION_INVALID"):
        validate_migration_connection(value, {})


@pytest.mark.parametrize(
    "attributes",
    [
        {"oi_test_id": "uuid", "oi_test_port": 55550},
        {"oi_test_id": uuid4()},
        {"oi_test_port": 55550},
        {"oi_test_id": uuid4(), "oi_test_port": 55432},
        {"oi_test_id": uuid4(), "oi_test_port": 55433},
        {"oi_test_id": uuid4(), "oi_test_port": "55550"},
        {"oi_test_id": uuid4(), "oi_test_port": True},
    ],
)
def test_test_target_cannot_reach_production_or_operational(attributes):
    with pytest.raises(ValueError, match="OI_MIGRATION_TARGET_INVALID"):
        migration_target(attributes)


def test_uuid_test_target_exact_identity_only():
    identity = uuid4()
    attributes = {"oi_test_id": identity, "oi_test_port": 55551}
    database, port = migration_target(attributes)
    assert database == "auvexo_test_oi" + identity.hex
    assert port == 55551
    connection = synthetic_connection(database=database, port=port)
    connection.execute.return_value.one.return_value = (
        "auvexo_admin",
        "auvexo_admin",
        "none",
        database,
        "127.0.0.1",
        port,
    )
    validate_migration_connection(connection, attributes)


@pytest.mark.parametrize(
    "hostile", [None, "not-a-valid-dsn", "postgresql+psycopg://hostile/foreign"]
)
def test_programmatic_env_path_does_not_read_dsn(monkeypatch, hostile):
    if hostile is None:
        monkeypatch.delenv("AUVEXO_MIGRATION_DSN", raising=False)
    else:
        monkeypatch.setenv("AUVEXO_MIGRATION_DSN", hostile)
    connection = synthetic_connection()
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    monkeypatch.setattr(context, "config", config, raising=False)
    monkeypatch.setattr(context, "is_offline_mode", lambda: False)
    configure, run = MagicMock(), MagicMock()
    monkeypatch.setattr(context, "configure", configure)
    monkeypatch.setattr(context, "begin_transaction", nullcontext)
    monkeypatch.setattr(context, "run_migrations", run)
    runpy.run_path(str(ROOT / "migrations" / "env.py"))
    assert configure.call_args.kwargs["connection"] is connection
    run.assert_called_once()


def test_offline_refused_before_dsn_or_connection(monkeypatch):
    monkeypatch.delenv("AUVEXO_MIGRATION_DSN", raising=False)
    monkeypatch.setattr(context, "is_offline_mode", lambda: True)
    with pytest.raises(ValueError, match="offline migrations"):
        runpy.run_path(str(ROOT / "migrations" / "env.py"))


def test_migration_api_uses_config_attributes_not_text(monkeypatch):
    from auvexo_alpha.infrastructure import oi_migrations

    connection = synthetic_connection()
    call = MagicMock()
    monkeypatch.setattr(oi_migrations.command, "upgrade", call)
    migrate_oi_database(connection, ROOT)
    config = call.call_args.args[0]
    assert config.attributes == {"connection": connection}
    assert config.get_main_option("sqlalchemy.url") is None
    assert call.call_args.args[1] == "head"
    connection.execute.assert_not_called()


def test_programmatic_env_owns_only_missing_caller_transaction(monkeypatch):
    connection = synthetic_connection()
    connection.in_transaction.return_value = False
    connection.begin.return_value = nullcontext(connection)
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    monkeypatch.setattr(context, "config", config, raising=False)
    monkeypatch.setattr(context, "is_offline_mode", lambda: False)
    monkeypatch.setattr(context, "configure", MagicMock())
    monkeypatch.setattr(context, "begin_transaction", nullcontext)
    run = MagicMock()
    monkeypatch.setattr(context, "run_migrations", run)
    runpy.run_path(str(ROOT / "migrations" / "env.py"))
    connection.begin.assert_called_once()
    connection.commit.assert_not_called()
    connection.rollback.assert_not_called()
    run.assert_called_once()


def test_inherited_env_path_still_constructs_original_engine(monkeypatch):
    import sqlalchemy

    url = URL.create(
        "postgresql+psycopg",
        host="127.0.0.1",
        port=55432,
        username="auvexo_admin",
        database="auvexo_test",
    )
    monkeypatch.setenv("AUVEXO_MIGRATION_DSN", url.render_as_string())
    monkeypatch.setattr(context, "config", Config(), raising=False)
    monkeypatch.setattr(context, "is_offline_mode", lambda: False)
    connection = synthetic_connection()
    engine = MagicMock()
    engine.connect.return_value = nullcontext(connection)
    construct = MagicMock(return_value=engine)
    monkeypatch.setattr(sqlalchemy, "create_engine", construct)
    monkeypatch.setattr(context, "configure", MagicMock())
    monkeypatch.setattr(context, "begin_transaction", nullcontext)
    run = MagicMock()
    monkeypatch.setattr(context, "run_migrations", run)
    runpy.run_path(str(ROOT / "migrations" / "env.py"))
    assert construct.call_args.args[0] == url
    assert construct.call_args.kwargs["hide_parameters"] is True
    run.assert_called_once()
    engine.dispose.assert_called_once()


@pytest.mark.parametrize(
    "actual",
    [
        (
            "auvexo_admin",
            "foreign_login",
            "auvexo_admin",
            "auvexo_dev_oiresearch",
            "127.0.0.1",
            55433,
        ),
        (
            "auvexo_admin",
            "auvexo_admin",
            "auvexo_admin",
            "auvexo_dev_oiresearch",
            "127.0.0.1",
            55433,
        ),
    ],
)
def test_migrations_refuse_set_role_or_indirect_admin_login(actual):
    connection = synthetic_connection()
    connection.execute.return_value.one.return_value = actual
    with pytest.raises(ValueError, match="OI_MIGRATION_CONNECTION_INVALID"):
        validate_migration_connection(connection, {})
