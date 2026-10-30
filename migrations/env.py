"""Explicit local migration connection, separate from diagnostic app identity."""

import os
import re

from alembic import context
from sqlalchemy import Connection, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

if context.is_offline_mode():
    raise ValueError("offline migrations are not a substitute for real PostgreSQL proof")


def run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()


if "connection" in context.config.attributes:
    # This branch never reads the inherited DSN, including hostile environment input.
    from auvexo_alpha.infrastructure.oi_migrations import validate_migration_connection

    supplied = context.config.attributes["connection"]
    if not isinstance(supplied, Connection) or supplied.closed:
        raise ValueError("OI_MIGRATION_CONNECTION_INVALID")
    if supplied.in_transaction():
        # Caller owns this transaction; Alembic must not commit or roll it back.
        validate_migration_connection(supplied, context.config.attributes)
        run(supplied)
    else:
        # Begin BEFORE live identity inspection, whose SELECT would autobegin.
        # This branch commits/rolls back only the transaction it created itself.
        with supplied.begin():
            validate_migration_connection(supplied, context.config.attributes)
            run(supplied)
else:
    # Existing DEV/TEST/PAPER tools retain their explicit environment-based seam.
    url = make_url(os.environ["AUVEXO_MIGRATION_DSN"])
    if (
        url.drivername != "postgresql+psycopg"
        or url.host != "127.0.0.1"
        or not re.fullmatch(
            r"auvexo_((dev|test|restore)(_[a-z0-9]{1,32})?|paperobs_[a-f0-9]{20})",
            url.database or "",
        )
        or url.username != "auvexo_admin"
        or bool(url.query)
    ):
        raise ValueError("migrations require explicit local development/test database and migrator")
    engine = create_engine(
        url,
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={"connect_timeout": 3, "options": "-c statement_timeout=10000"},
    )
    try:
        with engine.connect() as connection:
            run(connection)
    finally:
        engine.dispose()
