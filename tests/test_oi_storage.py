"""OI immutable generic-table storage on a separate synthetic PostgreSQL endpoint."""

import hashlib
import json
import os
import subprocess
import sys
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from oi_pg_helpers import oi_test_server
from psycopg import sql
from sqlalchemy import URL, create_engine, event, text
from sqlalchemy.exc import DBAPIError
from test_postgres import connection_args

from auvexo_alpha.domain.open_interest import accepted_oi_rights
from auvexo_alpha.domain.research import DataUseClass
from auvexo_alpha.infrastructure.oi_http import OIBudgetState
from auvexo_alpha.infrastructure.oi_parser import parse_oi
from auvexo_alpha.infrastructure.oi_store import OIStore

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 30, 10, tzinfo=UTC)


@pytest.fixture(scope="module")
def oi_server():
    with oi_test_server() as port:
        assert port != 55432
        yield port


@pytest.fixture
def store(tmp_path, oi_server):
    args = connection_args()
    args.update(port=oi_server, dbname="postgres")
    name = "auvexo_test_oi" + uuid4().hex[:12]
    with psycopg.connect(**args, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        admin.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name)))
        admin.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO auvexo_data_writer").format(
                sql.Identifier(name)
            )
        )
        url = URL.create(
            "postgresql+psycopg",
            username="auvexo_admin",
            password=args["password"],
            host="127.0.0.1",
            port=oi_server,
            database=name,
        )
        engine = None
        try:
            environment = os.environ | {
                "AUVEXO_MIGRATION_DSN": url.render_as_string(hide_password=False),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            migrated = subprocess.run(
                [sys.executable, "-B", "-m", "alembic", "upgrade", "head"],
                env=environment,
                check=False,
                capture_output=True,
            )
            if migrated.returncode:
                raise RuntimeError(
                    migrated.stderr.decode("utf8", errors="replace").replace(
                        str(args["password"]), "[REDACTED]"
                    )
                )
            admin.execute("GRANT auvexo_ingest TO auvexo_data_writer")
            password = os.environ.get("TEST_PG_DATA_WRITER_PASSWORD")
            if not password:
                password = json.loads(Path(".local/data-secrets.json").read_text())["data_writer"]
            engine = create_engine(
                url.set(username="auvexo_data_writer", password=password),
                hide_parameters=True,
                connect_args={"options": "-c statement_timeout=10000 -c lock_timeout=3000"},
            )
            yield OIStore(engine, tmp_path / "store", tmp_path)
        finally:
            if engine is not None:
                engine.dispose()
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def observation(
    slot=NOW, symbol="BTCUSDT", value="100", provider_at=None, review_receipt_hash=None
):
    provider_at = provider_at or slot + timedelta(seconds=1)
    raw = json.dumps(
        {"openInterest": value, "symbol": symbol, "time": int(provider_at.timestamp() * 1000)},
        separators=(",", ":"),
    ).encode("ascii")
    parsed = parse_oi(
        raw,
        symbol=symbol,
        slot_at=slot,
        request_sent_at=slot + timedelta(seconds=1),
        first_seen_at=slot + timedelta(seconds=3),
        received_at=slot + timedelta(seconds=3),
        processed_at=slot + timedelta(seconds=4),
        code_revision="synthetic-fixture",
        code_hash="a" * 64,
        review_receipt_hash=review_receipt_hash,
    )
    return parsed, raw


def publish(store, slot=NOW, symbol="BTCUSDT", value="100", **kwargs):
    parsed, raw = observation(slot, symbol, value, **kwargs)
    return store.publish(parsed, raw, now=parsed.available_at)


def test_oi_immutable_idempotent_raw_normalized_and_checkpoint(store):
    first = publish(store)
    assert publish(store) == first
    assert store.manifests() == [first]
    store.verify(first)
    assert store.checkpoint("BTCUSDT") == first
    assert store.read_as_of(first, first.created_at) == first.observation
    assert (store.root / first.raw_relative_path).read_bytes() == observation()[1]
    assert hashlib.sha256(
        (store.root / first.normalized_relative_path).read_bytes()
    ).hexdigest() == (first.normalized_hash)
    assert store.reconcile() == {
        "verified_manifests": 1,
        "unpublished_orphans": 0,
        "staging_files": 0,
    }


def test_oi_concurrent_duplicate_single_publication(store):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: publish(store), range(2)))
    assert results[0] == results[1]
    assert len(store.manifests()) == 1


def test_oi_conflicting_identity_quarantines_without_rewriting_original(store):
    first = publish(store)
    original = first.canonical_bytes()
    conflict = publish(store, value="101")
    assert conflict.observation.quality == "QUARANTINED"
    assert conflict.observation.reason == "IDENTITY_CONFLICT"
    assert conflict.classification == DataUseClass.BLOCKED
    assert conflict.supersedes == first.dataset_version
    assert conflict.conflict_raw_hash == first.observation.raw_hash
    assert first.canonical_bytes() == original
    assert len(store.manifests()) == 2
    store.verify(first)
    store.verify(conflict)
    with pytest.raises(ValueError, match="CONFLICTED"):
        store.read_as_of(first, conflict.created_at)
    assert store.checkpoint("BTCUSDT") == first


