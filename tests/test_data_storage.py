"""Real PostgreSQL privileges, concurrency, atomic failure and disk/manifest recovery."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import URL, create_engine, event, text
from sqlalchemy.exc import DBAPIError
from test_data_parser import NOW, row
from test_postgres import connection_args

from auvexo_alpha.infrastructure.data_collection import Collector
from auvexo_alpha.infrastructure.data_replay import replay
from auvexo_alpha.infrastructure.data_store import DataStore, file_hash, parquet_bytes, read_bars
from auvexo_alpha.infrastructure.public_http import PublicHTTP, Response
from auvexo_alpha.infrastructure.source_registry import identity, rights
from auvexo_alpha.infrastructure.spot_parser import parse_rest

pytestmark = pytest.mark.integration


@pytest.fixture
def store(tmp_path):
    name = "auvexo_test_" + uuid4().hex[:12]
    args = connection_args()
    args["dbname"] = "postgres"
    with psycopg.connect(**args, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        admin.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name)))
        admin.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO auvexo_data_writer,auvexo_app").format(
                sql.Identifier(name)
            )
        )
        url = URL.create(
            "postgresql+psycopg",
            username="auvexo_admin",
            password=args["password"],
            host="127.0.0.1",
            port=args["port"],
            database=name,
        )
        env = os.environ | {"AUVEXO_MIGRATION_DSN": url.render_as_string(hide_password=False)}
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            env=env,
            check=True,
            capture_output=True,
        )
        secret_path = Path(".local/data-secrets.json")
        password = (
            os.environ.get("TEST_PG_DATA_WRITER_PASSWORD")
            or json.loads(secret_path.read_text())["data_writer"]
        )
        engine = create_engine(
            url.set(username="auvexo_data_writer", password=password),
            hide_parameters=True,
            connect_args={"options": "-c statement_timeout=10000 -c lock_timeout=3000"},
        )
        result = DataStore(engine, tmp_path / "data", tmp_path)
        try:
            yield result
        finally:
            engine.dispose()
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def publish(store, key="sample", price="100", checkpoint=None):
    start = NOW - timedelta(hours=2)
    raw = json.dumps(
        [row(start, price=price), row(start + timedelta(hours=1), price=price)]
    ).encode()
    bars, report = parse_rest(raw, "BTCUSDT", "1h", start, NOW, NOW, "https://fixture.invalid")
    return store.publish(
        bars,
        report,
        identity("DS-02"),
        rights("DS-02"),
        key,
        "https://fixture.invalid",
        raw,
        NOW,
        "synthetic-test",
        checkpoint,
    )


def test_idempotent_correction_lineage_and_exact_replay(store):
    first = publish(store)
    assert publish(store) == first
    revised = publish(store, price="101")
    assert (
        revised.dataset_version != first.dataset_version
        and revised.supersedes == first.dataset_version
    )
    assert revised.changed_rows == 2 and len(store.manifests()) == 2
    store.verify(first)
    store.verify(revised)
    replay(store, first)
    replay(store, revised)
    path = store.path(first)
    assert file_hash(path) == first.parquet_hash
    assert parquet_bytes(read_bars(path)) == path.read_bytes()
    assert store.reconcile() == {
        "verified_manifests": 2,
        "unpublished_orphans": 0,
        "staging_files": 0,
    }


def test_simultaneous_ingestion_checkpoint_contention(store):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: publish(store, checkpoint="feed"), range(2)))
    assert results[0] == results[1] and len(store.manifests()) == 1
    assert store.checkpoint("feed").next_open == NOW


@pytest.mark.parametrize("stage", ["rename", "database"])
def test_crash_boundaries_never_publish_partial_manifest(store, monkeypatch, stage):
    if stage == "rename":
        original = os.replace

        def fail(src, dst):
            if str(dst).endswith(".parquet"):
                raise OSError("simulated disk failure")
            return original(src, dst)

        monkeypatch.setattr(os, "replace", fail)
        with pytest.raises(OSError):
            publish(store)
        monkeypatch.setattr(os, "replace", original)
    else:

        def fail(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith("INSERT INTO data_manifest"):
                raise RuntimeError("simulated database failure after rename")

        event.listen(store.engine, "before_cursor_execute", fail)
        with pytest.raises(RuntimeError):
            publish(store)
        event.remove(store.engine, "before_cursor_execute", fail)
    assert store.manifests() == [] and store.checkpoint("feed") is None
    assert not list(store.root.rglob("*.stage"))
    result = publish(store)
    store.verify(result)
    assert len(store.manifests()) == 1


def test_corrupt_missing_raw_and_parquet_fail_closed(store):
    manifest = publish(store)
    path = store.path(manifest)
    original = path.read_bytes()
    path.write_bytes(b"partial")
    with pytest.raises(ValueError):
        store.reconcile()
    with pytest.raises(ValueError):
        publish(store)
    path.write_bytes(original)
    raw = store.root / manifest.raw_relative_path
    raw.unlink()
    with pytest.raises(ValueError, match="RAW_SOURCE"):
        store.verify(manifest)


def test_ingestion_role_positive_and_all_privilege_negatives(store):
    publish(store)
    with store.engine.connect() as conn:
        assert conn.scalar(text("SELECT current_user")) == "auvexo_data_writer"
        assert conn.scalar(text("SELECT execution_enabled FROM foundation_policy")) is False
    for statement in [
        "UPDATE foundation_policy SET execution_enabled=true",
        "DELETE FROM data_manifest",
        "TRUNCATE data_manifest",
        "UPDATE data_manifest SET source_hash=source_hash",
        "DELETE FROM data_checkpoint",
        "CREATE TABLE unauthorized(id int)",
        "UPDATE alembic_version SET version_num='bad'",
        "SET ROLE auvexo_admin",
        "DROP TABLE foundation_policy",
        "ALTER TABLE data_manifest DISABLE TRIGGER ALL",
    ]:
        with pytest.raises(DBAPIError), store.engine.begin() as conn:
            conn.execute(text(statement))


def test_quota_refusal_preserves_accepted_data(store, monkeypatch):
    first = publish(store)
    store.quota = 1
    with pytest.raises(ValueError, match="QUOTA"):
        publish(store, key="other")
    store.verify(first)
    assert len(store.manifests()) == 1


def test_as_of_and_staging_cleanup(store):
    manifest = publish(store)
    with pytest.raises(ValueError, match="LOOKAHEAD"):
        store.read_as_of(manifest, NOW - timedelta(seconds=1))
    assert len(store.read_as_of(manifest, NOW)) == 2
    stage = store.root / "discard.stage"
    stage.write_bytes(b"incomplete")
    assert store.cleanup_staging() == 1
    store.verify(manifest)


def test_false_complete_report_refused(store):
    start = NOW - timedelta(hours=2)
    raw = json.dumps([row(start)]).encode()
    bars, report = parse_rest(raw, "BTCUSDT", "1h", start, NOW, NOW, "https://fixture.invalid")
    forged = report.model_copy(update={"status": "PASS", "findings": ()})
    with pytest.raises(ValueError, match="COVERAGE"):
        store.publish(
            bars,
            forged,
            identity("DS-02"),
            rights("DS-02"),
            "forged",
            "https://fixture.invalid",
            raw,
            NOW,
            "test",
        )


def test_verified_qualification_input_refuses_corrupt_artifact(store):
    manifest = publish(store)
    store.path(manifest).write_bytes(b"damaged accepted file")
    with pytest.raises(ValueError, match="MANIFEST_FILE_MISMATCH"):
        store.verified_manifests()


def test_default_off_and_persistent_rate_limit(store):
    from threading import Event

    http = PublicHTTP(Event(), lambda url, limit: Response(429, b"", 3600), lambda _: False)
    collector = Collector(store, http, "synthetic-test")
    with pytest.raises(ValueError, match="DISABLED"):
        collector.poll("BTCUSDT")
    collector.enabled = True
    with pytest.raises(ValueError, match="RATE_LIMIT"):
        collector.poll("BTCUSDT")
    assert store.events()[-1].state == "STALE" and store.events()[-1].blocked_until is not None
    with pytest.raises(ValueError, match="COOLDOWN"):
        collector.poll("ETHUSDT")
    assert http.requests == 1


def test_poll_restart_and_disconnect_backfill(store, monkeypatch):
    from datetime import UTC, datetime
    from threading import Event
    from urllib.parse import parse_qs, urlsplit

    from auvexo_alpha.infrastructure.spot_parser import EPOCH

    # A controlled fixture clock prevents a wall-minute boundary from making this flaky.
    clock = datetime.now(UTC).replace(second=20, microsecond=0)

    class FixtureClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock

    monkeypatch.setattr("auvexo_alpha.infrastructure.data_collection.datetime", FixtureClock)

    def transport(url, limit):
        params = parse_qs(urlsplit(url).query)
        start = EPOCH + timedelta(milliseconds=int(params["startTime"][0]))
        end = EPOCH + timedelta(milliseconds=int(params["endTime"][0]) + 1)
        rows = []
        while start < end:
            values = row(start)
            values[6] = str(int(values[0]) + 59999)
            rows.append(values)
            start += timedelta(minutes=1)
        return Response(200, json.dumps(rows).encode())

    collector = Collector(
        store, PublicHTTP(Event(), transport, lambda _: False), "synthetic-test", True
    )
    first = collector.poll("BTCUSDT")
    assert first.coverage.status == "PASS" and store.checkpoint("DS-02.BTCUSDT.1m")
    assert collector.poll("BTCUSDT") is None
    restarted = Collector(
        store, PublicHTTP(Event(), transport, lambda _: False), "synthetic-test", True
    )
    assert restarted.poll("BTCUSDT") is None
    clock += timedelta(minutes=5)
    recovered = restarted.poll("BTCUSDT")
    assert recovered.coverage.requested_start == first.coverage.requested_end
    assert recovered.coverage.observed_rows == 5 and recovered.coverage.status == "PASS"
    assert store.checkpoint("DS-02.BTCUSDT.1m").next_open == recovered.coverage.requested_end


def test_malformed_spec_retained_and_never_accepted(store):
    from threading import Event

    raw = b'{"symbols":[]}'
    collector = Collector(
        store,
        PublicHTTP(Event(), lambda url, limit: Response(200, raw), lambda _: False),
        "synthetic-test",
        True,
    )
    with pytest.raises(ValueError, match="SPEC_INPUT_REJECTED"):
        collector.spec("BTCUSDT")
    rejected = store.events()[-1]
    assert rejected.state == "BLOCKED"
    assert (
        store.root / "quarantine" / (rejected.quarantined_source_hash + ".raw")
    ).read_bytes() == raw
    assert not store.manifests()
    assert store.quarantine(raw) == rejected.quarantined_source_hash


def test_spec_rate_limit_blocks_other_requests(store):
    from threading import Event

    http = PublicHTTP(Event(), lambda url, limit: Response(429, b"", 3600), lambda _: False)
    collector = Collector(store, http, "synthetic-test", True)
    with pytest.raises(ValueError, match="RATE_LIMIT"):
        collector.spec("BTCUSDT")
    with pytest.raises(ValueError, match="COOLDOWN"):
        collector.poll("ETHUSDT")
    assert http.requests == 1 and store.events()[-1].blocked_until is not None
