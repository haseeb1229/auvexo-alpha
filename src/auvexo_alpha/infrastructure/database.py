"""Bounded read-only diagnostic queries against the real foundation schema."""

from sqlalchemy import URL, Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from auvexo_alpha.application.safety import POLICY_VERSION
from auvexo_alpha.config import Settings

SCHEMA_REVISION = "0001_foundation"


def make_engine(settings: Settings) -> Engine:
    url = URL.create(
        "postgresql+psycopg",
        username=settings.database_user,
        password=settings.database_password.get_secret_value(),
        host=settings.database_host,
        port=settings.database_port,
        database=settings.database_name,
    )
    return create_engine(
        url,
        pool_size=2,
        max_overflow=0,
        pool_timeout=2,
        connect_args={"connect_timeout": 2, "options": "-c statement_timeout=2000"},
        hide_parameters=True,
    )


class DatabaseProbe:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def ready(self) -> bool:
        try:
            with self.engine.connect() as conn:
                revision = conn.scalar(text("SELECT version_num FROM alembic_version"))
                policy = conn.execute(
                    text(
                        "SELECT policy_version, execution_enabled, binance_live_derivatives "
                        "FROM foundation_policy WHERE singleton_id = 1"
                    )
                ).one()
                privileges = conn.execute(
                    text(
                        "SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles "
                        "WHERE rolname = current_user"
                    )
                ).one()
                return (
                    revision == SCHEMA_REVISION
                    and policy[0] == POLICY_VERSION
                    and policy[1] is False
                    and policy[2] == "BLOCKED_BY_POLICY"
                    and not any(privileges)
                )
        except SQLAlchemyError:
            # Dependency failure is reported as NOT_READY; never emit a DSN or driver detail.
            return False
