"""Observation-only additive schema; accepted base migration head remains 0005."""

import os
import re

from alembic import context
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

url = make_url(os.environ["AUVEXO_MIGRATION_DSN"])
if (
    url.drivername != "postgresql+psycopg"
    or url.host != "127.0.0.1"
    or url.port != 55432
    or url.username != "auvexo_admin"
    or url.query
    or not re.fullmatch(r"auvexo_paperobs_[a-f0-9]{20}", url.database or "")
    or context.is_offline_mode()
):
    raise ValueError("OBSERVATION_LOCAL_MIGRATION_BOUNDARY")
engine = create_engine(
    url,
    poolclass=NullPool,
    hide_parameters=True,
    connect_args={"connect_timeout": 3, "options": "-c timezone=UTC -c statement_timeout=10000"},
)
try:
    with engine.connect() as connection:
        if connection.scalar(text("SELECT version_num FROM alembic_version")) != "0005_paper_core":
            raise ValueError("OBSERVATION_REQUIRES_ACCEPTED_BASE_0005")
        connection.rollback()
        context.configure(
            connection=connection, target_metadata=None, version_table="paper_observation_version"
        )
        with context.begin_transaction():
            context.run_migrations()
finally:
    engine.dispose()
