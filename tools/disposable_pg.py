"""Disposable PostgreSQL 17 clusters for the test suite; never the operational endpoint.

Each cluster lives in its own UUID-named directory under the user's temporary directory,
outside every checkout. It listens on 127.0.0.1 only, on a free high port that is never
55432 (operational) or 55433 (open-interest runtime), authenticates with SCRAM, and carries
the server settings ``auvexo.disposable_cluster = '<uuid>'`` and the start-only
``cluster_name = 'auvexo-disposable-<uuid>'``. Every PostgreSQL test helper
refuses the operational ports and proves that marker before writing, so a misconfigured
run cannot reach a real cluster.

    python tools/disposable_pg.py test [pytest arguments]   # create, run all tests, destroy
    python tools/disposable_pg.py run -- COMMAND ...         # same, for any command
    python tools/disposable_pg.py create | describe D | destroy D

``destroy`` removes only the exact directory it created, after checking the descriptor's
UUID, the directory and that the running postmaster is the recorded process.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import psutil
import psycopg
from psycopg import sql
from sqlalchemy import URL

from auvexo_alpha.infrastructure.paper_identity import (
    DISPOSABLE_CLUSTER_NAME_PREFIX,
    DISPOSABLE_MARKER_SQL,
    OI_RUNTIME_PORT,
    OPERATIONAL_PORT,
    DisposableCluster,
    require_disposable_marker,
)

if __package__:
    from tools.local_db import NO_WINDOW, login_role_sql, port_bound, safe_window, write_private
else:
    from local_db import NO_WINDOW, login_role_sql, port_bound, safe_window, write_private

ROOT = Path(__file__).resolve().parents[1]
PG = ROOT / ".local/toolchains/postgres/pgsql/bin"
PREFIX = "auvexo-disposable-pg-"
PORTS = range(41000, 49000)
ROLES = ("admin", "app", "data_writer")
DATABASE = "auvexo_test"
_EXE = ".exe" if os.name == "nt" else ""


# --- Harness: what every PostgreSQL test helper uses -------------------------------------


def harness_cluster() -> DisposableCluster:
    """The disposable cluster the test environment names; the operational ports never are."""
    port = os.environ.get("TEST_PG_PORT")
    cluster_id = os.environ.get("TEST_PG_CLUSTER_ID")
    if port is None or cluster_id is None:
        raise RuntimeError(
            "DISPOSABLE_TEST_CLUSTER_REQUIRED: run python tools/disposable_pg.py test"
        )
    if not port.isascii() or not port.isdecimal() or len(port) > 5:
        raise ValueError("DISPOSABLE_CLUSTER_INVALID")
    return DisposableCluster(int(port), cluster_id)


def require_disposable(conn: psycopg.Connection[Any], cluster: DisposableCluster) -> None:
    """Prove, on this very connection, that the server is the named disposable cluster."""
    info = conn.info
    if (info.host, info.port) != ("127.0.0.1", cluster.port):
        raise ValueError("DISPOSABLE_CLUSTER_ENDPOINT_DENIED")
    require_disposable_marker(conn.execute(DISPOSABLE_MARKER_SQL).fetchone(), cluster)


def harness_args(role: str = "admin") -> dict[str, Any]:
    """Connection arguments for a harness role, proven against the marker before return."""
    if role not in ROLES:
        raise ValueError("DISPOSABLE_CLUSTER_ROLE_DENIED")
    cluster = harness_cluster()
    password = os.environ.get(f"TEST_PG_{role.upper()}_PASSWORD")
    if not password:
        raise RuntimeError("DISPOSABLE_TEST_CLUSTER_REQUIRED: harness password missing")
    args: dict[str, Any] = dict(
        host="127.0.0.1",
        port=cluster.port,
        user=f"auvexo_{role}",
        password=password,
        connect_timeout=3,
    )
    database = DATABASE if role != "admin" else "postgres"
    with psycopg.connect(dbname=database, autocommit=True, **args) as conn:
        require_disposable(conn, cluster)
    return args


def provision(
    admin: Mapping[str, Any], passwords: Mapping[str, str], cluster: DisposableCluster
) -> None:
    """The one provisioning path for local disposable clusters and hosted CI.

    The admin connection must already reach ``cluster``; roles get SCRAM verifiers only.
    """
    with psycopg.connect(dbname="postgres", autocommit=True, **admin) as conn:
        require_disposable(conn, cluster)
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (DATABASE,)).fetchone():
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DATABASE)))
        conn.execute(
            login_role_sql(
                conn, "auvexo_app", passwords["app"], "NOSUPERUSER NOCREATEDB NOCREATEROLE"
            )
        )
    with psycopg.connect(dbname=DATABASE, autocommit=True, **admin) as conn:
        require_disposable(conn, cluster)
        conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    migrate(admin, DATABASE, cluster)
    with psycopg.connect(dbname=DATABASE, autocommit=True, **admin) as conn:
        require_disposable(conn, cluster)
        conn.execute(
            login_role_sql(
                conn,
                "auvexo_data_writer",
                passwords["data_writer"],
                "NOSUPERUSER NOCREATEDB NOCREATEROLE",
            )
        )
        conn.execute("GRANT auvexo_ingest TO auvexo_data_writer")


def migrate(admin: Mapping[str, Any], database: str, cluster: DisposableCluster) -> None:
    """Main-chain head; the DSN travels in the child environment, never on a command line."""
    dsn = URL.create(
        "postgresql+psycopg",
        username=str(admin["user"]),
        password=str(admin["password"]),
        host="127.0.0.1",
        port=cluster.port,
        database=database,
    ).render_as_string(hide_password=False)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=os.environ | {"AUVEXO_MIGRATION_DSN": dsn},
        capture_output=True,
        timeout=300,
        check=False,
    )
    if result.returncode:
        output = (result.stdout + result.stderr).decode(errors="replace")
        raise RuntimeError(
            "DISPOSABLE_CLUSTER_MIGRATION_FAILED\n" + output.replace(str(admin["password"]), "***")
        )


# --- Cluster lifecycle ---------------------------------------------------------------------


@dataclass(frozen=True)
class Descriptor:
    cluster_id: str
    root: Path
    port: int
    pid: int
    pid_created: float
    passwords: dict[str, str] = field(repr=False)

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def cluster(self) -> DisposableCluster:
        return DisposableCluster(self.port, self.cluster_id)

    def environment(self) -> dict[str, str]:
        values = {
            "TEST_PG_PORT": str(self.port),
            "TEST_PG_CLUSTER_ID": self.cluster_id,
            "TEST_PG_DATABASE": DATABASE,
        }
        for role in ROLES:
            values[f"TEST_PG_{role.upper()}_PASSWORD"] = self.passwords[role]
        return values


def _temp_root() -> Path:
    return Path(tempfile.gettempdir()).resolve()


def expected_root(cluster_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", cluster_id):
        raise ValueError("DISPOSABLE_CLUSTER_ID_INVALID")
    return _temp_root() / (PREFIX + cluster_id)


def _pg(name: str) -> str:
    return str(PG / (name + _EXE))


def _run(name: str, *args: str) -> None:
    # A file, not a pipe: on Windows the postmaster would inherit and hold a pipe open.
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(
            [_pg(name), *args],
            stdout=output,
            stderr=output,
            creationflags=NO_WINDOW,
            timeout=180,
            check=False,
        )
        if result.returncode:
            output.seek(0)
            raise RuntimeError(f"{name} failed: " + output.read().decode(errors="replace"))


def free_port() -> int:
    """A random port in the high test range that nothing listens on and that binds now."""
    for _ in range(50):
        port = PORTS[secrets.randbelow(len(PORTS))]
        if port in (OPERATIONAL_PORT, OI_RUNTIME_PORT) or port_bound(port):
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise RuntimeError("DISPOSABLE_CLUSTER_NO_FREE_PORT")


def _postmaster_pid(data: Path) -> int | None:
    path = data / "postmaster.pid"
    if not path.exists():
        return None
    first = path.read_text(encoding="ascii", errors="replace").splitlines()[:1]
    if not first or not first[0].isdecimal():
        raise RuntimeError("DISPOSABLE_CLUSTER_PID_FILE_INVALID")
    return int(first[0])


def _owned_process(descriptor: Descriptor) -> psutil.Process | None:
    """The recorded postmaster if it is still that exact process, else None."""
    try:
        process = psutil.Process(descriptor.pid)
        if process.create_time() != descriptor.pid_created:
            return None
        if Path(process.exe()).resolve() != Path(_pg("postgres")).resolve():
            return None
        return process
    except psutil.NoSuchProcess:
        return None


def _write_descriptor(descriptor: Descriptor) -> None:
    write_private(
        descriptor.root / "descriptor.json",
        json.dumps(
            {
                "version": 1,
                "cluster_id": descriptor.cluster_id,
                "root": str(descriptor.root),
                "port": descriptor.port,
                "pid": descriptor.pid,
                "pid_created": descriptor.pid_created,
                "passwords": descriptor.passwords,
            }
        ),
    )


def load(path: Path) -> Descriptor:
    """Read a descriptor and bind it to the one directory its UUID names."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        set(payload) != {"version", "cluster_id", "root", "port", "pid", "pid_created", "passwords"}
        or payload["version"] != 1
        or set(payload["passwords"]) != set(ROLES)
    ):
        raise ValueError("DISPOSABLE_CLUSTER_DESCRIPTOR_INVALID")
    root = expected_root(payload["cluster_id"])
    if Path(payload["root"]) != root or path.resolve() != root / "descriptor.json":
        raise ValueError("DISPOSABLE_CLUSTER_DESCRIPTOR_ROOT_MISMATCH")
    return Descriptor(
        cluster_id=payload["cluster_id"],
        root=root,
        port=payload["port"],
        pid=payload["pid"],
        pid_created=payload["pid_created"],
        passwords=payload["passwords"],
    )


