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
    start = datetime(2026, 10, 18, 18, tzinfo=UTC)
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


def shift_observations(events, manifests, delta):
    """Move internally consistent synthetic receipts without changing their quality."""
    return (
        [e.model_copy(update={"observed_at": e.observed_at + delta}) for e in events],
        [
            m.model_copy(
                update={
                    "created_at": m.created_at + delta,
                    "processed_at": m.processed_at + delta,
                    "coverage": m.coverage.model_copy(
                        update={
                            key: getattr(m.coverage, key) + delta
                            for key in (
                                "requested_start",
                                "requested_end",
                                "earliest",
                                "latest_end",
                            )
                        }
                    ),
                }
            )
            for m in manifests
        ],
    )


@pytest.mark.parametrize("hours", [-18, -1, 1])
def test_old_midnight_and_other_windows_never_qualify(hours):
    start, events, manifests = observation_fixtures()
    events, manifests = shift_observations(events, manifests, timedelta(hours=hours))
    report = qualification(events, start.date(), start + timedelta(days=7), manifests)
    assert report["status"] == "OPEN"
    assert all(day["events"] == 0 for day in report["days"])


def test_window_boundaries_close_and_schedule_effective_date():
    start, events, manifests = observation_fixtures()
    # Start inclusive: moving :15 to :00 preserves all evidence/freshness requirements.
    events, manifests = shift_observations(events, manifests, -timedelta(seconds=15))
    report = qualification(events, start.date(), start + timedelta(days=6, minutes=12), manifests)
    assert report["status"] == "PASS"
    assert report["days"][0]["first"] == start.isoformat()
    before_close = qualification(
        events, start.date(), start + timedelta(days=6, minutes=12, microseconds=-1), manifests
    )
    assert before_close["days"][-1]["status"] == "OPEN"
    # An event exactly at 18:12 is excluded, even when marked FRESH.
    outside = events[0].model_copy(update={"observed_at": start + timedelta(minutes=12)})
    assert (
        qualification([*events, outside], start.date(), start + timedelta(days=7), manifests)[
            "days"
        ][0]["events"]
        == 24
    )
    # Seven real calendar dates are required, including across a month boundary.
    shifted, shifted_manifests = shift_observations(events, manifests, timedelta(days=13))
    assert (
        qualification(shifted, date(2026, 10, 31), start + timedelta(days=20), shifted_manifests)[
            "status"
        ]
        == "PASS"
    )
    missing_day = [e for e in events if e.observed_at.date() != date(2026, 10, 21)]
    assert (
        qualification(missing_day, start.date(), start + timedelta(days=7), manifests)["status"]
        == "OPEN"
    )
    earlier, earlier_manifests = shift_observations(events, manifests, -timedelta(days=1))
    assert (
        qualification(earlier, date(2026, 10, 17), start + timedelta(days=7), earlier_manifests)[
            "days"
        ][0]["status"]
        == "INCOMPLETE"
    )


@pytest.mark.parametrize("fault", ["count", "span", "gap", "version"])
def test_observation_thresholds_remain_strict(fault):
    start, events, manifests = observation_fixtures()
    if fault == "count":
        events = [e for e in events if e.observed_at >= start + timedelta(minutes=2)]
    elif fault == "span":
        # Eleven observations cannot compensate for less than ten minutes of coverage.
        events = [e for e in events if e.observed_at < start + timedelta(minutes=11)]
        events, manifests = shift_observations(events, manifests, -timedelta(seconds=1))
        events[0] = events[0].model_copy(
            update={"observed_at": events[0].observed_at + timedelta(seconds=1)}
        )
        manifests[0] = manifests[0].model_copy(
            update={"created_at": events[0].observed_at, "processed_at": events[0].observed_at}
        )
    elif fault == "gap":
        # Keep eleven observations and the full span, but create a 121-second gap.
        events = [
            e
            for e in events
            if not start + timedelta(minutes=1) <= e.observed_at < start + timedelta(minutes=2)
        ]
        for index in (2, 3):
            shifted = events[index].observed_at + timedelta(seconds=1)
            events[index] = events[index].model_copy(update={"observed_at": shifted})
        for index in (4, 5):
            shifted = manifests[index].created_at + timedelta(seconds=1)
            manifests[index] = manifests[index].model_copy(
                update={"created_at": shifted, "processed_at": shifted}
            )
    else:
        events[2] = events[2].model_copy(update={"dataset_version": events[0].dataset_version})
    assert (
        qualification(events, start.date(), start + timedelta(days=7), manifests)["status"]
        == "OPEN"
    )


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
