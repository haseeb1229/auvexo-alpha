"""Explicit local migration connection, separate from diagnostic app identity."""

import os
import re

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

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
if context.is_offline_mode():
    raise ValueError("offline migrations are not a substitute for real PostgreSQL proof")
engine = create_engine(
    url,
    poolclass=NullPool,
    hide_parameters=True,
    connect_args={"connect_timeout": 3, "options": "-c statement_timeout=10000"},
)
try:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()
finally:
    engine.dispose()