def test_oi_equal_value_new_fact_advances_and_out_of_order_quarantines(store):
    first = publish(store)
    second = publish(store, slot=NOW + timedelta(hours=1))
    assert second.observation.value == first.observation.value
    assert second.observation.identity_key != first.observation.identity_key
    assert second.observation.quality == "VALID"
    old = publish(store, slot=NOW - timedelta(hours=1))
    assert old.observation.quality == "QUARANTINED"
    assert store.checkpoint("BTCUSDT") == second
    with pytest.raises(ValueError, match="ADMISSION_BLOCKED"):
        store.read_as_of(old, second.created_at)


def test_oi_repeated_receipt_keeps_earliest_availability_and_cannot_change_slot(store):
    first = publish(store)
    parsed, raw = observation()
    repeated = parsed.model_copy(
        update={
            "received_at": parsed.received_at + timedelta(seconds=1),
            "processed_at": parsed.processed_at + timedelta(seconds=1),
            "available_at": parsed.available_at + timedelta(seconds=1),
        }
    )
    assert store.publish(repeated, raw, now=repeated.available_at) == first
    recycled = parsed.model_copy(
        update={
            "slot_at": parsed.slot_at + timedelta(hours=1),
            "request_sent_at": parsed.request_sent_at + timedelta(hours=1),
            "first_seen_at": parsed.first_seen_at + timedelta(hours=1),
            "received_at": parsed.received_at + timedelta(hours=1),
            "processed_at": parsed.processed_at + timedelta(hours=1),
            "available_at": parsed.available_at + timedelta(hours=1),
            "quality": "STALE",
            "reason": "RECYCLED",
        }
    )
    with pytest.raises(ValueError, match="RECYCLED_IDENTITY"):
        store.publish(recycled, raw, now=recycled.available_at)
    assert len(store.manifests()) == 1


@pytest.mark.parametrize("artifact", ["raw", "normalized", "missing_raw"])
def test_oi_corruption_and_missing_artifact_fail_closed(store, artifact):
    manifest = publish(store)
    path = store.root / (
        manifest.normalized_relative_path
        if artifact == "normalized"
        else manifest.raw_relative_path
    )
    if artifact == "missing_raw":
        path.unlink()
    else:
        path.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="MISMATCH"):
        store.verify(manifest)
    with pytest.raises(ValueError, match="MISMATCH"):
        publish(store)