def create() -> Descriptor:
    safe_window()
    cluster_id = uuid4().hex
    root = expected_root(cluster_id)
    if root.is_relative_to(ROOT.resolve()):
        raise RuntimeError("DISPOSABLE_CLUSTER_INSIDE_CHECKOUT")
    root.mkdir(mode=0o700)
    passwords = {role: secrets.token_hex(32) for role in ROLES}
    try:
        password_file = root / "initdb.pw"
        write_private(password_file, passwords["admin"])
        try:
            _run(
                "initdb",
                "-D",
                str(root / "data"),
                "-U",
                "auvexo_admin",
                "--pwfile",
                str(password_file),
                "--auth=scram-sha-256",
                "--encoding=UTF8",
                "--locale=C",
            )
        finally:
            password_file.unlink(missing_ok=True)
        port = free_port()
        with (root / "data/postgresql.conf").open("a", encoding="utf-8") as config:
            config.write(
                "\n# Disposable test cluster written by tools/disposable_pg.py\n"
                "listen_addresses = '127.0.0.1'\n"
                f"port = {port}\n"
                "max_connections = 100\n"
                "shared_buffers = '32MB'\n"
                "work_mem = '4MB'\n"
                "maintenance_work_mem = '32MB'\n"
                "fsync = off\n"
                "synchronous_commit = off\n"
                "full_page_writes = off\n"
                "timezone = 'UTC'\n"
                f"auvexo.disposable_cluster = '{cluster_id}'\n"
                f"cluster_name = '{DISPOSABLE_CLUSTER_NAME_PREFIX}{cluster_id}'\n"
            )
        data, log = str(root / "data"), str(root / "server.log")
        _run("pg_ctl", "-D", data, "-l", log, "-w", "-t", "60", "start")
        pid = _postmaster_pid(root / "data")
        if pid is None:
            raise RuntimeError("DISPOSABLE_CLUSTER_NOT_STARTED")
        descriptor = Descriptor(
            cluster_id, root, port, pid, psutil.Process(pid).create_time(), passwords
        )
        if _owned_process(descriptor) is None:
            raise RuntimeError("DISPOSABLE_CLUSTER_POSTMASTER_UNVERIFIED")
        _write_descriptor(descriptor)
        admin = dict(
            host="127.0.0.1",
            port=port,
            user="auvexo_admin",
            password=passwords["admin"],
            connect_timeout=3,
        )
        provision(admin, passwords, descriptor.cluster)
        return descriptor
    except BaseException:
        # Everything below `root` was created by this call; stop its postmaster, if any.
        if (root / "data/postmaster.pid").exists():
            _run("pg_ctl", "-D", str(root / "data"), "-m", "immediate", "-w", "stop")
        _remove(root)
        raise


