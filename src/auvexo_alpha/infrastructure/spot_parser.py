"""Bounded untrusted input parser. Archive units are selected by family/date, never magnitude."""

import csv
import hashlib
import io
import json
import re
import stat
import zipfile
import zlib
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from pydantic import ValidationError

from auvexo_alpha.application.data_quality import assess
from auvexo_alpha.domain.contracts import exact_decimal
from auvexo_alpha.domain.market_data import (
    Candle,
    CoverageReport,
    DataAvailabilityWindow,
    DataQualityFinding,
    Interval,
    SourceRecord,
    Symbol,
    interval_seconds,
)

MAX_ARCHIVE = 16 * 1024 * 1024
MAX_EXPANDED = 32 * 1024 * 1024
MAX_ROWS = 50_000
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
TRANSITION = date(2025, 1, 1)


def timestamp(raw: object, unit: Literal["MILLISECOND", "MICROSECOND"], now: datetime) -> datetime:
    if isinstance(raw, str) and re.fullmatch(r"[0-9]{1,18}", raw):
        raw = int(raw)
    if type(raw) is not int or raw < 0 or raw > 10**18:
        raise ValueError("TIMESTAMP_UNIT")
    try:
        result = EPOCH + timedelta(microseconds=raw * (1000 if unit == "MILLISECOND" else 1))
    except OverflowError as error:
        raise ValueError("TIMESTAMP_UNIT") from error
    if result < datetime(2017, 7, 1, tzinfo=UTC) or result > now + timedelta(days=1):
        raise ValueError("IMPLAUSIBLE_TIME")
    return result


def parse_row(
    row: list[object],
    symbol: Symbol,
    interval: Interval,
    unit: Literal["MILLISECOND", "MICROSECOND"],
    source_id: Literal["DS-01", "DS-02"],
    url: str,
    digest: str,
    received: datetime,
) -> Candle:
    if len(row) != 12:
        raise ValueError("SCHEMA")
    opened, closed = timestamp(row[0], unit, received), timestamp(row[6], unit, received)
    step = timedelta(seconds=interval_seconds(interval))
    if (opened - EPOCH) % step or closed != opened + step - timedelta(
        microseconds=1000 if unit == "MILLISECOND" else 1
    ):
        raise ValueError("TIMESTAMP_UNIT")
    if opened + step > received:
        raise ValueError("PARTIAL")
    try:
        if exact_decimal(row[5]) < 0 or exact_decimal(row[7]) < 0:
            raise ValueError("negative volume")
    except ValueError as error:
        raise ValueError("VOLUME") from error
    trades = row[8]
    if isinstance(trades, str) and re.fullmatch(r"[0-9]{1,12}", trades):
        trades = int(trades)
    return Candle.model_validate(
        dict(
            instrument_id="binance.spot." + symbol,
            symbol=symbol,
            interval=interval,
            base_currency=symbol[:-4],
            open_at=opened,
            end_at=opened + step,
            open=row[1],
            high=row[2],
            low=row[3],
            close=row[4],
            volume=row[5],
            quote_volume=row[7],
            trades=trades,
            source=SourceRecord(
                source_id=source_id,
                source_url=url,
                source_hash=digest,
                raw_open=int(str(row[0])),
                raw_close=int(str(row[6])),
                timestamp_unit=unit,
                received_at=received,
            ),
            availability=DataAvailabilityWindow(
                received_at=received,
                processed_at=received,
                available_at=received,
                historical_close_bound=opened + step,
                basis="BACKFILL_RECEIPT" if source_id == "DS-01" else "OBSERVED_RECEIPT",
            ),
        )
    )