@pytest.mark.parametrize("boundary", ["artifact", "database"])
def test_oi_staging_crash_and_orphan_recovery_never_admits_partial_manifest(
    store, monkeypatch, boundary
):
    if boundary == "artifact":
        original = os.link

        def fail(source, destination):
            if str(destination).endswith(".json"):
                raise OSError("synthetic crash before immutable publication")
            return original(source, destination)

        monkeypatch.setattr(os, "link", fail)
        with pytest.raises(OSError):
            publish(store)
        monkeypatch.setattr(os, "link", original)
    else:

        def fail(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith("INSERT INTO data_manifest"):
                raise RuntimeError("synthetic DB crash after artifacts")

        event.listen(store.engine, "before_cursor_execute", fail)
        with pytest.raises(RuntimeError):
            publish(store)
        event.remove(store.engine, "before_cursor_execute", fail)
    assert store.manifests() == []
    assert store.checkpoint("BTCUSDT") is None
    assert store.reconcile()["unpublished_orphans"] >= 1
    assert store.reconcile()["staging_files"] == 0
    manifest = publish(store)
    store.verify(manifest)
    assert store.reconcile()["unpublished_orphans"] == 0


def test_oi_staging_cleanup_quota_and_unlinked_orphan_report(store):
    first = publish(store)
    stage = store.root / "oi" / "incomplete.stage"
    stage.write_bytes(b"incomplete")
    assert store.reconcile()["staging_files"] == 1
    assert store.cleanup_staging() == 1
    orphan = store.root / "oi" / "raw" / ("0" * 64 + ".raw")
    orphan.write_bytes(b"orphan-not-admitted")
    assert store.reconcile()["unpublished_orphans"] == 1
    assert store.manifests() == [first]
    store.quota = 1
    with pytest.raises(ValueError, match="QUOTA"):
        publish(store, slot=NOW + timedelta(hours=1))
    store.verify(first)


def test_oi_symlink_or_reparse_escape_refused_without_following(store, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = store.root / "oi"
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            check=True,
            capture_output=True,
        )
    else:
        link.symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises(ValueError, match="UNSAFE_STORAGE"):
            publish(store)
        assert list(outside.iterdir()) == []
    finally:
        if os.name == "nt":
            os.rmdir(link)
        else:
            link.unlink()


@pytest.mark.parametrize("change", ["port", "database", "role", "host", "query"])
def test_oi_store_refuses_operational_or_ambiguous_endpoint_before_connect(tmp_path, change):
    args = {
        "host": "127.0.0.1",
        "port": 55433,
        "username": "auvexo_data_writer",
        "database": "auvexo_test_oisynthetic",
    }
    update = {
        "port": {"port": 55432},
        "database": {"database": "auvexo_paper"},
        "role": {"username": "auvexo_admin"},
        "host": {"host": "localhost"},
        "query": {"query": {"host": "127.0.0.1"}},
    }[change]
    engine = create_engine(URL.create("postgresql+psycopg", **(args | update)))
    try:
        with pytest.raises(ValueError, match="ISOLATED_DATABASE_REQUIRED"):
            OIStore(engine, tmp_path / "store", tmp_path)
        assert not (tmp_path / "store").exists()
    finally:
        engine.dispose()


def test_oi_rights_expiry_revocation_and_promotion_never_publish(store):
    parsed, raw = observation()
    for rights, at in [
        (accepted_oi_rights(), datetime(2026, 11, 27, tzinfo=UTC)),
        (accepted_oi_rights().model_copy(update={"revoked": True}), parsed.available_at),
    ]:
        with pytest.raises(ValueError, match="RIGHTS"):
            store.publish(parsed, raw, rights, now=at)
    with pytest.raises(ValueError, match="DATA_USE_DENIED"):
        store.publish(
            parsed, raw, classification=DataUseClass.PROMOTION_ELIGIBLE, now=parsed.available_at
        )
    assert store.manifests() == []
    manifest = store.publish(
        parsed, raw, classification=DataUseClass.PERSONAL_RESEARCH, now=parsed.available_at
    )
    assert manifest.classification == DataUseClass.PERSONAL_RESEARCH
    with pytest.raises(ValueError, match="ADMISSION_BLOCKED"):
        store.read_as_of(manifest, datetime(2026, 11, 27, tzinfo=UTC))


def test_oi_data_writer_append_only_and_financial_privileges_denied(store):
    publish(store)
    with store.engine.connect() as conn:
        assert conn.scalar(text("SELECT current_user")) == "auvexo_data_writer"
        assert conn.scalar(text("SELECT execution_enabled FROM foundation_policy")) is False
    for statement in (
        "UPDATE data_manifest SET source_hash=source_hash",
        "DELETE FROM data_manifest",
        "TRUNCATE data_manifest",
        "DELETE FROM data_event",
        "DELETE FROM data_checkpoint",
        "UPDATE data_source_review SET payload=payload",
        "SET ROLE auvexo_admin",
        "UPDATE foundation_policy SET execution_enabled=true",
        "CREATE TABLE forbidden(id int)",
    ):
        with pytest.raises(DBAPIError), store.engine.begin() as conn:
            conn.execute(text(statement))


def reservation(at=NOW, count=1, **kwargs):
    return OIBudgetState(
        hour_started_at=at.replace(minute=0, second=0, microsecond=0),
        day_started_at=at.replace(hour=0, minute=0, second=0, microsecond=0),
        hour_attempts=count,
        day_attempts=count,
        last_attempt_at=at,
        pending_attempt=True,
        **kwargs,
    )


def complete(state, **kwargs):
    return OIBudgetState.model_validate(state.model_dump() | {"pending_attempt": False} | kwargs)


def test_oi_budget_reservation_persists_before_network_and_unknown_restart_blocks(store):
    assert store.load_transport_state(NOW).hour_attempts == 0
    state = reservation()
    store.save_transport_state(state)
    restarted = OIStore(store.engine, store.root, store.managed_root)
    with pytest.raises(ValueError, match="OUTCOME_REVIEW_REQUIRED"):
        restarted.load_transport_state(NOW + timedelta(seconds=2))
    with pytest.raises(ValueError, match="OUTCOME_REVIEW_REQUIRED"):
        restarted.save_transport_state(reservation(NOW + timedelta(seconds=2), 2))
    store.save_transport_state(complete(state))
    assert restarted.load_transport_state(NOW + timedelta(seconds=2)).hour_attempts == 1
    with pytest.raises(ValueError, match="CONCURRENT_OR_INVALID"):
        restarted.save_transport_state(reservation(NOW + timedelta(seconds=1), 2))
    second = reservation(NOW + timedelta(seconds=2), 2)
    restarted.save_transport_state(second)
    restarted.save_transport_state(complete(second))
    assert store.load_transport_state(NOW + timedelta(seconds=3)).day_attempts == 2


def test_oi_cooldown_cannot_reset_on_restart_or_rollover(store):
    state = reservation()
    store.save_transport_state(state)
    until = NOW + timedelta(days=3)
    store.save_transport_state(complete(state, blocked_until=until))
    restarted = OIStore(store.engine, store.root, store.managed_root)
    assert restarted.load_transport_state(NOW + timedelta(days=1)).blocked_until == until
    next_day = reservation(NOW + timedelta(days=1), blocked_until=until)
    with pytest.raises(ValueError, match="CONCURRENT_OR_INVALID"):
        restarted.save_transport_state(next_day)
    cleared = reservation(until + timedelta(seconds=2))
    with pytest.raises(ValueError, match="COOLDOWN_REWIND"):
        restarted.save_transport_state(cleared)
    preserved = reservation(until + timedelta(seconds=2), blocked_until=until)
    restarted.save_transport_state(preserved)
    restarted.save_transport_state(complete(preserved))
    assert restarted.load_transport_state(until + timedelta(seconds=3)).day_attempts == 1


def test_oi_stale_cached_budget_cannot_duplicate_attempt(store):
    state = reservation()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(store.save_transport_state, state) for _ in range(2)]
        failures = [f.exception() for f in futures]
    assert sum(f is None for f in failures) == 1
    assert sum(isinstance(f, ValueError) for f in failures) == 1


