"""Snapshot real metadata and connected artifacts; restore into a fresh isolated database.

The backup lease requires the collector stopped (20801403) and holds the data writer
(20801402), study registration and trial recording (20801405), holdout opening (20801406)
and owner cooldown release (20801407) locks. It does not take the per-study research locks
(hashtextextended(study, 20801404)): trial recording takes a study lock and then 20801405,
so taking study locks while holding 20801405 could deadlock. Run it with no research worker
running. A read receipt, read digest or holdout completion written meanwhile carries no
artifact file; pg_dump takes one consistent snapshot, and a row landing between the
comparison snapshot and the dump fails the restore comparison instead of passing silently.
"""

import json
import os
import shutil
import time
from typing import Any
from uuid import uuid4

import psycopg
from local_db import LOCAL, PORT, credentials, run_pg
from psycopg import sql
from sqlalchemy import URL, create_engine, text

from auvexo_alpha.infrastructure.data_replay import replay
from auvexo_alpha.infrastructure.data_store import DataStore, file_hash
from auvexo_alpha.infrastructure.research_ledger import ResearchLedger

# Every table whose trigger refuses DELETE, including all of migration 0006's tables, is
# compared after restore and probed for its restored trigger.
IMMUTABLE = (
    "data_manifest",
    "data_event",
    "data_checkpoint",
    "data_source_review",
    "data_spec",
    "data_source_comparison",
    "data_source_conflict",
    "data_gap_review",
    "data_gap_evidence",
    "data_cooldown_release",
    "data_cooldown_probe",
    "data_cooldown_probe_result",
    "research_study",
    "research_trial",
    "research_event",
    "research_study_config",
    "research_selection",
    "research_holdout_completion",
    "research_read_receipt",
    "research_read_digest",
)
TABLES = ("alembic_version", "foundation_policy", "developer_event", *IMMUTABLE)


def main() -> None:
    started = time.monotonic()
    suffix = uuid4().hex[:12]
    target = "auvexo_restore_" + suffix
    directory = LOCAL / ("data-recovery-" + suffix)
    directory.mkdir()
    creds = credentials()
    args: dict[str, Any] = dict(
        host="127.0.0.1", port=PORT, user="auvexo_admin", password=creds["admin"]
    )
    url = URL.create(
        "postgresql+psycopg",
        username="auvexo_admin",
        password=creds["admin"],
        host="127.0.0.1",
        port=PORT,
        database="auvexo_dev",
    )
    engine = create_engine(url, hide_parameters=True)
    source = DataStore(engine, LOCAL / "market", LOCAL)

    def snapshot(database: str) -> list[list[tuple[Any, ...]]]:
        # Whole-row order: several tables have composite keys, so the first column ties.
        with psycopg.connect(dbname=database, **args) as conn:
            return [
                conn.execute(
                    sql.SQL("SELECT t.* FROM {} AS t ORDER BY t::text").format(
                        sql.Identifier(table)
                    )
                ).fetchall()
                for table in TABLES
            ]

    with psycopg.connect(dbname="postgres", autocommit=True, **args) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
        admin.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(target))
        )
        with engine.connect() as lease:
            if not lease.scalar(text("SELECT pg_try_advisory_lock(20801403)")):
                raise RuntimeError("Stop collector before backup")
            lease.execute(text("SELECT pg_advisory_lock(20801402)"))
            lease.execute(text("SELECT pg_advisory_lock(20801405)"))
            lease.execute(text("SELECT pg_advisory_lock(20801406)"))
            lease.execute(text("SELECT pg_advisory_lock(20801407)"))
            try:
                source.reconcile()
                expected = snapshot("auvexo_dev")
                manifests = source.manifests()
                research_root = LOCAL / "research"
                research = ResearchLedger(engine, research_root, LOCAL)
                research_verified = research.verify()
                shutil.copytree(research_root, directory / "research")
                rejected = {
                    e.quarantined_source_hash for e in source.events() if e.quarantined_source_hash
                }
                for manifest in manifests:
                    for relative in (manifest.relative_path, manifest.raw_relative_path):
                        destination = directory / "market" / relative
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source.root / relative, destination)
                for digest in rejected:
                    original = source.root / "quarantine" / (digest + ".raw")
                    assert file_hash(original) == digest
                    destination = directory / "market/quarantine" / original.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(original, destination)
                pg_env = os.environ | dict(
                    PGHOST="127.0.0.1",
                    PGPORT=str(PORT),
                    PGUSER="auvexo_admin",
                    PGPASSWORD=creds["admin"],
                )
                dump = directory / "metadata.dump"
                run_pg("pg_dump", "-Fc", "-f", str(dump), "auvexo_dev", env=pg_env)
            finally:
                lease.execute(text("SELECT pg_advisory_unlock(20801407)"))
                lease.execute(text("SELECT pg_advisory_unlock(20801406)"))
                lease.execute(text("SELECT pg_advisory_unlock(20801405)"))
                lease.execute(text("SELECT pg_advisory_unlock(20801402)"))
                lease.execute(text("SELECT pg_advisory_unlock(20801403)"))
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
        restored_engine = create_engine(url.set(database=target), hide_parameters=True)
        restored = DataStore(restored_engine, directory / "market", LOCAL)
        try:
            result = restored.reconcile()
            assert result["verified_manifests"] == len(manifests)
            for manifest in manifests:
                replay(restored, manifest)
            assert ResearchLedger(restored_engine, directory / "research", LOCAL).verify() == (
                research_verified
            )
            for digest in rejected:
                assert file_hash(restored.root / "quarantine" / (digest + ".raw")) == digest
            for table in IMMUTABLE:
                with psycopg.connect(dbname=target, **args) as conn:
                    try:
                        conn.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(table)))
                    except psycopg.errors.RaiseException:
                        conn.rollback()
                    else:
                        raise AssertionError("Missing restored immutable trigger")
        finally:
            restored_engine.dispose()
        admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(target)))
    engine.dispose()
    report = dict(
        status="PASS",
        schema=expected[TABLES.index("alembic_version")][0][0],
        tables_compared=len(TABLES),
        manifests=len(manifests),
        parquet_bytes=sum(m.parquet_bytes for m in manifests),
        raw_bytes=sum(m.raw_bytes for m in manifests),
        dump_bytes=dump.stat().st_size,
        dump_sha256=file_hash(dump),
        restored_triggers=True,
        exact_source_to_parquet_replay=True,
        quarantined_payloads_verified=len(rejected),
        research_artifacts=research_verified,
        elapsed_seconds=round(time.monotonic() - started, 3),
        retained_backup=directory.name,
        limitation="Same-disk DEV backup; not encrypted disaster recovery",
    )
    (LOCAL / "data-recovery-evidence.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
