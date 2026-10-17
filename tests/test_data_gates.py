from datetime import UTC, date, datetime, timedelta
from hashlib import sha256

import pytest

from auvexo_alpha.application.data_reporting import coverage_matrix, qualification
from auvexo_alpha.application.demo_data_gate import DemoDataPrerequisites, require_demo_data
from auvexo_alpha.domain.contracts import Product, Venue
from auvexo_alpha.domain.market_data import (
    CoverageReport,
    DatasetManifest,
    IngestionEvent,
    InstrumentAlias,
    SpecSnapshot,
)
from auvexo_alpha.infrastructure.data_store import pressure, tree_bytes
from auvexo_alpha.infrastructure.source_registry import identity, rights


@pytest.mark.parametrize(
    "kind,origin",
    [("REAL", "TERMINAL"), ("UNKNOWN", "TERMINAL"), ("DEMO", "LABEL"), ("DEMO", "TERMINAL")],
)
def test_exness_unconditionally_disabled(kind, origin):
    with pytest.raises(ValueError):
        require_demo_data(
            DemoDataPrerequisites(terminal_account_type=kind, attestation_origin=origin)
        )
    with pytest.raises(ValueError, match="NOT_PROVISIONED"):
        require_demo_data(
            DemoDataPrerequisites(
                owner_authorized=True,
                encrypted_os_store=True,
                isolated_process=True,
                dedicated_demo_profile=True,
                provider_terms_reviewed=True,
                terminal_account_type="DEMO",
                attestation_origin="TERMINAL",
            )
        )


def test_unknown_specs_remain_unknown_and_venue_not_interchangeable():
    alias = InstrumentAlias(
        instrument_id="exness.cfd.XAU",
        asset="XAU",
        venue=Venue.EXNESS,
        product=Product.CFD,
        provider_symbol=None,
        quote_currency=None,
        mapping_version="unknown.v1",
    )
    spec = SpecSnapshot(
        alias=alias,
        source_id="DS-03",
        observed_at=datetime.now(UTC),
        spec_version="0" * 64,
        provenance_url="NOT_OBSERVED",
    )
    assert spec.price_tick is None and spec.quantity_unit == "UNKNOWN"
    with pytest.raises(ValueError):
        InstrumentAlias.model_validate(alias.model_dump() | {"venue": Venue.BINANCE})
    assert all(row["earliest"] is None for row in coverage_matrix([]))


@pytest.mark.parametrize(
    "managed,free,expected",
    [
        (0, 100_000_000_000, "NORMAL"),
        (120_000_000_000, 100_000_000_000, "PAUSE_BACKFILL"),
        (135_000_000_000, 100_000_000_000, "PAUSE_OPTIONAL"),
        (150_000_000_000, 100_000_000_000, "HARD_STOP"),
        (0, 10_000_000_000, "HARD_STOP"),
        (0, 30_000_000_000, "PAUSE_OPTIONAL"),
        (0, 50_000_000_000, "PAUSE_BACKFILL"),
    ],
)
def test_storage_pressure(managed, free, expected):
    assert pressure(managed, free) == expected


def test_storage_scan_counts_nested_bytes_and_refuses_unreadable(tmp_path, monkeypatch):
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "raw").write_bytes(b"12345")
    assert tree_bytes(tmp_path) == 5

    def refuse(path):
        raise PermissionError("unreadable managed storage")

    monkeypatch.setattr("auvexo_alpha.infrastructure.data_store.os.scandir", refuse)
    with pytest.raises(PermissionError):
        tree_bytes(tmp_path)


def test_rights_expiry_fails_closed():
    with pytest.raises(ValueError):
        rights("DS-01").require_research(datetime(2027, 1, 1, tzinfo=UTC))