def test_oi_source_global_lease_is_immediate_and_releases(store):
    with store.collection_lease() as first:
        assert first
        with store.collection_lease() as second:
            assert not second
    with store.collection_lease() as third:
        assert third


def test_oi_rejected_bytes_private_quarantine_idempotent(store):
    assert store.quarantine(b"invalid fixture", NOW, "PARSER_REJECTED") == store.quarantine(
        b"invalid fixture", NOW, "PARSER_REJECTED"
    )
    assert store.manifests() == []
    assert store.reconcile()["unpublished_orphans"] == 0


def research_chain(store, persist_forecast=True):
    from auvexo_alpha.application.oi_research import (
        OIStudyWindow,
        compute_oi_features,
        create_forecast,
    )

    previous = publish(store, slot=NOW - timedelta(hours=1), value="100")
    current = publish(store, value="101")
    study = OIStudyWindow(
        study_id="synthetic-oi-fwd",
        owner_start_at=datetime(2026, 10, 27, 12, tzinfo=UTC),
        preregistration_hash="c" * 64,
        code_hash="a" * 64,
        rights_snapshot_hash=accepted_oi_rights().content_hash(),
    )
    feature = compute_oi_features(current, previous, at=current.observation.available_at)
    forecast = create_forecast(study, feature, created_at=current.observation.available_at)
    store.append_study(study)
    store.append_feature(feature)
    if persist_forecast:
        store.append_prediction(forecast)
    return study, current, feature, forecast


def test_oi_ledger_prediction_is_immutable_before_target_and_score_bound(store):
    from auvexo_alpha.application.oi_research import score_forecast

    study, current, feature, forecast = research_chain(store)
    assert store.append_feature(feature) == feature.content_hash()
    assert store.append_prediction(forecast) == forecast.content_hash()
    assert store.features() == (feature,)
    assert store.forecasts(study.content_hash()) == (forecast,)
    assert store.scores(study.content_hash()) == ()
    target = publish(store, slot=NOW + timedelta(hours=1), value="102")
    score = score_forecast(study, forecast, current, target, scored_at=target.created_at)
    assert store.append_prediction(forecast) == forecast.content_hash()
    assert store.append_score(score) == score.content_hash()
    assert store.append_score(score) == score.content_hash()
    assert store.scores(study.content_hash()) == (score,)
    changed = forecast.model_copy(update={"created_at": forecast.created_at + timedelta(seconds=1)})
    with pytest.raises(ValueError, match="IMMUTABLE_LEDGER_CONFLICT"):
        store.append_prediction(changed)
    forged = score.model_copy(update={"outcome": Decimal("0.9")})
    with pytest.raises(ValueError, match="SCORE_BINDING"):
        store.append_score(forged)
    assert store.forecasts()[0] == forecast


def test_oi_missing_target_retains_original_forecast_and_no_retroactive_replacement(store):
    from auvexo_alpha.application.oi_research import score_forecast

    study, current, _, forecast = research_chain(store)
    score = score_forecast(
        study,
        forecast,
        current,
        None,
        scored_at=NOW + timedelta(hours=1, minutes=1),
    )
    store.append_score(score)
    assert not store.scores()[0].eligible
    assert store.forecasts() == (forecast,)
    target = publish(store, slot=NOW + timedelta(hours=1), value="102")
    retrospective = score_forecast(study, forecast, current, target, scored_at=target.created_at)
    with pytest.raises(ValueError, match="IMMUTABLE_LEDGER_CONFLICT"):
        store.append_score(retrospective)


