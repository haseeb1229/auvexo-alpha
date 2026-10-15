"""Fresh committed-source clone/venv and isolated PostgreSQL migration on this Windows host."""

import hashlib
import json
import os
import subprocess
import time
from uuid import uuid4

import psycopg
from local_db import LOCAL, PORT, ROOT, credentials
from psycopg import sql


def main() -> None:
    suffix = uuid4().hex[:12]
    target = LOCAL / f"clean-clone-{suffix}"
    database = f"auvexo_test_{suffix}"
    uv = LOCAL / "toolchains/uv-wheel/uv-0.13.1.data/scripts/uv.exe"
    env = {k: v for k, v in os.environ.items() if not k.startswith("AUVEXO_")}
    env["UV_PYTHON_INSTALL_DIR"] = str(LOCAL / "python")
    env["UV_CACHE_DIR"] = str(LOCAL / f"clean-cache-{suffix}")
    env["UV_LINK_MODE"] = "copy"
    creds = credentials()
    env.update(
        TEST_PG_ADMIN_PASSWORD=creds["admin"],
        TEST_PG_APP_PASSWORD=creds["app"],
        TEST_PG_DATABASE=database,
        TEST_PG_PORT=str(PORT),
    )
    git = ["git", "-c", f"safe.directory={ROOT.as_posix()}"]
    commit = subprocess.check_output([*git, "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    started = time.monotonic()
    subprocess.run(
        [
            *git,
            "clone",
            "--no-local",
            "--no-hardlinks",
            "--branch",
            "phase-1/engineering-foundation",
            str(ROOT),
            str(target),
        ],
        check=True,
    )
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=target, text=True).strip()
    assert actual == commit
    assert not (target / ".venv").exists()
    subprocess.run([str(uv), "sync", "--locked"], cwd=target, env=env, check=True)
    install_seconds = time.monotonic() - started
    args = dict(host="127.0.0.1", port=PORT, user="auvexo_admin", password=creds["admin"])
    with psycopg.connect(dbname="postgres", autocommit=True, **args) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        admin.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database))
        )
        admin.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO auvexo_app").format(sql.Identifier(database))
        )
        migrate_env = env | {
            "AUVEXO_MIGRATION_DSN": f"postgresql+psycopg://auvexo_admin:{creds['admin']}@127.0.0.1:{PORT}/{database}"
        }
        python = target / ".venv/Scripts/python.exe"
        subprocess.run(
            [str(python), "-m", "alembic", "upgrade", "head"],
            cwd=target,
            env=migrate_env,
            check=True,
        )
        commands = [
            [str(python), "-m", "ruff", "format", "--check", "src", "tests", "tools", "migrations"],
            [str(python), "-m", "ruff", "check", "src", "tests", "tools", "migrations"],
            [str(python), "-m", "mypy"],
            [str(python), "-m", "pytest", "-q"],
            [str(python), "tools/secret_scan.py"],
            ["node", "tools/check-docs.mjs"],
            ["git", "diff", "--exit-code"],
        ]
        for command in commands:
            subprocess.run(command, cwd=target, env=env, check=True)
        assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=target)
        admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))
    report = dict(
        status="PASS",
        source_commit=commit,
        clone_path=target.name,
        clone_method="git clone --no-local --no-hardlinks; committed source only",
        fresh_venv=True,
        fresh_download_cache=True,
        shared_verified_python=True,
        isolated_migration=True,
        clean_tree=True,
        clone_and_install_seconds=round(install_seconds, 3),
        total_seconds=round(time.monotonic() - started, 3),
        lock_sha256=hashlib.sha256((target / "uv.lock").read_bytes()).hexdigest(),
    )
    (LOCAL / "clean-clone-evidence.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
