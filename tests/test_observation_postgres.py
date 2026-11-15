"""Real PG observation isolation and NON_COUNTING date-forgery regression gates."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import psycopg
import pytest
from observation_fixtures import make_config, make_config_v2
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from auvexo_alpha.domain.observation import (
    ObservationResources,
    ObservationRunEvidence,
    ObservationStandingResume,
    ObservationStandingResumeUse,
    observation_window,
)
from auvexo_alpha.domain.paper_lifecycle import KillLevel
from auvexo_alpha.infrastructure.database import SCHEMA_REVISION
from auvexo_alpha.infrastructure.observation_store import (
    OBSERVATION_SCHEMA_HEAD,
    ObservationStore,
)
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
    for suffix in (
        "campaign",
        "activation",
        "run",
        "feed",
        "trace",
        "simulation",
        "receipt",
        "standing_resume",
    )
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
            SCHEMA_REVISION,
        )
        assert conn.execute("SELECT version_num FROM paper_observation_version").fetchone() == (
            OBSERVATION_SCHEMA_HEAD,
        )
        assert OBSERVATION_SCHEMA_HEAD == "obs0002_campaign_v2"
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
        # Pinned to the DS-02 record valid now. A campaign pinned to an earlier review is
        # correctly refused by prepare (OBSERVATION_CURRENT_SOURCE_RIGHTS_MISMATCH) once the
        # owner's 2026-11-14 renewal is the current record; only v2 can prepare at all.
        config = make_config_v2(campaign_id="synthetic.forged.v2", at=now)
        with pytest.raises(ValueError, match="OBSERVATION_CAMPAIGN_VERSION_RETIRED"):
            store.prepare(make_config(), now=now)
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


def test_obs0002_truth_reads_cooldowns_and_retains_spec_bytes_only(observation_database):
    engines = {g: engine_for(observation_database, g) for g in PAPER_GROUPS}
    try:
        with engines["auvexo_paper_truth"].connect() as conn:
            for table in (
                "data_cooldown_release",
                "data_cooldown_probe",
                "data_cooldown_probe_result",
            ):
                assert conn.scalar(text(f"SELECT count(*) FROM {table}")) == 0
            privileges = conn.execute(
                text(
                    "SELECT has_table_privilege(current_user,'data_spec','INSERT'),"
                    "has_table_privilege(current_user,'data_cooldown_probe','INSERT'),"
                    "has_table_privilege(current_user,'paper_observation_standing_resume',"
                    "'INSERT')"
                )
            ).one()
            assert tuple(privileges) == (True, False, False)
        for group in ("auvexo_paper", "auvexo_paper_owner"):
            with pytest.raises(DBAPIError), engines[group].connect() as conn:
                conn.execute(text("SELECT count(*) FROM data_cooldown_release"))
    finally:
        for engine in engines.values():
            engine.dispose()


def test_a_v1_campaign_row_cannot_begin_a_run_in_the_database(observation_database):
    owner = engine_for(observation_database, "auvexo_paper_owner")
    runtime = engine_for(observation_database, "auvexo_paper")
    legacy = make_config()
    try:
        with owner.begin() as conn:
            conn.execute(
                text("INSERT INTO paper_observation_campaign(campaign_hash,payload) VALUES(:h,:p)"),
                {"h": legacy.content_hash(), "p": legacy.canonical_bytes().decode()},
            )
        with pytest.raises(DBAPIError, match="OBSERVATION_CAMPAIGN_VERSION_RETIRED"):
            with runtime.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO paper_observation_run "
                        "(run_id,campaign_hash,kind,local_date,started_at,payload) "
                        "VALUES(:id,:h,'PREFLIGHT',CURRENT_DATE,now(),'{}')"
                    ),
                    {"id": str(uuid4()), "h": legacy.content_hash()},
                )
        # It stays readable as recorded.
        assert ObservationStore(runtime).config(legacy.content_hash()) == legacy
    finally:
        owner.dispose()
        runtime.dispose()


def activate(conn, activation_id, campaign_hash, reviewed_sha, authority_hash):
    conn.execute(
        "INSERT INTO paper_observation_activation"
        "(activation_id,campaign_hash,reviewed_sha,first_date,task_hash,authority_hash) "
        "VALUES(%s,%s,%s,(clock_timestamp() AT TIME ZONE 'Asia/Karachi')::date+1,%s,%s)",
        (activation_id, campaign_hash, reviewed_sha, "0" * 64, authority_hash),
    )


def standing(conn, activation_id, campaign_hash, payload):
    conn.execute(
        "INSERT INTO paper_observation_standing_resume"
        "(activation_id,campaign_hash,authority_hash,payload) VALUES(%s,%s,%s,%s)",
        (activation_id, campaign_hash, sha256(payload.encode()).hexdigest(), payload),
    )


def test_standing_resume_authority_is_bound_to_its_start_row(observation_database):
    owner = engine_for(observation_database, "auvexo_paper_owner")
    runtime = engine_for(observation_database, "auvexo_paper")
    config = make_config_v2(campaign_id="synthetic.standing.v2", at=datetime.now(UTC))
    good = ObservationStandingResume(
        campaign_hash=config.content_hash(),
        reviewed_sha=config.git_revision,
        start_resume_event_hash="5" * 64,
        valid_through="2027-01-31",
        owner="owner.founder",
    )
    try:
        with owner.begin() as conn:
            conn.execute(
                text("INSERT INTO paper_observation_campaign(campaign_hash,payload) VALUES(:h,:p)"),
                {"h": config.content_hash(), "p": config.canonical_bytes().decode()},
            )
        store = ObservationStore(runtime)
        assert store.standing_authority(config.content_hash()) is None
        foreign = good.model_copy(update={"reviewed_sha": "b" * 40})
        refusals = (
            # Payload for another reviewed commit than its START row.
            ("bad.sha", foreign.canonical_bytes().decode(), foreign.content_hash()),
            # A START row naming another authority than the payload.
            ("bad.hash", good.canonical_bytes().decode(), "0" * 64),
        )
        for activation_id, payload, authority_hash in refusals:
            with psycopg.connect(dbname=observation_database, **admin_args()) as conn:
                activate(
                    conn, activation_id, config.content_hash(), config.git_revision, authority_hash
                )
                with pytest.raises(psycopg.errors.RaiseException, match="BINDING_DENIED"):
                    standing(conn, activation_id, config.content_hash(), payload)
        with psycopg.connect(dbname=observation_database, **admin_args()) as conn:
            activate(
                conn, "owner.start", config.content_hash(), config.git_revision, good.content_hash()
            )
            standing(conn, "owner.start", config.content_hash(), good.canonical_bytes().decode())
        record = store.standing_authority(config.content_hash())
        assert record.activation_id == "owner.start" and record.authority == good
        assert record.authority_hash == good.content_hash()
        for group in PAPER_GROUPS:
            engine = engine_for(observation_database, group)
            try:
                with pytest.raises(DBAPIError), engine.begin() as conn:
                    conn.execute(
                        text(
                            "INSERT INTO paper_observation_standing_resume"
                            "(activation_id,campaign_hash,authority_hash,payload) "
                            "VALUES('owner.start',:h,repeat('0',64),'{}')"
                        ),
                        {"h": config.content_hash()},
                    )
            finally:
                engine.dispose()
    finally:
        owner.dispose()
        runtime.dispose()


def test_kernel_standing_resume_clears_only_writer_k1_at_the_journal_tail_it_read():
    with isolated_observation_database() as database:
        engines = [
            engine_for(database, g)
            for g in ("auvexo_paper", "auvexo_paper_owner", "auvexo_paper_truth")
        ]
        try:
            store = ObservationStore(*engines)
            config = make_config_v2(campaign_id="synthetic.kernel.resume", at=datetime.now(UTC))
            store.prepare(config, now=datetime.now(UTC))
            paper, account = store.paper, config.account_ref

            def use(tail):
                return ObservationStandingResumeUse(
                    authority_hash="1" * 64,
                    activation_id="owner.start",
                    run_id=uuid4(),
                    local_day=datetime.now(UTC).date().isoformat(),
                    boundary="START_RESUME",
                    boundary_hash="2" * 64,
                    boundary_journal_hash="3" * 64,
                    roll_event_hash="4" * 64,
                    examined_event_hashes=(tail,),
                    journal_tail_hash=tail,
                    evaluated_at=datetime.now(UTC),
                )

            paper.acquire_writer(account, now=datetime.now(UTC))
            assert paper.reconcile(account, now=datetime.now(UTC))
            with pytest.raises(ValueError, match="PAPER_STANDING_RESUME_SCOPE_DENIED"):
                paper.resume(
                    account,
                    actor="owner.founder",
                    now=datetime.now(UTC),
                    standing_use=use("9" * 64),
                )
            tail = paper.journal(account)[-1]["content_hash"]
            applied = use(tail)
            paper.resume(
                account, actor="owner.founder", now=datetime.now(UTC), standing_use=applied
            )
            event = paper.journal(account)[-1]
            assert event["kind"] == "OWNER_PAPER_RESUME"
            assert event["data"]["standing_use"] == json.loads(applied.canonical_bytes())
            assert paper.account(account).kill == KillLevel.K0
            # Any kill above the writer's K1 stays until the owner resumes it by hand.
            paper.acquire_writer(account, now=datetime.now(UTC))
            assert paper.reconcile(account, now=datetime.now(UTC))
            paper.set_kill(account, KillLevel.K2, actor="synthetic.loss", now=datetime.now(UTC))
            assert paper.reconcile(account, now=datetime.now(UTC))
            tail = paper.journal(account)[-1]["content_hash"]
            with pytest.raises(ValueError, match="PAPER_STANDING_RESUME_SCOPE_DENIED"):
                paper.resume(
                    account, actor="owner.founder", now=datetime.now(UTC), standing_use=use(tail)
                )
            assert paper.account(account).kill == KillLevel.K2
            assert paper.ledger_replay(account).mismatch_count == 0
        finally:
            for engine in engines:
                engine.dispose()
