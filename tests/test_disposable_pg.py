"""Disposable test clusters: the operational endpoints stay unreachable from every test."""

import json
import os
import shutil
import socket
import sys
from pathlib import Path
from uuid import uuid4

import psutil
import psycopg
import pytest
from psycopg import sql
from sqlalchemy import URL, create_engine

from auvexo_alpha.infrastructure.paper_identity import (
    DISPOSABLE_MARKER_SQL,
    DisposableCluster,
    PaperIdentityError,
    attested_port,
    enforce_paper_engine,
    require_disposable_marker,
)
from tools import disposable_pg
from tools.local_db import login_role_sql

ID = "0123456789abcdef0123456789abcdef"
GENERATED = ("auvexo_test_", "auvexo_restore_", "auvexo_paperobs_")


@pytest.mark.parametrize(
    "port,cluster_id",
    [
        (55432, ID),
        (55433, ID),
        (1023, ID),
        (65536, ID),
        (True, ID),
        ("41000", ID),
        (41000, ID.upper()),
        (41000, ID[:-1]),
        (41000, "g" * 32),
        (41000, None),
    ],
)
def test_disposable_cluster_refuses_operational_ports_and_malformed_ids(port, cluster_id):
    with pytest.raises(PaperIdentityError, match="^DISPOSABLE_CLUSTER_INVALID$"):
        DisposableCluster(port, cluster_id)


@pytest.mark.parametrize(
    "database",
    ["auvexo_dev", "auvexo_test", "postgres", "auvexo_paperobs_x", "auvexo_test_" + "a" * 19],
)
def test_production_and_shared_names_only_ever_attest_the_operational_port(database):
    assert attested_port(database, None) == 55432
    with pytest.raises(PaperIdentityError, match="^DISPOSABLE_CLUSTER_DATABASE_DENIED$"):
        attested_port(database, DisposableCluster(41000, ID))


@pytest.mark.parametrize("prefix", GENERATED)
def test_generated_names_attest_the_disposable_port_only_when_named(prefix):
    database = prefix + "a" * 20
    assert attested_port(database, None) == 55432
    assert attested_port(database, DisposableCluster(41000, ID)) == 41000


@pytest.mark.parametrize(
    "row",
    [
        None,
        (),
        (ID,),
        (ID, ""),
        # A client can set the custom setting for its own session, but not cluster_name.
        (ID, "auvexo-disposable-" + "f" * 32),
        ("f" * 32, "auvexo-disposable-" + ID),
        (None, "auvexo-disposable-" + ID),
        (ID, "auvexo-disposable-" + ID, "extra"),
    ],
)
def test_marker_requires_the_exact_server_pair(row):
    with pytest.raises(PaperIdentityError, match="^DISPOSABLE_CLUSTER_MARKER_DENIED$"):
        require_disposable_marker(row, DisposableCluster(41000, ID))
    require_disposable_marker((ID, "auvexo-disposable-" + ID), DisposableCluster(41000, ID))


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"TEST_PG_PORT": "41000"},
        {"TEST_PG_CLUSTER_ID": ID},
        {"TEST_PG_PORT": "55432", "TEST_PG_CLUSTER_ID": ID},
        {"TEST_PG_PORT": "55433", "TEST_PG_CLUSTER_ID": ID},
        {"TEST_PG_PORT": " 41000", "TEST_PG_CLUSTER_ID": ID},
        {"TEST_PG_PORT": "41000.0", "TEST_PG_CLUSTER_ID": ID},
        {"TEST_PG_PORT": "٤١٠٠٠", "TEST_PG_CLUSTER_ID": ID},
        {"TEST_PG_PORT": "041000", "TEST_PG_CLUSTER_ID": ID},
    ],
)
def test_harness_cluster_from_environment_fails_closed(environment, monkeypatch):
    for name in ("TEST_PG_PORT", "TEST_PG_CLUSTER_ID"):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    with pytest.raises((RuntimeError, ValueError)):
        disposable_pg.harness_cluster()


def test_unbound_engine_on_a_test_port_is_refused_before_any_connection():
    # A production caller names no cluster, so only the operational port can attest.
    url = URL.create(
        "postgresql+psycopg",
        username="auvexo_pw_" + "a" * 20,
        password="synthetic-only",
        host="127.0.0.1",
        port=41000,
        database="auvexo_test_" + "a" * 20,
    )
    engine = create_engine(url)
    try:
        with pytest.raises(PaperIdentityError, match="^PAPER_IDENTITY_ENDPOINT_OR_LOGIN_DENIED$"):
            enforce_paper_engine(engine, "auvexo_paper")
        # Naming a cluster does not admit a shared or production database either.
        with pytest.raises(PaperIdentityError, match="^PAPER_IDENTITY_DATABASE_OR_GROUP_DENIED$"):
            enforce_paper_engine(
                create_engine(url.set(database="auvexo_dev")),
                "auvexo_paper",
                disposable=DisposableCluster(41000, ID),
            )
        # The named cluster's port must be the engine's advertised port.
        with pytest.raises(PaperIdentityError, match="^PAPER_IDENTITY_ENDPOINT_OR_LOGIN_DENIED$"):
            enforce_paper_engine(engine, "auvexo_paper", disposable=DisposableCluster(41001, ID))
    finally:
        engine.dispose()