def test_oi_ledger_missing_feature_study_or_manifest_cannot_be_forged(store):
    from auvexo_alpha.application.oi_research import (
        OIStudyWindow,
        compute_oi_features,
        create_forecast,
    )

    previous = publish(store, slot=NOW - timedelta(hours=1))
    current = publish(store, value="101")
    study = OIStudyWindow(
        study_id="synthetic-missing",
        owner_start_at=datetime(2026, 10, 27, 12, tzinfo=UTC),
        preregistration_hash="c" * 64,
        code_hash="a" * 64,
        rights_snapshot_hash=accepted_oi_rights().content_hash(),
    )
    feature = compute_oi_features(current, previous, at=current.created_at)
    forecast = create_forecast(study, feature, created_at=current.created_at)
    with pytest.raises(ValueError, match="RECORD_MISSING"):
        store.append_prediction(forecast)
    store.append_study(study)
    with pytest.raises(ValueError, match="RECORD_MISSING"):
        store.append_prediction(forecast)
    forged = feature.model_copy(update={"level": Decimal("999")})
    with pytest.raises(ValueError):
        store.append_feature(forged)
    assert store.forecasts() == ()


def test_oi_forged_rights_and_raw_provider_binding_refused(store):
    parsed, raw = observation()
    forged_rights = accepted_oi_rights().model_copy(update={"terms_hash": "0" * 64})
    with pytest.raises(ValueError, match="RIGHTS"):
        store.publish(parsed, raw, forged_rights, now=parsed.available_at)
    forged = parsed.model_copy(
        update={
            "raw_hash": hashlib.sha256(raw).hexdigest(),
            "value": Decimal("999"),
            "raw_open_interest": "999",
        }
    )
    with pytest.raises(ValueError, match="RAW_NORMALIZED_MISMATCH"):
        store.publish(forged, raw, now=parsed.available_at)
    assert store.manifests() == []


def test_oi_store_refuses_foreign_manifest_metadata_and_cannot_wrap_spot(store):
    first = publish(store)
    with store.engine.begin() as conn:
        conn.execute(
            text("INSERT INTO data_manifest VALUES (:v,:k,:s,:t,NULL,:h,:p)"),
            {
                "v": "9" * 64,
                "k": "spot-fixture",
                "s": "8" * 64,
                "t": NOW,
                "h": "7" * 64,
                "p": "{}",
            },
        )
    with pytest.raises(ValueError, match="DEDICATED_DATABASE_REQUIRED"):
        OIStore(store.engine, store.root, store.managed_root)
    original_artifacts = {
        path: path.read_bytes() for path in store.root.rglob("*") if path.is_file()
    }
    with pytest.raises(ValueError, match="DEDICATED_DATABASE_REQUIRED"):
        publish(store, slot=NOW + timedelta(hours=1))
    assert {path: path.read_bytes() for path in store.root.rglob("*") if path.is_file()} == (
        original_artifacts
    )
    store.verify(first)


def test_oi_postgres_manifest_parser_discriminator_is_explicit(store):
    manifest = publish(store)
    with store.engine.connect() as conn:
        assert (
            conn.scalar(
                text(
                    "SELECT payload::jsonb->>'parser_version' FROM data_manifest "
                    "WHERE dataset_version=:v"
                ),
                {"v": manifest.dataset_version},
            )
            == "oi-snapshot.v1"
        )
    assert manifest.retention_profile == "REVIEW_BEFORE_REMOVAL_NO_AGE_CAP"


def test_oi_synthetic_resource_envelope(store):
    """Tiny hourly source: measured fixtures are engineering only, never feed evidence."""
    parsed, raw = observation()
    tracemalloc.start()
    started = time.perf_counter()
    for _ in range(1000):
        result, _ = observation()
        assert result.raw_hash == parsed.raw_hash
    parser_seconds = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    started = time.perf_counter()
    first = store.publish(parsed, raw, now=parsed.available_at)
    one_symbol_seconds = time.perf_counter() - started
    started = time.perf_counter()
    btc = publish(store, slot=NOW + timedelta(hours=1))
    eth = publish(store, slot=NOW + timedelta(hours=1), symbol="ETHUSDT")
    two_symbol_seconds = time.perf_counter() - started
    assert peak < 32 * 1024 * 1024
    assert len(raw) <= 4096
    assert first.raw_bytes + first.normalized_bytes < 20480
    assert btc.observation.quality == eth.observation.quality == "VALID"
    report = {
        "kind": "SYNTHETIC_ENGINEERING_ONLY_NONCOUNTING",
        "iterations": 1000,
        "parser_total_seconds": parser_seconds,
        "parser_records_per_second": 1000 / parser_seconds,
        "python_tracemalloc_peak_bytes": peak,
        "raw_bytes": first.raw_bytes,
        "normalized_bytes": first.normalized_bytes,
        "one_symbol_publish_seconds": one_symbol_seconds,
        "two_symbol_publish_seconds": two_symbol_seconds,
        "endpoint_calls": 0,
        "clock_days": 0,
        "worker_count": 1,
        "queue": "NONE_IMMEDIATE_LEASE_NO_BUSY_LOOP",
        "database_port": store.engine.url.port,
        "database": store.engine.url.database,
    }
    output = os.environ.get("AUVEXO_OI_RESOURCE_REPORT")
    if output:
        destination = Path(output).absolute()
        allowed = (Path.cwd() / ".local").absolute()
        if not destination.is_relative_to(allowed):
            raise ValueError("resource receipt must stay in ignored Development .local")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf8")
    print(json.dumps(report, sort_keys=True))