def observation_fixtures():
    """Synthetic domain fixtures only: these never qualify an actual provider or stored run."""
    start = datetime(2026, 10, 17, tzinfo=UTC)
    events, manifests = [], []
    for day in range(7):
        for minute in range(12):
            for symbol in ("BTCUSDT", "ETHUSDT"):
                observed = start + timedelta(days=day, minutes=minute, seconds=15)
                end = observed.replace(second=0)
                digest = sha256(f"fixture.{day}.{minute}.{symbol}".encode()).hexdigest()
                feed = f"DS-02.{symbol}.1m"
                manifests.append(
                    DatasetManifest(
                        dataset_version=digest,
                        logical_key=feed + f".{day}.{minute}",
                        source=identity("DS-02"),
                        rights=rights("DS-02"),
                        source_url="https://data-api.binance.vision/api/v3/klines?symbol=" + symbol,
                        source_hash=digest,
                        checksum_verified=False,
                        raw_bytes=1,
                        raw_relative_path="bronze/" + digest + ".raw",
                        parquet_hash=digest,
                        parquet_bytes=1,
                        relative_path=f"partitions/binance.spot.{symbol}/{digest}.parquet",
                        normalized_hash=digest,
                        code_revision="synthetic-domain-fixture",
                        code_hash=digest,
                        created_at=observed,
                        processed_at=observed,
                        coverage=CoverageReport(
                            instrument_id="binance.spot." + symbol,
                            interval="1m",
                            requested_start=end - timedelta(minutes=1),
                            requested_end=end,
                            earliest=end - timedelta(minutes=1),
                            latest_end=end,
                            expected_rows=1,
                            observed_rows=1,
                            rejected_rows=0,
                            findings=(),
                            status="PASS",
                        ),
                        supersedes=None,
                        changed_rows=0,
                    )
                )
                events.append(
                    IngestionEvent(
                        event_id=f"d{day}.m{minute}.{symbol}",
                        feed_key=f"DS-02.{symbol}.1m",
                        observed_at=observed,
                        state="FRESH",
                        reason="CANDLES_PASS",
                        requests=1,
                        network_bytes=10,
                        dataset_version=digest,
                    )
                )
    return start, events, manifests


def test_seven_actual_calendar_days_not_seven_minutes():
    start, events, manifests = observation_fixtures()
    assert (
        qualification(events, start.date(), start + timedelta(minutes=7), manifests)["status"]
        == "OPEN"
    )
    assert (
        qualification(events, start.date(), start + timedelta(days=7), manifests)["status"]
        == "PASS"
    )
    assert (
        qualification(events[:-10], start.date(), start + timedelta(days=7), manifests)["status"]
        == "OPEN"
    )
    assert qualification([], date(2026, 10, 17), start, manifests)["status"] == "OPEN"


@pytest.mark.parametrize(
    "fault", ["missing", "symbol", "degraded", "stale", "receipt", "archive", "future", "duplicate"]
)
def test_fresh_strings_or_invalid_dataset_cannot_qualify(fault):
    start, events, manifests = observation_fixtures()
    now = start + timedelta(days=7)
    manifest = manifests[0]
    if fault == "missing":
        manifests = []
    elif fault == "symbol":
        manifests[0] = manifest.model_copy(
            update={
                "coverage": manifest.coverage.model_copy(
                    update={"instrument_id": "binance.spot.ETHUSDT"}
                )
            }
        )
    elif fault == "degraded":
        manifests[0] = manifest.model_copy(
            update={"coverage": manifest.coverage.model_copy(update={"status": "DEGRADED"})}
        )
    elif fault == "stale":
        manifests[0] = manifest.model_copy(
            update={
                "coverage": manifest.coverage.model_copy(
                    update={"requested_end": manifest.created_at - timedelta(minutes=3)}
                )
            }
        )
    elif fault == "receipt":
        manifests[0] = manifest.model_copy(
            update={"created_at": manifest.created_at + timedelta(seconds=1)}
        )
    elif fault == "archive":
        manifests[0] = manifest.model_copy(update={"source": identity("DS-01")})
    elif fault == "future":
        manifests[0] = manifest.model_copy(update={"processed_at": now + timedelta(seconds=1)})
    else:
        events.append(events[0])
    report = qualification(events, start.date(), now, manifests)
    assert report["status"] == "OPEN" and report["days"][0]["status"] == "INCOMPLETE"
