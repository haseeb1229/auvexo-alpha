from datetime import UTC, date, datetime, timedelta

import pytest

from auvexo_alpha.application.data_reporting import coverage_matrix, qualification
from auvexo_alpha.application.demo_data_gate import DemoDataPrerequisites, require_demo_data
from auvexo_alpha.domain.contracts import Product, Venue
from auvexo_alpha.domain.market_data import IngestionEvent, InstrumentAlias, SpecSnapshot
from auvexo_alpha.infrastructure.data_store import pressure, tree_bytes
from auvexo_alpha.infrastructure.source_registry import rights


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


def test_seven_actual_calendar_days_not_seven_minutes():
    start = datetime(2026, 10, 17, tzinfo=UTC)
    events = []
    for day in range(7):
        for minute in range(12):
            for symbol in ("BTCUSDT", "ETHUSDT"):
                events.append(
                    IngestionEvent(
                        event_id=f"d{day}.m{minute}.{symbol}",
                        feed_key=f"DS-02.{symbol}.1m",
                        observed_at=start + timedelta(days=day, minutes=minute),
                        state="FRESH",
                        reason="CANDLES_PASS",
                        requests=1,
                        network_bytes=10,
                        dataset_version="0" * 64,
                    )
                )
    assert (
        qualification(events, date(2026, 10, 17), start + timedelta(minutes=7))["status"] == "OPEN"
    )
    assert qualification(events, date(2026, 10, 17), start + timedelta(days=7))["status"] == "PASS"
    assert (
        qualification(events[:-10], date(2026, 10, 17), start + timedelta(days=7))["status"]
        == "OPEN"
    )
    assert qualification([], date(2026, 10, 17), start)["status"] == "OPEN"