@pytest.mark.parametrize("future_symbol", ["BTCUSDT", "ETHUSDT"])
def test_oi_new_backdated_forecast_cannot_be_inserted_after_same_symbol_future_fact(
    store, future_symbol
):
    _, _, _, forecast = research_chain(store, persist_forecast=False)
    assert store.forecasts() == ()
    publish(store, slot=NOW + timedelta(hours=1), symbol=future_symbol, value="102")
    if future_symbol == forecast.symbol:
        with pytest.raises(ValueError, match="FORECAST_AFTER_FUTURE_FACT"):
            store.append_prediction(forecast)
        assert store.forecasts() == ()
    else:
        assert store.append_prediction(forecast) == forecast.content_hash()
        assert store.forecasts() == (forecast,)


def synthetic_review_authority(accepted_at):
    """Test-only external acceptance fixture; never an actual rights renewal."""
    from auvexo_alpha.domain.oi_rights_review import OIReviewAuthority, OIReviewContinuation

    rights = accepted_oi_rights()
    receipt = OIReviewContinuation(
        base_rights_hash=rights.content_hash(),
        previous_review_hash=rights.content_hash(),
        source_hash=rights.source.content_hash(),
        reviewed_at=accepted_at - timedelta(hours=1),
        accepted_at=accepted_at,
        next_review_due=datetime(2027, 1, 30, tzinfo=UTC),
        review_ref="synthetic-review-only",
        independent_acceptance_ref="synthetic-independent-only",
    )
    return OIReviewAuthority(rights, (receipt,), (receipt.content_hash(),), accepted_at)


def test_oi_same_evidence_review_continues_fixed_study_and_persists_external_proof(store):
    from auvexo_alpha.application.oi_research import (
        OIStudyWindow,
        compute_oi_features,
        create_forecast,
        score_forecast,
    )

    before = datetime(2026, 11, 26, 23, tzinfo=UTC)
    previous = publish(store, slot=before - timedelta(hours=1), value="100")
    current = publish(store, slot=before, value="101")
    study = OIStudyWindow(
        study_id="synthetic-continuing-study",
        owner_start_at=datetime(2026, 10, 27, 12, tzinfo=UTC),
        preregistration_hash="c" * 64,
        code_hash="a" * 64,
        rights_snapshot_hash=accepted_oi_rights().content_hash(),
    )
    feature = compute_oi_features(current, previous, at=current.created_at)
    forecast = create_forecast(study, feature, created_at=current.created_at)
    original_study_hash = store.append_study(study)
    store.append_feature(feature)
    store.append_prediction(forecast)
    authority = synthetic_review_authority(datetime(2026, 11, 26, 12, tzinfo=UTC))
    continued = OIStore(
        store.engine,
        store.root,
        store.managed_root,
        review_authority=authority,
    )
    target_at = before + timedelta(hours=1)
    receipt_hash = authority.receipt_hash_at(target_at + timedelta(seconds=3))
    target = publish(continued, slot=target_at, value="102", review_receipt_hash=receipt_hash)
    assert target.observation.review_receipt_hash == receipt_hash
    assert target.rights.content_hash() == study.rights_snapshot_hash
    assert current.observation.review_receipt_hash is None
    continued.verify(target)
    assert continued.read_as_of(current, target.created_at) == current.observation
    feature_after = compute_oi_features(
        target,
        current,
        at=target.created_at,
        review_authority=authority,
    )
    continued.append_feature(feature_after)
    score = score_forecast(
        study,
        forecast,
        current,
        target,
        scored_at=target.created_at,
        review_authority=authority,
    )
    continued.append_score(score)
    assert continued.append_study(study) == original_study_hash
    assert continued.forecasts(study.content_hash()) == (forecast,)
    assert continued.scores(study.content_hash()) == (score,)
    assert study.evaluation_start == datetime(2026, 10, 30, tzinfo=UTC)
    assert study.evaluation_end == datetime(2027, 1, 28, tzinfo=UTC)
    with store.engine.connect() as conn:
        assert conn.scalar(
            text("SELECT payload FROM data_source_review WHERE review_hash=:h"), {"h": receipt_hash}
        ) == authority.chain[0].canonical_bytes().decode("ascii")
    with pytest.raises(ValueError, match="ADMISSION_BLOCKED"):
        store.read_as_of(target, target.created_at)


