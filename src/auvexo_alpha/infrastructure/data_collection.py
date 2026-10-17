"""Small public collector with immutable receipts and restart from complete checkpoints."""

import calendar
import json
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from auvexo_alpha.domain.contracts import Product, Venue
from auvexo_alpha.domain.market_data import (
    Candle,
    DataAvailabilityWindow,
    DatasetManifest,
    IngestionEvent,
    InstrumentAlias,
    Interval,
    SpecSnapshot,
    Symbol,
    interval_seconds,
)
from auvexo_alpha.infrastructure.data_store import DataStore, sha
from auvexo_alpha.infrastructure.public_http import PublicHTTP, SourceError
from auvexo_alpha.infrastructure.source_registry import identity, rights
from auvexo_alpha.infrastructure.spot_parser import EPOCH, MAX_ARCHIVE, parse_archive, parse_rest


def archive_location(
    symbol: Symbol, interval: Interval, period: str
) -> tuple[str, str, datetime, datetime]:
    if (
        symbol not in ("BTCUSDT", "ETHUSDT")
        or interval not in ("1m", "1h")
        or not re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", period)
    ):
        raise ValueError("SOURCE_CONFIG")
    day = date.fromisoformat(period if len(period) == 10 else period + "-01")
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    days = 1 if len(period) == 10 else calendar.monthrange(day.year, day.month)[1]
    filename = f"{symbol}-{interval}-{period}.zip"
    kind = "daily" if len(period) == 10 else "monthly"
    return (
        f"https://data.binance.vision/data/spot/{kind}/klines/{symbol}/{interval}/{filename}",
        filename,
        start,
        start + timedelta(days=days),
    )


def processed(bars: list[Candle]) -> list[Candle]:
    finished = datetime.now(UTC)
    return [
        Candle.model_validate(
            bar.model_dump()
            | {
                "availability": DataAvailabilityWindow.model_validate(
                    bar.availability.model_dump()
                    | {"processed_at": finished, "available_at": finished}
                )
            }
        )
        for bar in bars
    ]