def test_free_port_skips_operational_occupied_and_unbindable_ports(monkeypatch):
    assert 55432 not in disposable_pg.PORTS and 55433 not in disposable_pg.PORTS
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        taken = occupied.getsockname()[1]
        free = next(p for p in (41001, 41002, 41003) if not disposable_pg.port_bound(p))
        choices = iter([55432, taken, free])
        monkeypatch.setattr(disposable_pg, "PORTS", [55432, taken, free])
        positions = {55432: 0, taken: 1, free: 2}
        monkeypatch.setattr(disposable_pg.secrets, "randbelow", lambda n: positions[next(choices)])
        assert disposable_pg.free_port() == free


def _fake_root(pid: int) -> Path:
    """A descriptor naming a process that is NOT this cluster's postmaster."""
    cluster_id = uuid4().hex
    root = disposable_pg.expected_root(cluster_id)
    (root / "data").mkdir(parents=True)
    (root / "data/postgresql.conf").write_text(
        f"auvexo.disposable_cluster = '{cluster_id}'\n", encoding="utf-8"
    )
    (root / "data/postmaster.pid").write_text(f"{pid}\n", encoding="ascii")
    (root / "descriptor.json").write_text(
        json.dumps(
            {
                "version": 1,
                "cluster_id": cluster_id,
                "root": str(root),
                "port": 41000,
                "pid": pid,
                "pid_created": psutil.Process(pid).create_time(),
                "passwords": {role: "synthetic" for role in disposable_pg.ROLES},
            }
        ),
        encoding="utf-8",
    )
    return root


def test_destroy_never_stops_or_deletes_a_process_it_cannot_prove_is_its_postmaster():
    root = _fake_root(os.getpid())
    try:
        with pytest.raises(RuntimeError, match="^DISPOSABLE_CLUSTER_PID_MISMATCH"):
            disposable_pg.destroy(root / "descriptor.json")
        assert root.is_dir() and psutil.pid_exists(os.getpid())
    finally:
        shutil.rmtree(root)


def test_destroy_refuses_a_descriptor_outside_its_own_uuid_root(tmp_path):
    root = _fake_root(os.getpid())
    try:
        moved = tmp_path / "descriptor.json"
        shutil.copy(root / "descriptor.json", moved)
        with pytest.raises(ValueError, match="^DISPOSABLE_CLUSTER_DESCRIPTOR_ROOT_MISMATCH$"):
            disposable_pg.destroy(moved)
        payload = json.loads((root / "descriptor.json").read_text(encoding="utf-8"))
        payload["root"] = str(tmp_path)
        (root / "descriptor.json").write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError, match="^DISPOSABLE_CLUSTER_DESCRIPTOR_ROOT_MISMATCH$"):
            disposable_pg.destroy(root / "descriptor.json")
        assert root.is_dir() and tmp_path.is_dir()
    finally:
        shutil.rmtree(root)


@pytest.mark.parametrize("name", ["auvexo-disposable-pg-x", "other", ""])
def test_remove_refuses_any_path_but_a_disposable_temp_root(tmp_path, name):
    target = tmp_path / name if name else Path(disposable_pg.tempfile.gettempdir())
    with pytest.raises(RuntimeError, match="^DISPOSABLE_CLUSTER_ROOT_REFUSED$"):
        disposable_pg._remove(target)
    assert tmp_path.is_dir()


# --- Real disposable cluster ---------------------------------------------------------------


@pytest.mark.integration
def test_harness_proves_the_marker_on_the_connection_and_refuses_another_id():
    cluster = disposable_pg.harness_cluster()
    args = disposable_pg.harness_args("app")
    with psycopg.connect(dbname="auvexo_test", **args) as conn:
        disposable_pg.require_disposable(conn, cluster)
        with pytest.raises(PaperIdentityError, match="^DISPOSABLE_CLUSTER_MARKER_DENIED$"):
            disposable_pg.require_disposable(conn, DisposableCluster(cluster.port, uuid4().hex))
    # A client may set the custom setting for itself; it still cannot forge the pair.
    forged = uuid4().hex
    options = f"-c auvexo.disposable_cluster={forged}"
    with psycopg.connect(dbname="auvexo_test", options=options, **args) as conn:
        assert conn.execute(DISPOSABLE_MARKER_SQL).fetchone()[0] == forged
        with pytest.raises(PaperIdentityError, match="^DISPOSABLE_CLUSTER_MARKER_DENIED$"):
            disposable_pg.require_disposable(conn, DisposableCluster(cluster.port, forged))
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(dbname="auvexo_test", options="-c cluster_name=forged", **args)