def test_oi_late_review_leaves_gap_and_cannot_backdate_or_forge_receipt_stamp(store):
    accepted_at = datetime(2026, 11, 28, tzinfo=UTC)
    authority = synthetic_review_authority(accepted_at)
    continued = OIStore(
        store.engine,
        store.root,
        store.managed_root,
        review_authority=authority,
    )
    missing_at = datetime(2026, 11, 27, 10, tzinfo=UTC)
    gap, raw = observation(missing_at, review_receipt_hash=authority.chain[0].content_hash())
    with pytest.raises(ValueError, match="REVIEW_GAP_BLOCKED"):
        continued.publish(gap, raw, now=accepted_at)
    valid_at = accepted_at + timedelta(hours=10)
    parsed, raw = observation(valid_at)
    with pytest.raises(ValueError, match="REVIEW_RECEIPT_BINDING"):
        continued.publish(parsed, raw, now=parsed.available_at)
    forged = parsed.model_copy(update={"review_receipt_hash": "0" * 64})
    with pytest.raises(ValueError, match="REVIEW_RECEIPT_BINDING"):
        continued.publish(forged, raw, now=forged.available_at)
    assert continued.manifests() == []


def _generic_counts(store):
    with store.engine.connect() as conn:
        return tuple(
            conn.scalar(text("SELECT count(*) FROM " + table))
            for table in (
                "data_spec",
                "data_manifest",
                "data_checkpoint",
                "data_event",
                "data_source_review",
            )
        )


@pytest.mark.parametrize(
    "table,namespace",
    [
        ("data_spec", "foreign-instrument-spec"),
        ("data_manifest", "spot-fixture"),
        ("data_manifest", "ds04-a1:spot-fixture"),
        ("data_manifest", "ds04-a1:BTCUSDT:1793354401000:spot.v2"),
        ("data_manifest", "ds04-a1:BTCUSDT:1793354401000:oi-snapshot.v1:extra"),
        ("data_checkpoint", "DS-02:BTCUSDT"),
        ("data_checkpoint", "DS-04-A1:BTCUSDT:extra"),
        ("data_checkpoint", "DS-04-A1:SOLUSDT"),
        ("data_event", "DS-02:transport-budget"),
        ("data_event", "DS-04-A1:transport-budget:extra"),
        ("data_event", "DS-04-A1:ledger:OTHER"),
        ("data_source_review", "foreign-rights"),
    ],
)
def test_oi_initialization_attests_every_generic_table_and_retains_foreign_rows(
    store, table, namespace
):
    manifest = publish(store)
    with store.engine.begin() as conn:
        if table == "data_spec":
            conn.execute(
                text("INSERT INTO data_spec VALUES (:h,:s,:p)"),
                {"h": "6" * 64, "s": json.dumps({"source": namespace}), "p": b"{}"},
            )
        elif table == "data_manifest":
            conn.execute(
                text("INSERT INTO data_manifest VALUES (:v,:k,:s,:t,NULL,:h,:p)"),
                {
                    "v": "9" * 64,
                    "k": namespace,
                    "s": "8" * 64,
                    "t": NOW,
                    "h": "7" * 64,
                    "p": "{}",
                },
            )
        elif table == "data_checkpoint":
            conn.execute(
                text("INSERT INTO data_checkpoint VALUES (:f,:n,:v,:t)"),
                {
                    "f": namespace,
                    "n": NOW + timedelta(hours=1),
                    "v": manifest.dataset_version,
                    "t": NOW,
                },
            )
        elif table == "data_event":
            conn.execute(
                text(
                    "INSERT INTO data_event(event_id,feed_key,observed_at,payload) "
                    "VALUES (:i,:f,:t,:p)"
                ),
                {"i": "oi-budget:" + "a" * 64, "f": namespace, "t": NOW, "p": "{}"},
            )
        else:
            conn.execute(
                text("INSERT INTO data_source_review VALUES (:h,:p)"),
                {
                    "h": "a" * 64,
                    "p": json.dumps({"source": namespace}),
                },
            )
    before = _generic_counts(store)
    files_before = {
        p.relative_to(store.root): p.read_bytes() for p in store.root.rglob("*") if p.is_file()
    }
    destination = store.root / "uncreated-restart-root"
    with pytest.raises(ValueError, match="^OI_DEDICATED_DATABASE_REQUIRED$"):
        OIStore(store.engine, destination, store.managed_root)
    assert not destination.exists()
    assert _generic_counts(store) == before
    with pytest.raises(ValueError, match="^OI_DEDICATED_DATABASE_REQUIRED$"):
        publish(store, slot=NOW + timedelta(hours=1))
    assert _generic_counts(store) == before
    assert {
        p.relative_to(store.root): p.read_bytes() for p in store.root.rglob("*") if p.is_file()
    } == files_before