def _stop(descriptor: Descriptor) -> None:
    pid = _postmaster_pid(descriptor.data)
    process = _owned_process(descriptor)
    if pid is None:
        if process is not None:
            raise RuntimeError("DISPOSABLE_CLUSTER_RUNNING_WITHOUT_PID_FILE")
        return
    if pid != descriptor.pid or process is None:
        raise RuntimeError("DISPOSABLE_CLUSTER_PID_MISMATCH; refusing to stop or delete")
    try:
        _run("pg_ctl", "-D", str(descriptor.data), "-m", "fast", "-w", "-t", "60", "stop")
    finally:
        # Only the verified postmaster of this cluster, if a failed stop left it running.
        if _owned_process(descriptor) is not None:
            process.terminate()
            process.wait(30)


def _remove(root: Path) -> None:
    """Delete one disposable root by exact path; refuse links and foreign locations."""
    if root.parent != _temp_root() or not root.name.startswith(PREFIX):
        raise RuntimeError("DISPOSABLE_CLUSTER_ROOT_REFUSED")
    if not root.exists():
        return
    if root.is_symlink() or root.is_junction() or not root.is_dir():
        raise RuntimeError("DISPOSABLE_CLUSTER_ROOT_REFUSED")
    # The last postmaster children can hold files for a moment after shutdown on Windows.
    for attempt in range(20):
        try:
            shutil.rmtree(root)
            return
        except OSError:
            if attempt == 19:
                raise
            time.sleep(0.5)


