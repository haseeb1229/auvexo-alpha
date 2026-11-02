"""In-process OI migration connection checks; no environment or password serialization."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, text

OI_DATABASE = "auvexo_dev_oiresearch"
OI_PORT = 55433
OI_ADMIN = "auvexo_admin"


def migration_target(attributes: dict[str, object]) -> tuple[str, int]:
    """Production is fixed. The private test seam can name only a UUID test database.

    Neither an environment variable nor a command-line flag selects this seam. It
    cannot address the production name, production port or operational server.
    """
    if "oi_test_id" not in attributes and "oi_test_port" not in attributes:
        return OI_DATABASE, OI_PORT
    identity = attributes.get("oi_test_id")
    port = attributes.get("oi_test_port")
    if not isinstance(identity, UUID) or type(port) is not int or not 55500 <= port <= 55999:
        raise ValueError("OI_MIGRATION_TARGET_INVALID")
    return "auvexo_test_oi" + identity.hex, port


def validate_migration_connection(connection: Connection, attributes: dict[str, object]) -> None:
    database, port = migration_target(attributes)
    if not isinstance(connection, Connection) or connection.closed:
        raise ValueError("OI_MIGRATION_CONNECTION_INVALID")
    url = connection.engine.url
    if (
        url.drivername != "postgresql+psycopg"
        or url.host != "127.0.0.1"
        or url.username != OI_ADMIN
        or url.database != database
        or url.port != port
        or bool(url.query)
        or connection.dialect.name != "postgresql"
        or connection.dialect.driver != "psycopg"
    ):
        raise ValueError("OI_MIGRATION_CONNECTION_INVALID")
    actual = connection.execute(
        text(
            "SELECT current_user,session_user,current_setting('role'),current_database(),"
            "host(inet_server_addr()),inet_server_port()"
        )
    ).one()
    if tuple(actual) != (OI_ADMIN, OI_ADMIN, "none", database, "127.0.0.1", port):
        raise ValueError("OI_MIGRATION_CONNECTION_INVALID")


def migrate_oi_database(
    connection: Connection,
    source_root: Path,
    *,
    _test_id: UUID | None = None,
    _test_port: int | None = None,
) -> None:
    """Alembic receives the live Connection, never a plaintext URL/config/env value."""
    config = Config(str(source_root / "alembic.ini"))
    config.set_main_option("path_separator", "os")
    config.attributes["connection"] = connection
    if _test_id is not None or _test_port is not None:
        config.attributes["oi_test_id"] = _test_id
        config.attributes["oi_test_port"] = _test_port
    command.upgrade(config, "head")