def parse_rows(
    rows: list[list[object]],
    symbol: Symbol,
    interval: Interval,
    start: datetime,
    end: datetime,
    received: datetime,
    source_id: Literal["DS-01", "DS-02"],
    url: str,
    digest: str,
) -> tuple[list[Candle], CoverageReport]:
    unit: Literal["MILLISECOND", "MICROSECOND"] = (
        "MICROSECOND" if source_id == "DS-01" and start.date() >= TRANSITION else "MILLISECOND"
    )
    bars, findings = [], []
    if len(rows) > MAX_ROWS:
        raise ValueError("OVERSIZED_ROWS")
    for row in rows:
        try:
            bar = parse_row(row, symbol, interval, unit, source_id, url, digest, received)
            if not start <= bar.open_at < end:
                raise ValueError("SESSION")
            bars.append(bar)
        except (ValueError, ValidationError) as error:
            code = str(error)
            # Error payloads never retain arbitrary provider text or row contents.
            finding = DataQualityFinding(code="SCHEMA", detail="row rejected by strict schema")
            for candidate in (
                "PARTIAL",
                "TIMESTAMP_UNIT",
                "IMPLAUSIBLE_TIME",
                "OHLC",
                "VOLUME",
                "SESSION",
            ):
                if candidate in code:
                    finding = DataQualityFinding.model_validate(
                        dict(code=candidate, detail="row rejected")
                    )
                    break
            findings.append(finding)
    rejected = len(findings)
    grouped: dict[str, DataQualityFinding] = {}
    for finding in findings:
        prior = grouped.get(finding.code)
        grouped[finding.code] = (
            finding
            if prior is None
            else DataQualityFinding.model_validate(
                finding.model_dump() | {"count": prior.count + 1}
            )
        )
    return assess(
        bars, "binance.spot." + symbol, interval, start, end, list(grouped.values()), rejected
    )


def parse_archive(
    payload: bytes,
    checksum: bytes,
    filename: str,
    symbol: Symbol,
    interval: Interval,
    start: datetime,
    end: datetime,
    received: datetime,
    url: str,
) -> tuple[list[Candle], CoverageReport]:
    if len(payload) > MAX_ARCHIVE or len(checksum) > 512:
        raise ValueError("OVERSIZED_ARCHIVE")
    expected = re.fullmatch(rb"([0-9a-f]{64}) [ *]([^\r\n]+)\r?\n?", checksum)
    digest = hashlib.sha256(payload).hexdigest()
    if (
        expected is None
        or expected[1].decode() != digest
        or expected[2].decode("ascii") != filename
    ):
        raise ValueError("CHECKSUM")
    rows: list[list[object]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = archive.infolist()
            if len(entries) != 1:
                raise ValueError("ARCHIVE_MEMBERS")
            item = entries[0]
            if (
                item.filename != filename.removesuffix(".zip") + ".csv"
                or "/" in item.filename
                or "\\" in item.filename
                or stat.S_ISLNK(item.external_attr >> 16)
                or item.flag_bits & 1
                or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                or item.file_size > MAX_EXPANDED
                or item.file_size > max(1, item.compress_size) * 200
            ):
                raise ValueError("UNSAFE_ARCHIVE")
            with archive.open(item) as stream:
                consumed = 0
                while line := stream.readline(4097):
                    consumed += len(line)
                    if len(line) > 4096 or consumed > MAX_EXPANDED or len(rows) >= MAX_ROWS:
                        raise ValueError("OVERSIZED_ROWS")
                    rows.append(list(next(csv.reader([line.decode("ascii")], strict=True))))
    except (
        zipfile.BadZipFile,
        UnicodeError,
        csv.Error,
        EOFError,
        RuntimeError,
        zlib.error,
    ) as error:
        raise ValueError("CORRUPT_ARCHIVE") from error
    return parse_rows(rows, symbol, interval, start, end, received, "DS-01", url, digest)


def parse_rest(
    payload: bytes,
    symbol: Symbol,
    interval: Interval,
    start: datetime,
    end: datetime,
    received: datetime,
    url: str,
) -> tuple[list[Candle], CoverageReport]:
    if len(payload) > 2 * 1024 * 1024:
        raise ValueError("OVERSIZED_RESPONSE")
    raw: object = json.loads(payload)
    if (
        not isinstance(raw, list)
        or len(raw) > 1000
        or any(not isinstance(row, list) for row in raw)
    ):
        raise ValueError("SCHEMA")
    return parse_rows(
        raw,
        symbol,
        interval,
        start,
        end,
        received,
        "DS-02",
        url,
        hashlib.sha256(payload).hexdigest(),
    )