def destroy(path: Path) -> None:
    descriptor = load(path)
    config = (descriptor.data / "postgresql.conf").read_text(encoding="utf-8")
    if f"auvexo.disposable_cluster = '{descriptor.cluster_id}'\n" not in config:
        raise RuntimeError("DISPOSABLE_CLUSTER_MARKER_MISSING; refusing to delete")
    _stop(descriptor)
    _remove(descriptor.root)
    if descriptor.root.exists() or _owned_process(descriptor) is not None:
        raise RuntimeError("DISPOSABLE_CLUSTER_NOT_REMOVED")


def describe(path: Path) -> dict[str, object]:
    descriptor = load(path)
    return {
        "cluster_id": descriptor.cluster_id,
        "root": str(descriptor.root),
        "port": descriptor.port,
        "pid": descriptor.pid,
        "running": _owned_process(descriptor) is not None,
        "listening": port_bound(descriptor.port),
    }


@contextmanager
def disposable_cluster() -> Iterator[Descriptor]:
    descriptor = create()
    try:
        yield descriptor
    finally:
        destroy(descriptor.root / "descriptor.json")


def run(command: list[str]) -> int:
    if not command:
        raise ValueError("COMMAND_REQUIRED")
    with disposable_cluster() as descriptor:
        print(
            f"Disposable cluster {descriptor.cluster_id} on 127.0.0.1:{descriptor.port}",
            flush=True,
        )
        code = subprocess.call(command, cwd=ROOT, env=os.environ | descriptor.environment())
    print(f"Disposable cluster {descriptor.cluster_id} destroyed", flush=True)
    return code


def main(argv: list[str]) -> int:
    # Everything after `test` or `run` belongs to the child, including its options.
    if argv[:1] == ["test"]:
        return run([sys.executable, str(ROOT / "tools/run_tests.py"), *argv[1:]])
    if argv[:1] == ["run"]:
        return run(argv[2:] if argv[1:2] == ["--"] else argv[1:])
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("create")
    for name in ("describe", "destroy"):
        commands.add_parser(name).add_argument("descriptor", type=Path)
    commands.add_parser("run", help="run -- COMMAND [ARGS...]")
    commands.add_parser("test", help="test [PYTEST ARGS...]")
    args = parser.parse_args(argv)
    if args.action == "create":
        descriptor = create()
        print(json.dumps(describe(descriptor.root / "descriptor.json"), indent=2))
        print(f"Descriptor (owner-only, holds passwords): {descriptor.root / 'descriptor.json'}")
    elif args.action == "describe":
        print(json.dumps(describe(args.descriptor), indent=2))
    else:
        destroy(args.descriptor)
        print("Disposable cluster destroyed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
