"""Separate OI PostgreSQL for CI without changing inherited workflow or using 55432."""

import os
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import psycopg
from psycopg import sql

IMAGE = "postgres:17.11@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3"
OPERATIONAL_PORT = 55432
# The fixed production OI runtime port on the owner's machine. Only the disposable CI
# container below may listen there; a local test must never reach the real runtime.
OI_RUNTIME_PORT = 55433


def _test_port_allowed(port: int) -> bool:
    return (
        1024 <= port <= 65535
        and port != OPERATIONAL_PORT
        and (port != OI_RUNTIME_PORT or os.environ.get("GITHUB_ACTIONS") == "true")
    )


@contextmanager
def oi_test_server() -> Iterator[int]:
    override = os.environ.get("OI_TEST_PG_PORT")
    if override is not None:
        if not override.isascii() or not override.isdecimal() or len(override) > 5:
            raise ValueError("OI_TEST_PORT_INVALID")
        port = int(override)
        if not _test_port_allowed(port):
            raise ValueError("OI_TEST_PORT_INVALID")
        yield port
        return
    port = int(os.environ.get("TEST_PG_PORT", "55432"))
    if port != OPERATIONAL_PORT:
        if not _test_port_allowed(port):
            raise ValueError("OI_TEST_PORT_INVALID")
        yield port
        return
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.name == "nt":
        raise RuntimeError("ISOLATED_PG_UNAVAILABLE: explicit separate TEST_PG_PORT required")
    port = OI_RUNTIME_PORT
    name = "auvexo-oi-ci-" + uuid4().hex
    passwords = {
        "admin": "ci-synthetic-oi-admin-only-20261027",
        "app": "ci-synthetic-oi-app-only-20261027",
        "data_writer": "ci-synthetic-oi-data-only-20261027",
    }
    keys = {"TEST_PG_PORT": str(port)} | {
        "TEST_PG_" + role.upper() + "_PASSWORD": value for role, value in passwords.items()
    }
    previous = {key: os.environ.get(key) for key in keys}
    started = False
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                name,
                "--network",
                "host",
                "--env",
                "POSTGRES_USER=auvexo_admin",
                "--env",
                "POSTGRES_PASSWORD=" + passwords["admin"],
                "--env",
                "POSTGRES_INITDB_ARGS=--auth-host=scram-sha-256",
                IMAGE,
                "postgres",
                "-c",
                "listen_addresses=127.0.0.1",
                "-c",
                "port=55433",
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
        started = True
        deadline = time.monotonic() + 30
        while True:
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    name,
                    "pg_isready",
                    "-h",
                    "127.0.0.1",
                    "-p",
                    str(port),
                    "-U",
                    "auvexo_admin",
                ],
                capture_output=True,
                timeout=3,
            )
            if result.returncode == 0:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("OI_ISOLATED_CI_PG_NOT_READY")
            time.sleep(0.2)
        with psycopg.connect(
            host="127.0.0.1",
            port=port,
            dbname="postgres",
            user="auvexo_admin",
            password=passwords["admin"],
            autocommit=True,
            connect_timeout=3,
        ) as conn:
            for role in ("app", "data_writer"):
                conn.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE"
                    ).format(sql.Identifier("auvexo_" + role), sql.Literal(passwords[role]))
                )
        os.environ.update(keys)
        yield port
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if started:
            subprocess.run(
                ["docker", "rm", "--force", name], check=True, capture_output=True, timeout=20
            )
