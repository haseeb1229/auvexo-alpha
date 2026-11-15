"""Workspace-only PostgreSQL harness with random DEV/TEST credentials; no broker keys."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psutil
import psycopg
from psycopg import sql

# Explicit re-export for the workspace tools that create LOGIN roles beside local_db.
from auvexo_alpha.infrastructure.pg_login import login_role_sql as login_role_sql

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
PG = LOCAL / "toolchains/postgres/pgsql/bin"
DATA = LOCAL / "postgres-data"
SECRET = LOCAL / "dev-secrets.json"
PORT = 55432
# Native children get no console window on Windows and no creation flags elsewhere.
NO_WINDOW = 0
if sys.platform == "win32":
    NO_WINDOW = subprocess.CREATE_NO_WINDOW


def credentials() -> dict[str, str]:
    if not SECRET.exists():
        raise RuntimeError("Run local_db.py start first")
    values: dict[str, str] = json.loads(SECRET.read_text())
    return values


def write_private(path: Path, content: str) -> None:
    path.touch(exist_ok=False)
    if os.name == "nt":
        identity = subprocess.check_output(["whoami"], text=True).strip()
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{identity}:F"],
            check=True,
            capture_output=True,
        )
    else:
        path.chmod(0o600)
    path.write_text(content)


def safe_window() -> None:
    """Reserve the daily collector qualification window in Pakistan (UTC+05)."""
    local = datetime.now(UTC) + timedelta(hours=5)
    if (22, 45) <= (local.hour, local.minute) < (23, 20):
        raise RuntimeError("PHASE2_PRIORITY_WINDOW: no PAPER database/benchmark work")


def run_pg(name: str, *args: str, env: dict[str, str] | None = None) -> None:
    # A file avoids Windows descendants retaining a PIPE after pg_ctl exits.
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(
            [str(PG / f"{name}.exe"), *args],
            env=env,
            stdout=output,
            stderr=output,
            creationflags=NO_WINDOW,
            timeout=120,
        )
        if result.returncode:
            output.seek(0)
            raise RuntimeError(output.read().decode(errors="replace"))


def port_bound(port: int) -> bool:
    """Process-table fact only; no connection is opened to whatever owns the port.

    Windows reports some listening sockets (for example those of another session or
    integrity level) with status NONE rather than LISTEN; both count as occupied.
    """
    return any(
        connection.status in (psutil.CONN_LISTEN, psutil.CONN_NONE)
        and connection.laddr
        and connection.laddr.port == port
        for connection in psutil.net_connections(kind="tcp")
    )


def port_listener() -> bool:
    return port_bound(PORT)


def require_port_is_ours(create: bool) -> None:
    """Never take or share the fixed loopback port of another checkout's cluster.

    Every checkout uses the same port, so a second cluster started beside a pinned
    operational one would either fail or, if that one is down, occupy its endpoint and
    make its scheduled evidence runs fail. Creating a cluster is therefore explicit.
    """
    exists = (DATA / "PG_VERSION").exists()
    ours_running = (
        exists
        and subprocess.run(
            [str(PG / "pg_ctl.exe"), "-D", str(DATA), "status"], capture_output=True
        ).returncode
        == 0
    )
    if not ours_running and port_listener():
        raise RuntimeError("PORT_55432_OWNED_BY_ANOTHER_CLUSTER; refusing to start a second one")
    if not exists and not create:
        raise RuntimeError(
            "NO_CLUSTER_IN_THIS_CHECKOUT; pass --create only on a machine where no other "
            "Auvexo checkout uses port 55432"
        )


def start(create: bool = False) -> None:
    require_port_is_ours(create)
    LOCAL.mkdir(exist_ok=True)
    if not SECRET.exists():
        write_private(
            SECRET, json.dumps({key: secrets.token_hex(32) for key in ("admin", "app", "token")})
        )
    creds = credentials()
    if not (DATA / "PG_VERSION").exists():
        password_file = LOCAL / "init-password"
        write_private(password_file, creds["admin"])
        try:
            run_pg(
                "initdb",
                "-D",
                str(DATA),
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
        with (DATA / "postgresql.conf").open("a") as config:
            config.write(
                "\nlisten_addresses='127.0.0.1'\nport=55432\nshared_buffers='64MB'\nmax_connections=20\nlogging_collector=on\nlog_rotation_age='1d'\nlog_rotation_size='5MB'\nlog_filename='postgresql-%a.log'\nlog_truncate_on_rotation=on\n"
            )
    state = subprocess.run([str(PG / "pg_ctl.exe"), "-D", str(DATA), "status"], capture_output=True)
    if state.returncode != 0:
        run_pg("pg_ctl", "-D", str(DATA), "-l", str(LOCAL / "postgres-start.log"), "-w", "start")
    with psycopg.connect(
        host="127.0.0.1",
        port=PORT,
        user="auvexo_admin",
        password=creds["admin"],
        dbname="postgres",
        autocommit=True,
    ) as conn:
        if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname='auvexo_app'").fetchone():
            conn.execute(
                login_role_sql(
                    conn, "auvexo_app", creds["app"], "NOSUPERUSER NOCREATEDB NOCREATEROLE"
                )
            )
        for name in ("auvexo_dev", "auvexo_test"):
            if not conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (name,)).fetchone():
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            conn.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name))
            )
            conn.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO auvexo_app").format(sql.Identifier(name))
            )
    print("Local DEV/TEST cluster started on 127.0.0.1:55432; no trading capability")


def app_env(database: str = "auvexo_dev") -> dict[str, str]:
    creds = credentials()
    env = {k: v for k, v in os.environ.items() if not k.startswith("AUVEXO_")}
    env.update(
        AUVEXO_DB_PASSWORD=creds["app"], AUVEXO_API_TOKEN=creds["token"], AUVEXO_DB_NAME=database
    )
    return env


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop", "doctor", "serve", "migrate"])
    parser.add_argument(
        "--create",
        action="store_true",
        help="initialise a new cluster in this checkout; never beside an operational checkout",
    )
    args = parser.parse_args()
    if args.action == "start":
        start(create=args.create)
    elif args.action == "stop":
        run_pg("pg_ctl", "-D", str(DATA), "-m", "fast", "-w", "stop")
    elif args.action == "migrate":
        import sys

        creds = credentials()
        for name in ("auvexo_dev", "auvexo_test"):
            env = os.environ.copy()
            env["AUVEXO_MIGRATION_DSN"] = (
                f"postgresql+psycopg://auvexo_admin:{creds['admin']}@127.0.0.1:{PORT}/{name}"
            )
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"], env=env, check=True
            )
    else:
        import sys

        subprocess.run(
            [sys.executable, "-m", "auvexo_alpha.cli", args.action], env=app_env(), check=True
        )


if __name__ == "__main__":
    main()