@pytest.mark.parametrize(
    "feed,identifier",
    [
        ("DS-04-A1:transport-budget", "foreign-budget:" + "a" * 64),
        ("DS-04-A1:transport-budget", "oi-budget:" + "a" * 64 + ":extra"),
        ("DS-04-A1:quarantine", "oi-budget:" + "a" * 64),
        ("DS-04-A1:quarantine", "oi-quarantine:" + "a" * 64 + ":UNKNOWN"),
        ("DS-04-A1:ledger:FEATURE", "oi-ledger:FORECAST:" + "a" * 64),
        ("DS-04-A1:ledger:STUDY", "oi-ledger:STUDY:" + "a" * 63),
    ],
)
def test_oi_initialization_rejects_event_namespace_identifier_mismatches(store, feed, identifier):
    with store.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO data_event(event_id,feed_key,observed_at,payload) "
                "VALUES (:i,:f,:t,'{}')"
            ),
            {"i": identifier, "f": feed, "t": NOW},
        )
    before = _generic_counts(store)
    with pytest.raises(ValueError, match="^OI_DEDICATED_DATABASE_REQUIRED$"):
        OIStore(store.engine, store.root, store.managed_root)
    assert _generic_counts(store) == before


def test_oi_restart_accepts_exact_base_review_and_all_implemented_event_namespaces(store):
    from auvexo_alpha.application.oi_research import score_forecast

    base = accepted_oi_rights()
    with store.engine.begin() as conn:
        conn.execute(
            text("INSERT INTO data_source_review VALUES (:h,:p)"),
            {
                "h": base.content_hash(),
                "p": base.canonical_bytes().decode("ascii"),
            },
        )
    restarted = OIStore(store.engine, store.root, store.managed_root)
    study, current, _, forecast = research_chain(restarted)
    target = publish(restarted, slot=NOW + timedelta(hours=1), value="102")
    score = score_forecast(study, forecast, current, target, scored_at=target.created_at)
    restarted.append_score(score)
    state = reservation()
    restarted.save_transport_state(state)
    restarted.save_transport_state(complete(state))
    restarted.quarantine(b"synthetic rejected bytes", NOW, "PARSER_REJECTED")
    before = _generic_counts(restarted)
    accepted = OIStore(store.engine, store.root, store.managed_root)
    assert accepted.forecasts() == (forecast,)
    assert accepted.scores() == (score,)
    assert _generic_counts(accepted) == before


@pytest.mark.parametrize("mutation", ["payload", "hash"])
def test_oi_restart_requires_exact_canonical_base_review_hash_and_payload(store, mutation):
    base = accepted_oi_rights()
    digest = base.content_hash() if mutation == "payload" else "a" * 64
    payload = base.canonical_bytes().decode("ascii") + (" " if mutation == "payload" else "")
    with store.engine.begin() as conn:
        conn.execute(
            text("INSERT INTO data_source_review VALUES (:h,:p)"), {"h": digest, "p": payload}
        )
    before = _generic_counts(store)
    with pytest.raises(ValueError, match="^OI_DEDICATED_DATABASE_REQUIRED$"):
        OIStore(store.engine, store.root, store.managed_root)
    assert _generic_counts(store) == before


def test_oi_restart_requires_supplied_external_acceptance_for_continuation_rows(store):
    authority = synthetic_review_authority(datetime(2026, 11, 26, 12, tzinfo=UTC))
    receipt = authority.chain[0]
    with store.engine.begin() as conn:
        conn.execute(
            text("INSERT INTO data_source_review VALUES (:h,:p)"),
            {
                "h": receipt.content_hash(),
                "p": receipt.canonical_bytes().decode("ascii"),
            },
        )
    before = _generic_counts(store)
    with pytest.raises(ValueError, match="^OI_DEDICATED_DATABASE_REQUIRED$"):
        OIStore(store.engine, store.root, store.managed_root)
    restarted = OIStore(store.engine, store.root, store.managed_root, review_authority=authority)
    assert restarted.review_authority == authority
    assert _generic_counts(store) == before


def test_oi_restart_rejects_continuation_not_in_supplied_accepted_chain(store):
    authority = synthetic_review_authority(datetime(2026, 11, 26, 12, tzinfo=UTC))
    unaccepted = authority.chain[0].model_copy(update={"review_ref": "synthetic-unaccepted"})
    with store.engine.begin() as conn:
        conn.execute(
            text("INSERT INTO data_source_review VALUES (:h,:p)"),
            {
                "h": unaccepted.content_hash(),
                "p": unaccepted.canonical_bytes().decode("ascii"),
            },
        )
    before = _generic_counts(store)
    with pytest.raises(ValueError, match="^OI_DEDICATED_DATABASE_REQUIRED$"):
        OIStore(store.engine, store.root, store.managed_root, review_authority=authority)
    assert _generic_counts(store) == before
