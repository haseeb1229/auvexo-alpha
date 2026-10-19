"""Create an isolated TEST database, migrate, seed, back up and restore without replacing DEV."""

import hashlib
import json
import os
import subprocess
import sys
import time
from uuid import uuid4

import psycopg
from local_db import LOCAL, PORT, ROOT, credentials, run_pg
from psycopg import sql
from pydantic import SecretStr

from auvexo_alpha.config import Settings
from auvexo_alpha.infrastructure.database import SCHEMA_REVISION, DatabaseProbe, make_engine


def main() -> None:
    creds = credentials()
    suffix = uuid4().hex[:12]
    source, target = f"auvexo_test_{suffix}", f"auvexo_restore_{suffix}"
    args = dict(host="127.0.0.1", port=PORT, user="auvexo_admin", password=creds["admin"])
    dump = LOCAL / f"recovery-{suffix}.dump"
    start = time.monotonic()
    with psycopg.connect(dbname="postgres", autocommit=True, **args) as admin:
        for name in (source, target):
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            admin.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name))
            )
            admin.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO auvexo_app").format(sql.Identifier(name))
            )
        env = os.environ.copy()
        env["AUVEXO_MIGRATION_DSN"] = (
            f"postgresql+psycopg://auvexo_admin:{creds['admin']}@127.0.0.1:{PORT}/{source}"
        )
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"], env=env, cwd=ROOT, check=True
        )
        # Reapplying the same revision must be harmless.
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"], env=env, cwd=ROOT, check=True
        )
        event = uuid4()
        with psycopg.connect(dbname=source, **args) as conn:
            conn.execute(
                "INSERT INTO developer_event VALUES (%s,'1.0','TEST_FIXTURE',now(),%s)",
                (event, hashlib.sha256(b"synthetic-recovery-test").hexdigest()),
            )

        def snapshot(name: str) -> list[list[tuple[object, ...]]]:
            with psycopg.connect(dbname=name, **args) as conn:
                return [
                    conn.execute(
                        sql.SQL("SELECT * FROM {} ORDER BY 1").format(sql.Identifier(t))
                    ).fetchall()
                    for t in ("alembic_version", "foundation_policy", "developer_event")
                ]

        expected = snapshot(source)
        downgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "base"],
            env=env,
            cwd=ROOT,
            capture_output=True,
        )
        assert downgrade.returncode != 0 and b"destructive downgrade disabled" in downgrade.stderr
        assert snapshot(source) == expected
        pg_env = os.environ.copy()
        pg_env.update(
            PGHOST="127.0.0.1", PGPORT=str(PORT), PGUSER="auvexo_admin", PGPASSWORD=creds["admin"]
        )
        run_pg("pg_dump", "-Fc", "-f", str(dump), source, env=pg_env)
        run_pg(
            "pg_restore",
            "--exit-on-error",
            "--single-transaction",
            "-d",
            target,
            str(dump),
            env=pg_env,
        )
        assert snapshot(target) == expected
        settings = Settings(
            database_name=target,
            database_port=PORT,
            database_password=SecretStr(creds["app"]),
            api_token=SecretStr(creds["token"]),
        )
        engine = make_engine(settings)
        try:
            assert DatabaseProbe(engine).ready()
            with psycopg.connect(dbname=target, **args) as conn:
                conn.execute("UPDATE alembic_version SET version_num='unexpected_revision'")
            assert not DatabaseProbe(engine).ready()
            with psycopg.connect(dbname=target, **args) as conn:
                conn.execute("UPDATE alembic_version SET version_num=%s", (SCHEMA_REVISION,))
            assert DatabaseProbe(engine).ready()
        finally:
            engine.dispose()
        with psycopg.connect(dbname=target, **args) as conn:
            try:
                conn.execute("DELETE FROM developer_event")
            except psycopg.errors.RaiseException:
                conn.rollback()
            else:
                raise AssertionError("Restored append-only trigger absent")
        report = dict(
            status="PASS",
            source=source,
            isolated_restore=target,
            tables_compared=3,
            synthetic_events=1,
            migration_idempotent=True,
            destructive_downgrade_refused=True,
            restored_trigger_enforced=True,
            schema_drift_not_ready=True,
            elapsed_seconds=round(time.monotonic() - start, 3),
            backup_bytes=dump.stat().st_size,
            backup_sha256=hashlib.sha256(dump.read_bytes()).hexdigest(),
        )
        # Only the two freshly generated names are removed; a failed run preserves evidence.
        for name in (source, target):
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
        dump.unlink()
    (LOCAL / "recovery-evidence.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
