"""Observation-only additive schema on top of the repository's declared main-chain head."""

import os
import re

from alembic import context
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from auvexo_alpha.infrastructure.database import SCHEMA_REVISION
from auvexo_alpha.infrastructure.paper_identity import (
    DISPOSABLE_MARKER_SQL,
    OPERATIONAL_PORT,
    DisposableCluster,
    attested_port,
    require_disposable_marker,
)

url = make_url(os.environ["AUVEXO_MIGRATION_DSN"])
database = url.database or ""
# Only a DSN that already names another port can be a disposable test cluster; the
# operational endpoint never consults the test cluster identity.
disposable = (
    None
    if url.port in (None, OPERATIONAL_PORT)
    else DisposableCluster(url.port, os.environ.get("TEST_PG_CLUSTER_ID", ""))
)
if (
    url.drivername != "postgresql+psycopg"
    or url.host != "127.0.0.1"
    or url.port != attested_port(database, disposable)
    or url.username != "auvexo_admin"
    or url.query
    or not re.fullmatch(r"auvexo_paperobs_[a-f0-9]{20}", database)
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
        if disposable is not None:
            marker = connection.execute(text(DISPOSABLE_MARKER_SQL)).one()
            require_disposable_marker(tuple(marker), disposable)
        if connection.scalar(text("SELECT version_num FROM alembic_version")) != SCHEMA_REVISION:
            raise ValueError("OBSERVATION_REQUIRES_DECLARED_MAIN_HEAD")
        connection.rollback()
        context.configure(
            connection=connection, target_metadata=None, version_table="paper_observation_version"
        )
        with context.begin_transaction():
            context.run_migrations()
finally:
    engine.dispose()
