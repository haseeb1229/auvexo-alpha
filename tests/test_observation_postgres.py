"""Real PG observation isolation and NON_COUNTING date-forgery regression gates."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from observation_fixtures import make_config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from auvexo_alpha.domain.observation import (
    ObservationResources,
    ObservationRunEvidence,
    observation_window,
)
from auvexo_alpha.infrastructure.observation_store import ObservationStore
from auvexo_alpha.infrastructure.paper_identity import PaperIdentityError
from tools.paper_local import PAPER_GROUPS, admin_args
from tools.paper_observation_local import (
    engine_for,
    isolated_observation_database,
    load_credentials,
    migrate,
    provision_services,
)

pytestmark = pytest.mark.integration
TABLES = tuple(
    "paper_observation_" + suffix
    for suffix in ("campaign", "activation", "run", "feed", "trace", "simulation", "receipt")
)


@pytest.fixture(scope="module")
def observation_database():
    with isolated_observation_database() as database:
        yield database


def test_observation_extension_leaves_accepted_base_and_is_idempotent(observation_database):
    migrate(observation_database)
    provision_services(observation_database)
    with psycopg.connect(dbname=observation_database, **admin_args()) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0005_paper_core",
        )
        assert conn.execute("SELECT version_num FROM paper_observation_version").fetchone() == (
            "obs0001_qualification",
        )
        assert conn.execute(
            "SELECT execution_enabled,binance_live_derivatives FROM foundation_policy"
        ).fetchone() == (False, "BLOCKED_BY_POLICY")
        assert conn.execute("SELECT count(*) FROM paper_observation_activation").fetchone() == (0,)


@pytest.mark.parametrize("group", PAPER_GROUPS)
def test_observation_direct_login_survives_commit_rollback_pool_and_reconnect(
    observation_database, group
):
    credential = load_credentials(observation_database, group)
    engine = engine_for(observation_database, group)
    try:
        for _ in range(3):
            with engine.connect() as conn:
                assert conn.execute(text("SELECT current_user,session_user")).one() == (
                    credential.username,
                    credential.username,
                )
                conn.rollback()
                with pytest.raises(DBAPIError):
                    conn.execute(text("SET ROLE auvexo_admin"))
                conn.rollback()
                assert (
                    conn.scalar(text("SELECT rolsuper FROM pg_roles WHERE rolname=current_user"))
                    is False
                )
                conn.commit()
        engine.dispose()
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT current_user")) == credential.username
    finally:
        engine.dispose()


@pytest.mark.parametrize("group", PAPER_GROUPS)
@pytest.mark.parametrize(
    "statement",
    (
        "UPDATE foundation_policy SET execution_enabled=true",
        "DELETE FROM research_study",
        "CREATE TABLE observation_forbidden(id integer)",
        "CREATE SCHEMA observation_forbidden",
        "CREATE TEMP TABLE observation_forbidden(id integer)",
        "CREATE ROLE observation_forbidden",
        "SET SESSION AUTHORIZATION auvexo_admin",
        "GRANT auvexo_paper_owner TO CURRENT_USER",
    ),
)
def test_observation_no_privilege_escalation(observation_database, group, statement):
    engine = engine_for(observation_database, group)
    try:
        with pytest.raises(DBAPIError), engine.begin() as conn:
            conn.execute(text(statement))
    finally:
        engine.dispose()


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize(
    "action",
    ("UPDATE {table} SET payload=payload", "DELETE FROM {table}", "TRUNCATE {table} CASCADE"),
)
def test_observation_immutable_histories_even_admin(observation_database, table, action):
    if table == "paper_observation_activation" and action.startswith("UPDATE"):
        action = "UPDATE {table} SET authority_hash=authority_hash"
    with psycopg.connect(dbname=observation_database, **admin_args()) as conn:
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute(action.format(table=table))
        conn.rollback()


@pytest.mark.parametrize("group", PAPER_GROUPS)
def test_observation_no_service_can_mint_start(observation_database, group):
    engine = engine_for(observation_database, group)
    try:
        with pytest.raises(DBAPIError), engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO paper_observation_activation VALUES "
                    "('forged',repeat('0',64),repeat('a',40),CURRENT_DATE+1,repeat('0',64),"
                    "repeat('0',64),current_database(),clock_timestamp())"
                )
            )
    finally:
        engine.dispose()


def test_observation_runtime_cannot_manufacture_feed_or_source(observation_database):
    engine = engine_for(observation_database, "auvexo_paper")
    try:
        for statement in (
            "INSERT INTO paper_observation_feed VALUES (repeat('0',64),'forged',repeat('0',64),"
            "'BTCUSDT',now(),now(),'{}',now())",
            "INSERT INTO data_source_review VALUES(repeat('0',64),'{}')",
            "INSERT INTO data_manifest VALUES(repeat('0',64),'forged',repeat('0',64),"
            "now(),NULL,repeat('0',64),'{}')",
            "INSERT INTO paper_truth_event"
            "(event_id,account_ref,kind,content_hash,payload,recorded_at) "
            "VALUES('forged','paper.observation','STATUS',repeat('0',64),'{}',now())",
        ):
            with pytest.raises(DBAPIError), engine.begin() as conn:
                conn.execute(text(statement))
    finally:
        engine.dispose()


def test_observation_admin_or_wrong_scope_credential_refused(observation_database):
    credential = load_credentials(observation_database, "auvexo_paper")
    with pytest.raises(ValueError):
        engine_for(observation_database, None)
    for change in (
        {"username": "auvexo_admin"},
        {"database": "auvexo_dev"},
        {"role": "auvexo_paper_owner"},
    ):
        with pytest.raises(ValueError):
            engine_for(
                observation_database, "auvexo_paper", credential=replace(credential, **change)
            )
    with pytest.raises(PaperIdentityError):
        engine_for(
            observation_database, "auvexo_paper", credential=replace(credential, password="invalid")
        )


def test_observation_prepared_manual_and_forged_pass_never_count(observation_database):
    engines = [
        engine_for(observation_database, g)
        for g in ("auvexo_paper", "auvexo_paper_owner", "auvexo_paper_truth")
    ]
    try:
        store = ObservationStore(engines[0], engines[1], engines[2])
        now = datetime.now(UTC)
        config = make_config()
        config_hash = store.prepare(config, now=now)
        with pytest.raises(ValueError, match="OWNER_START_REQUIRED"):
            store.begin(config_hash, kind="SCHEDULED", now=now)
        with pytest.raises(DBAPIError), engines[0].begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO paper_observation_run VALUES "
                    "(:id,:hash,'SCHEDULED','2000-01-01',:now,NULL,current_database(),'{}')"
                ),
                {"id": str(uuid4()), "hash": config_hash, "now": now},
            )
        run_id = store.begin(config_hash, now=now)
        run = store.run(run_id)
        store.paper.acquire_writer(config.account_ref, now=datetime.now(UTC))
        store.paper.reconcile(config.account_ref, now=datetime.now(UTC))
        end = datetime.now(UTC)
        evidence = ObservationRunEvidence(
            run_id=run_id,
            campaign_id=config.campaign_id,
            local_day=run["local_date"].isoformat(),
            kind="NON_COUNTING",
            scheduled_at=observation_window(run["local_date"])[0],
            started_at=run["started_at"],
            ended_at=end,
            config_hash=config_hash,
            **store.snapshot(run_id),
            resource_snapshots=(
                ObservationResources(
                    observed_at=end,
                    available_ram_bytes=4_000_000_000,
                    cpu_percent="0",
                    cpu_high_for_seconds=0,
                ),
            ),
        )
        receipt = store.close(run_id, evidence, now=datetime.now(UTC))
        assert receipt.status == "INCOMPLETE"
        assert store.qualified_dates(config_hash, now=datetime.now(UTC)).qualified_count == 0
        with pytest.raises(DBAPIError), engines[0].begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO paper_observation_receipt VALUES "
                    "(repeat('1',64),:run,:campaign,:day,'PASS','{}',now())"
                ),
                {"run": str(run_id), "campaign": config_hash, "day": run["local_date"]},
            )
        assert store.qualified_dates(config_hash, now=datetime.now(UTC)).qualified_count == 0
        with pytest.raises(DBAPIError):
            store.close(run_id, evidence, now=datetime.now(UTC))
    finally:
        for engine in engines:
            engine.dispose()


@pytest.mark.parametrize(
    "group,table",
    (
        ("auvexo_paper", "paper_observation_receipt"),
        ("auvexo_paper_truth", "data_source_review"),
        ("auvexo_paper_owner", "paper_observation_campaign"),
    ),
)
def test_observation_pooled_checkout_rejects_required_grant_revocation(
    observation_database, group, table
):
    from psycopg import sql

    engine = engine_for(observation_database, group)
    try:
        with psycopg.connect(dbname=observation_database, **admin_args()) as admin:
            admin.execute(
                sql.SQL("REVOKE INSERT ON {} FROM {}").format(
                    sql.Identifier(table), sql.Identifier(group)
                )
            )
        with pytest.raises(PaperIdentityError, match="REQUIRED_GRANT_MISSING"), engine.connect():
            pass
    finally:
        with psycopg.connect(dbname=observation_database, **admin_args()) as admin:
            admin.execute(
                sql.SQL("GRANT INSERT ON {} TO {}").format(
                    sql.Identifier(table), sql.Identifier(group)
                )
            )
        engine.dispose()


@pytest.mark.parametrize("group", PAPER_GROUPS)
@pytest.mark.parametrize("attribute", ("NOLOGIN", "CREATEDB", "CREATEROLE", "BYPASSRLS"))
def test_observation_pooled_checkout_rejects_identity_drift(observation_database, group, attribute):
    from psycopg import sql

    engine = engine_for(observation_database, group)
    login = load_credentials(observation_database, group).username
    try:
        with psycopg.connect(dbname=observation_database, **admin_args()) as admin:
            admin.execute(sql.SQL("ALTER ROLE {} " + attribute).format(sql.Identifier(login)))
        with pytest.raises(PaperIdentityError), engine.connect():
            pass
    finally:
        with psycopg.connect(dbname=observation_database, **admin_args()) as admin:
            admin.execute(
                sql.SQL("ALTER ROLE {} LOGIN NOCREATEDB NOCREATEROLE NOBYPASSRLS").format(
                    sql.Identifier(login)
                )
            )
        engine.dispose()
