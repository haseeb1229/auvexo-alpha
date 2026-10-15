"""Workspace-only PostgreSQL harness with random DEV/TEST credentials; no broker keys."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import tempfile
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
PG = LOCAL / "toolchains/postgres/pgsql/bin"
DATA = LOCAL / "postgres-data"
SECRET = LOCAL / "dev-secrets.json"
PORT = 55432


def credentials() -> dict[str, str]:
    if not SECRET.exists():
        raise RuntimeError("Run local_db.py start first")
    return json.loads(SECRET.read_text())


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


def run_pg(name: str, *args: str, env: dict[str, str] | None = None) -> None:
    # A file avoids Windows descendants retaining a PIPE after pg_ctl exits.
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(
            [str(PG / f"{name}.exe"), *args],
            env=env,
            stdout=output,
            stderr=output,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            timeout=120,
        )
        if result.returncode:
            output.seek(0)
            raise RuntimeError(output.read().decode(errors="replace"))


def start() -> None:
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
                sql.SQL(
                    "CREATE ROLE auvexo_app LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE"
                ).format(sql.Literal(creds["app"]))
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
    args = parser.parse_args()
    if args.action == "start":
        start()
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
