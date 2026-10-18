"""Synthetic adversarial fixtures, never used as source-qualification evidence."""

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from auvexo_alpha.application.data_quality import assess
from auvexo_alpha.domain.market_data import Candle
from auvexo_alpha.infrastructure.spot_parser import (
    EPOCH,
    parse_archive,
    parse_rest,
    parse_row,
    timestamp,
)

NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)


def row(start, micros=False, price="100"):
    scale = timedelta(microseconds=1) if micros else timedelta(milliseconds=1)
    return [
        str((start - EPOCH) // scale),
        price,
        "110",
        "90",
        "105",
        "3",
        str((start + timedelta(hours=1) - EPOCH) // scale - 1),
        "300",
        "4",
        "1",
        "100",
        "0",
    ]


def archive(rows, name="BTCUSDT-1h-2024-12-31.csv"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr(name, "\n".join(",".join(map(str, r)) for r in rows))
    raw = buffer.getvalue()
    checksum = f"{hashlib.sha256(raw).hexdigest()}  BTCUSDT-1h-2024-12-31.zip\n".encode()
    return raw, checksum


def bar(start, price="100"):
    return parse_row(
        row(start),
        "BTCUSDT",
        "1h",
        "MILLISECOND",
        "DS-02",
        "https://fixture.invalid",
        "0" * 64,
        NOW,
    )


@pytest.mark.parametrize(
    "day,micros",
    [(datetime(2024, 12, 31, tzinfo=UTC), False), (datetime(2025, 1, 1, tzinfo=UTC), True)],
)
def test_timestamp_transition_golden(day, micros):
    raw, checksum = archive([row(day, micros)])
    bars, report = parse_archive(
        raw,
        checksum,
        "BTCUSDT-1h-2024-12-31.zip",
        "BTCUSDT",
        "1h",
        day,
        day + timedelta(hours=1),
        NOW,
        "https://fixture.invalid",
    )
    assert report.status == "PASS"
    assert bars[0].open_at == day and bars[0].end_at == day + timedelta(hours=1)
    assert bars[0].source.timestamp_unit == ("MICROSECOND" if micros else "MILLISECOND")
    rest = parse_row(
        row(day), "BTCUSDT", "1h", "MILLISECOND", "DS-02", "https://fixture.invalid", "0" * 64, NOW
    )
    assert rest.open_at == bars[0].open_at and rest.end_at == bars[0].end_at
    assert bars[0].availability.original_first_seen_at is None
    with pytest.raises(ValueError, match="LOOKAHEAD"):
        bars[0].require_as_of(day + timedelta(hours=1))
    bars[0].require_as_of(NOW)


@pytest.mark.parametrize(
    "raw", [0, True, -1, 10**30, "1735689600000000000", 1735689600000000, "1e12", 1.2]
)
def test_implausible_and_ambiguous_times(raw):
    with pytest.raises(ValueError):
        timestamp(raw, "MILLISECOND", NOW)


@given(st.integers(min_value=1500000000000, max_value=1750000000000))
def test_units_preserve_same_instant(value):
    assert timestamp(value, "MILLISECOND", NOW) == timestamp(value * 1000, "MICROSECOND", NOW)


@pytest.mark.parametrize(
    "index,value",
    [(1, 1.2), (1, "NaN"), (1, "0"), (2, "99"), (3, "106"), (5, "-1"), (7, "Infinity"), (8, True)],
)
def test_financial_and_ohlc_rejections(index, value):
    values = row(datetime(2024, 12, 31, tzinfo=UTC))
    values[index] = value
    with pytest.raises(ValueError):
        parse_row(
            values,
            "BTCUSDT",
            "1h",
            "MILLISECOND",
            "DS-01",
            "https://fixture.invalid",
            "0" * 64,
            NOW,
        )


def test_partial_and_close_semantics():
    values = row(NOW)
    with pytest.raises(ValueError, match="PARTIAL"):
        parse_row(values, "BTCUSDT", "1h", "MILLISECOND", "DS-02", "x", "0" * 64, NOW)
    values = row(NOW - timedelta(hours=1))
    values[6] = str(int(values[6]) + 1)
    with pytest.raises(ValueError, match="TIMESTAMP_UNIT"):
        parse_row(
            values,
            "BTCUSDT",
            "1h",
            "MILLISECOND",
            "DS-02",
            "x",
            "0" * 64,
            NOW,
            parser_version="spot.v1",
        )
    with pytest.raises(ValueError, match="INTERVAL_BOUNDARY"):
        parse_row(values, "BTCUSDT", "1h", "MILLISECOND", "DS-02", "x", "0" * 64, NOW)


@pytest.mark.parametrize(
    "name", ["../escape.csv", "/absolute.csv", "nested/file.csv", "C:\\escape.csv", "wrong.csv"]
)
def test_archive_paths_refused(name):
    start = datetime(2024, 12, 31, tzinfo=UTC)
    raw, checksum = archive([row(start)], name)
    with pytest.raises(ValueError, match="UNSAFE_ARCHIVE"):
        parse_archive(
            raw,
            checksum,
            "BTCUSDT-1h-2024-12-31.zip",
            "BTCUSDT",
            "1h",
            start,
            start + timedelta(hours=1),
            NOW,
            "x",
        )


@pytest.mark.parametrize("kind", ["missing", "wrong", "corrupt", "bomb", "longrow", "encoding"])
def test_bad_archive_checksum_and_bounds(kind):
    start = datetime(2024, 12, 31, tzinfo=UTC)
    values = [row(start)]
    if kind == "bomb":
        values = [["0" * 100000]]
    if kind == "longrow":
        values = [["a" * 5000]]
    if kind == "encoding":
        values = [["é"]]
    raw, checksum = archive(values)
    if kind == "missing":
        checksum = b""
    if kind == "wrong":
        checksum = b"0" * 64 + b"  BTCUSDT-1h-2024-12-31.zip"
    if kind == "corrupt":
        raw = b"not a zip"
        checksum = hashlib.sha256(raw).hexdigest().encode() + b"  BTCUSDT-1h-2024-12-31.zip"
    with pytest.raises(ValueError):
        parse_archive(
            raw,
            checksum,
            "BTCUSDT-1h-2024-12-31.zip",
            "BTCUSDT",
            "1h",
            start,
            start + timedelta(hours=1),
            NOW,
            "x",
        )


def test_reorder_duplicate_gaps_and_conflicts():
    start = datetime(2024, 12, 31, tzinfo=UTC)
    a, b = bar(start), bar(start + timedelta(hours=2))
    ordered, report = assess([b, a, a], a.instrument_id, "1h", start, start + timedelta(hours=4))
    assert ordered == [a, b]
    assert {f.code for f in report.findings} == {"GAP", "DUPLICATE", "OUT_OF_ORDER"}
    with pytest.raises(ValueError):
        report.require_complete()
    changed = Candle.model_validate(a.model_dump() | {"open": Decimal("101")})
    with pytest.raises(ValueError, match="CONFLICTING_DUPLICATE"):
        assess([a, changed], a.instrument_id, "1h", start, start + timedelta(hours=1))


def test_rest_schema_and_explicit_unit_mismatch_quarantine():
    start = datetime(2025, 1, 1, tzinfo=UTC)
    raw = json.dumps([row(start, True)]).encode()
    bars, report = parse_rest(raw, "BTCUSDT", "1h", start, start + timedelta(hours=1), NOW, "x")
    assert not bars and report.status == "BLOCKED" and report.rejected_rows == 1
    with pytest.raises(ValueError):
        parse_rest(b"{}", "BTCUSDT", "1h", start, start + timedelta(hours=1), NOW, "x")


def test_utc_rejects_naive_and_dst_offsets():
    start = datetime(2024, 12, 31, tzinfo=UTC)
    payload = bar(start).model_dump()
    for invalid in (datetime(2024, 12, 31), "2024-11-03T01:30:00-04:00"):
        with pytest.raises(ValueError):
            Candle.model_validate(payload | {"open_at": invalid})