@pytest.mark.integration
def test_scram_verifier_roles_log_in_and_the_password_never_reaches_the_server():
    admin = disposable_pg.harness_args("admin")
    role = "auvexo_scram_" + uuid4().hex[:20]
    password = uuid4().hex + uuid4().hex
    with psycopg.connect(dbname="postgres", autocommit=True, **admin) as conn:
        statement = login_role_sql(conn, role, password, "NOSUPERUSER NOCREATEDB NOCREATEROLE")
        sent = statement.as_string(conn)
        assert password not in sent and "SCRAM-SHA-256$4096:" in sent
        conn.execute(statement)
        try:
            stored = conn.execute(
                "SELECT rolpassword FROM pg_authid WHERE rolname=%s", (role,)
            ).fetchone()[0]
            assert stored.startswith("SCRAM-SHA-256$4096:") and stored in sent
            # A failing statement is what a server would log; it still carries no password.
            with pytest.raises(psycopg.errors.DuplicateObject):
                conn.execute(login_role_sql(conn, role, password, "NOSUPERUSER"))
            target = dict(admin, user=role)
            target.pop("password")
            with psycopg.connect(dbname="postgres", password=password, **target) as login:
                assert login.execute("SELECT current_user").fetchone() == (role,)
            with pytest.raises(psycopg.OperationalError, match="password authentication failed"):
                psycopg.connect(dbname="postgres", password=password[::-1], **target)
        finally:
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


_TOOLCHAIN = disposable_pg.PG / ("initdb" + disposable_pg._EXE)


@pytest.mark.integration
@pytest.mark.skipif(not _TOOLCHAIN.exists(), reason="local PostgreSQL toolchain only")
def test_create_then_destroy_leaves_no_process_port_or_directory():
    descriptor = disposable_pg.create()
    process = psutil.Process(descriptor.pid)
    try:
        assert descriptor.root.parent == Path(disposable_pg.tempfile.gettempdir()).resolve()
        assert not descriptor.root.is_relative_to(disposable_pg.ROOT.resolve())
        assert descriptor.port not in (55432, 55433) and disposable_pg.port_bound(descriptor.port)
        with psycopg.connect(
            host="127.0.0.1",
            port=descriptor.port,
            user="auvexo_admin",
            password=descriptor.passwords["admin"],
            dbname="postgres",
        ) as conn:
            disposable_pg.require_disposable(conn, descriptor.cluster)
        assert not (descriptor.root / "initdb.pw").exists()
        if sys.platform == "win32":
            # Owner-only ACL from the shared helper: no inherited entries remain.
            assert (
                disposable_pg.subprocess.run(
                    ["icacls", str(descriptor.root / "descriptor.json")],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.count("(F)")
                == 1
            )
    finally:
        disposable_pg.destroy(descriptor.root / "descriptor.json")
    assert not descriptor.root.exists()
    assert not process.is_running()
    assert not disposable_pg.port_bound(descriptor.port)


@pytest.mark.integration
def test_observation_migration_on_a_test_port_requires_the_matching_marker():
    from tools.paper_observation_local import isolated_observation_database

    cluster = disposable_pg.harness_cluster()
    admin = disposable_pg.harness_args("admin")
    with isolated_observation_database() as name:
        dsn = URL.create(
            "postgresql+psycopg",
            username="auvexo_admin",
            password=admin["password"],
            host="127.0.0.1",
            port=cluster.port,
            database=name,
        ).render_as_string(hide_password=False)
        for cluster_id, reason in (
            (None, "DISPOSABLE_CLUSTER_INVALID"),
            (uuid4().hex, "DISPOSABLE_CLUSTER_MARKER_DENIED"),
        ):
            environment = {k: v for k, v in os.environ.items() if k != "TEST_PG_CLUSTER_ID"}
            environment["AUVEXO_MIGRATION_DSN"] = dsn
            if cluster_id is not None:
                environment["TEST_PG_CLUSTER_ID"] = cluster_id
            result = disposable_pg.subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "alembic",
                    "-c",
                    "alembic-observation.ini",
                    "upgrade",
                    "head",
                ],
                cwd=disposable_pg.ROOT,
                env=environment,
                capture_output=True,
                timeout=120,
                check=False,
            )
            assert result.returncode != 0
            assert reason in result.stderr.decode(errors="replace")


def test_persistent_observation_names_stay_operational_whatever_the_environment(monkeypatch):
    from tools import paper_observation_local

    # A configured test cluster is visible, yet a name this process did not generate
    # is the persistent campaign database and is never moved off the operational port.
    monkeypatch.setenv("TEST_PG_PORT", "41000")
    monkeypatch.setenv("TEST_PG_CLUSTER_ID", ID)
    name = "auvexo_paperobs_" + "a" * 20
    assert paper_observation_local._cluster(name) is None
    assert paper_observation_local._port(name) == 55432