class Collector:
    def __init__(
        self, store: DataStore, http: PublicHTTP, revision: str, enabled: bool = False
    ) -> None:
        self.store, self.http, self.revision, self.enabled = store, http, revision, enabled

    def preflight(self, now: datetime) -> None:
        if not self.enabled:
            raise ValueError("COLLECTOR_DISABLED")
        self.store.check_quota(16 * 1024 * 1024)
        if self.store.cooldown(now):
            raise SourceError("PERSISTED_PROVIDER_COOLDOWN")

    def record(
        self,
        feed: str,
        state: str,
        reason: str,
        now: datetime,
        manifest: DatasetManifest | None = None,
        cooldown: int = 0,
        quarantined_source_hash: str | None = None,
    ) -> None:
        self.store.event(
            IngestionEvent.model_validate(
                dict(
                    event_id=str(uuid4()),
                    feed_key=feed,
                    observed_at=now,
                    state=state,
                    reason=reason,
                    requests=self.http.requests,
                    network_bytes=self.http.bytes,
                    dataset_version=manifest.dataset_version if manifest else None,
                    blocked_until=now + timedelta(seconds=cooldown) if cooldown else None,
                    quarantined_source_hash=quarantined_source_hash,
                )
            )
        )

    def history(self, symbol: Symbol, interval: Interval, period: str) -> DatasetManifest:
        now = datetime.now(UTC)
        self.preflight(now)
        rights("DS-01").require_research(now)
        url, filename, start, end = archive_location(symbol, interval, period)
        if end > now:
            raise ValueError("UNFINISHED_ARCHIVE")
        feed = f"DS-01.{symbol}.{interval}.{period}"
        raw: bytes | None = None
        try:
            checksum = self.http.get(url + ".CHECKSUM", 512)
            raw = self.http.get(url, MAX_ARCHIVE)
            received = datetime.now(UTC)
            bars, report = parse_archive(
                raw, checksum, filename, symbol, interval, start, end, received, url
            )
            bars = processed(bars)
            manifest = self.store.publish(
                bars,
                report,
                identity("DS-01"),
                rights("DS-01"),
                feed,
                url,
                raw,
                received,
                self.revision,
            )
            self.record(
                feed,
                "FRESH" if report.status == "PASS" else "BLOCKED",
                "HISTORY_" + report.status,
                datetime.now(UTC),
                manifest,
            )
            return manifest
        except SourceError as error:
            self.record(feed, "BLOCKED", error.code, datetime.now(UTC), cooldown=error.cooldown)
            raise
        except ValueError:
            self.reject_input(feed, raw)
            raise

    def poll(self, symbol: Symbol, interval: Interval = "1m") -> DatasetManifest | None:
        now = datetime.now(UTC)
        self.preflight(now)
        rights("DS-02").require_research(now)
        feed = f"DS-02.{symbol}.{interval}"
        step = timedelta(seconds=interval_seconds(interval))
        # Two-second publication grace; a poll is not proof of a two-second executable quote.
        end = EPOCH + ((now - EPOCH - timedelta(seconds=2)) // step) * step
        checkpoint = self.store.checkpoint(feed)
        start = checkpoint.next_open if checkpoint else end - 2 * step
        if start >= end:
            return None
        end = min(end, start + 1000 * step)
        begin_ms, end_ms = (
            (start - EPOCH) // timedelta(milliseconds=1),
            (end - EPOCH) // timedelta(milliseconds=1) - 1,
        )
        url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&startTime={begin_ms}&endTime={end_ms}&limit=1000"
        raw: bytes | None = None
        try:
            raw = self.http.get(url, 2 * 1024 * 1024)
            received = datetime.now(UTC)
            bars, report = parse_rest(raw, symbol, interval, start, end, received, url)
            bars = processed(bars)
            key = f"{feed}.{begin_ms}.{end_ms}"
            manifest = self.store.publish(
                bars,
                report,
                identity("DS-02"),
                rights("DS-02"),
                key,
                url,
                raw,
                received,
                self.revision,
                feed,
            )
            fresh = report.status == "PASS" and received - end <= 2 * step
            self.record(
                feed, "FRESH" if fresh else "STALE", "CANDLES_" + report.status, received, manifest
            )
            return manifest
        except SourceError as error:
            self.record(feed, "STALE", error.code, datetime.now(UTC), cooldown=error.cooldown)
            raise
        except ValueError:
            self.reject_input(feed, raw)
            raise

    def reject_input(self, feed: str, raw: bytes | None) -> None:
        digest = self.store.quarantine(raw) if raw is not None else None
        self.record(
            feed,
            "BLOCKED",
            "INPUT_REJECTED",
            datetime.now(UTC),
            quarantined_source_hash=digest,
        )

    def spec(self, symbol: Symbol) -> SpecSnapshot:
        now = datetime.now(UTC)
        self.preflight(now)
        rights("DS-02").require_research(now)
        url = "https://data-api.binance.vision/api/v3/exchangeInfo?symbol=" + symbol
        feed = f"DS-02.{symbol}.spec"
        raw: bytes | None = None
        try:
            raw = self.http.get(url, 2 * 1024 * 1024)
            return self.parse_spec(symbol, url, raw)
        except SourceError as error:
            self.record(feed, "BLOCKED", error.code, datetime.now(UTC), cooldown=error.cooldown)
            raise
        except (ValueError, KeyError, TypeError, IndexError) as error:
            self.reject_input(feed, raw)
            raise ValueError("SPEC_INPUT_REJECTED") from error

    def parse_spec(self, symbol: Symbol, url: str, raw: bytes) -> SpecSnapshot:
        payload = json.loads(raw)
        item = payload["symbols"][0]
        if (
            item["symbol"] != symbol
            or item["baseAsset"] != symbol[:-4]
            or item["quoteAsset"] != "USDT"
        ):
            raise ValueError("SPEC_UNIT")
        filters = {f["filterType"]: f for f in item["filters"]}
        snapshot = SpecSnapshot(
            alias=InstrumentAlias.model_validate(
                dict(
                    instrument_id="binance.spot." + symbol,
                    asset=symbol[:-4],
                    venue=Venue.BINANCE,
                    product=Product.SPOT,
                    provider_symbol=symbol,
                    quote_currency="USDT",
                    mapping_version="spot.v1",
                )
            ),
            source_id="DS-02",
            observed_at=datetime.now(UTC),
            spec_version=sha(raw),
            provenance_url=url,
            price_tick=filters["PRICE_FILTER"]["tickSize"],
            quantity_step=filters["LOT_SIZE"]["stepSize"],
            min_quantity=filters["LOT_SIZE"]["minQty"],
            max_quantity=filters["LOT_SIZE"]["maxQty"],
            contract_size=Decimal("1"),
            quantity_unit="BASE_UNIT",
            session="24x7 subject to provider outages",
            timezone="UTC",
            trade_status=item["status"],
            unknown_reason="No broker CFD facts; current spot specification only",
        )
        self.store.spec(snapshot, raw)
        return snapshot
