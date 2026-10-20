"""Isolated synthetic observation restore/replay; never credits a calendar date."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import UTC, datetime, timedelta
from threading import Event
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from sqlalchemy import text

from auvexo_alpha.domain.observation import (
    ObservationConfig,
    ObservationResources,
    ObservationRunEvidence,
    observation_spec,
    observation_window,
)
from auvexo_alpha.infrastructure.data_store import DataStore
from auvexo_alpha.infrastructure.observation_feed import ObservationFeed
from auvexo_alpha.infrastructure.observation_store import ObservationStore
from auvexo_alpha.infrastructure.public_http import PublicHTTP, Response
from auvexo_alpha.infrastructure.source_registry import identity, rights
from tools.local_db import run_pg, write_private
from tools.paper_local import admin_args, snapshot
from tools.paper_observation_local import LOCAL, engine_for, isolated_observation_database


def clone_verified_archives(source: DataStore, target: DataStore) -> int:
    """Copy only manifest-bound immutable artifacts, then rehash the target archive."""
    manifests = source.verified_manifests()
    for manifest in manifests:
        for relative in (manifest.relative_path, manifest.raw_relative_path):
            original, destination = source.root / relative, target.root / relative
            if (
                not original.resolve().is_relative_to(source.root)
                or not destination.resolve().is_relative_to(target.root)
                or original.is_symlink()
                or destination.exists()
            ):
                raise ValueError("OBSERVATION_RESTORE_ARCHIVE_SCOPE_OR_COLLISION")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, destination)
        target.verify(manifest)
    return len(manifests)


def main() -> None:
    directory = LOCAL / ("observation-recovery-" + uuid4().hex[:12])
    directory.mkdir(parents=True)
    dump = directory / "observation.dump"
    with isolated_observation_database() as source, isolated_observation_database() as target:
        source_engines = [
            engine_for(source, group)
            for group in ("auvexo_paper", "auvexo_paper_owner", "auvexo_paper_truth")
        ]
        target_engines = []
        try:
            source_archive = DataStore(source_engines[2], directory / "source-market", directory)
            store = ObservationStore(*source_engines, source_store=source_archive)
            now = datetime.now(UTC)
            config = ObservationConfig(
                campaign_id="synthetic.recovery.noncounting.v1",
                git_revision="a" * 40,
                rights=rights("DS-02"),
                source=identity("DS-02"),
                specs=tuple(
                    observation_spec(symbol, observed_at=now) for symbol in ("BTCUSDT", "ETHUSDT")
                ),
            )
            config_hash = store.prepare(config, now=now)
            run_id = store.begin(config_hash, kind="RESTORE", now=datetime.now(UTC))
            run = store.run(run_id)
            # Retained parser/source objects are synthetic and intentionally outside
            # this run's real server window. They can never qualify a genuine date.
            observed = observation_window((now - timedelta(days=1)).date())[0] + timedelta(
                seconds=3
            )

            def transport(url: str, limit: int) -> Response:
                epoch = datetime(1970, 1, 1, tzinfo=UTC)
                if urlsplit(url).path.endswith("/time"):
                    return Response(
                        200,
                        json.dumps(
                            {"serverTime": int((observed - epoch).total_seconds() * 1000)}
                        ).encode(),
                    )
                query = parse_qs(urlsplit(url).query)
                return Response(
                    200,
                    json.dumps(
                        [
                            [
                                int(query["startTime"][0]),
                                "100",
                                "100",
                                "100",
                                "100",
                                "1",
                                int(query["endTime"][0]),
                                "100",
                                1,
                                "1",
                                "1",
                                "0",
                            ]
                        ]
                    ).encode(),
                )

            feed = ObservationFeed(
                source_archive,
                PublicHTTP(Event(), transport=transport, wait=lambda _: False),
                config.git_revision,
                config.campaign_id,
                clock=lambda: observed,
            )
            start, end = observation_window(observed.date())
            fact = feed.poll("BTCUSDT", window_start=start, window_end=end)
            assert fact is not None
            store.append_feed(run_id, fact, now=datetime.now(UTC))
            store.paper.acquire_writer(config.account_ref, now=datetime.now(UTC))
            assert store.paper.reconcile(config.account_ref, now=datetime.now(UTC))
            ended = datetime.now(UTC)
            evidence = ObservationRunEvidence(
                run_id=run_id,
                campaign_id=config.campaign_id,
                local_day=run["local_date"].isoformat(),
                kind="NON_COUNTING",
                scheduled_at=observation_window(run["local_date"])[0],
                started_at=run["started_at"],
                ended_at=ended,
                config_hash=config_hash,
                facts=store.feeds(run_id),
                resource_snapshots=(
                    ObservationResources(
                        observed_at=ended,
                        available_ram_bytes=4_000_000_000,
                        cpu_percent="0",
                        cpu_high_for_seconds=0,
                    ),
                ),
                **store.snapshot(run_id),
            )
            receipt = store.close(run_id, evidence, now=datetime.now(UTC))
            witness = store.verify(run_id, evidence, now=datetime.now(UTC))
            expected = snapshot(source)
            arguments = admin_args()
            environment = os.environ | {
                "PGHOST": str(arguments["host"]),
                "PGPORT": str(arguments["port"]),
                "PGUSER": str(arguments["user"]),
                "PGPASSWORD": str(arguments["password"]),
                "PGOPTIONS": "-c timezone=UTC",
            }
            run_pg("pg_dump", "-Fc", "-f", str(dump), source, env=environment)
            # Both databases were generated and tracked by the bounded context manager.
            # Admin-only trigger suppression preserves original server origin and times.
            run_pg(
                "pg_restore",
                "--clean",
                "--if-exists",
                "--disable-triggers",
                "--exit-on-error",
                "--single-transaction",
                "-d",
                target,
                str(dump),
                env=environment,
            )
            assert snapshot(target) == expected
            target_engines = [
                engine_for(target, group)
                for group in ("auvexo_paper", "auvexo_paper_owner", "auvexo_paper_truth")
            ]
            target_archive = DataStore(target_engines[2], directory / "target-market", directory)
            archives = clone_verified_archives(source_archive, target_archive)
            assert archives == 1
            restored = ObservationStore(*target_engines, source_store=target_archive)
            assert restored.verify(run_id, evidence, now=datetime.now(UTC)) == witness
            assert restored.config(config_hash) == config
            assert restored.run(run_id)["database_name"] == source
            assert restored.qualified_dates(config_hash, now=datetime.now(UTC)).qualified_count == 0
            with target_engines[0].connect() as connection:
                assert (
                    connection.scalar(text("SELECT count(*) FROM paper_observation_activation"))
                    == 0
                )
                assert (
                    connection.scalar(text("SELECT count(*) FROM paper_observation_receipt")) == 1
                )
            report = {
                "status": "PASS",
                "evidence_use": "SYNTHETIC_ENGINEERING_ONLY",
                "source_archives": archives,
                "source_archive_claim": "SYNTHETIC_DS02_RAW_PARQUET_EXACT_REPLAY",
                "exact_rows_and_triggers": expected,
                "replayed_receipt_hash": receipt.content_hash(),
                "restored_original_origin": True,
                "restored_qualified_dates": 0,
                "activation_count": 0,
                "task_registered": False,
                "dump_sha256": hashlib.sha256(dump.read_bytes()).hexdigest(),
            }
            write_private(directory / "receipt.json", json.dumps(report, indent=2))
            print("PASS: synthetic NON_COUNTING observation restore/replay; dates=0")
        finally:
            for engine in (*source_engines, *target_engines):
                engine.dispose()


if __name__ == "__main__":
    main()
