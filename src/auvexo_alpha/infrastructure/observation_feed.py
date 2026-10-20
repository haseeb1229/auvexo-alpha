"""Current-only DS-02 observation polling using the accepted market-data stack."""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

from auvexo_alpha.application.observation_ports import ObservationSourceUnavailable
from auvexo_alpha.domain.contracts import utc_time
from auvexo_alpha.domain.market_data import Candle, DataAvailabilityWindow, Symbol
from auvexo_alpha.domain.observation import (
    ObservationClockProof,
    ObservationConfig,
    ObservationFact,
)
from auvexo_alpha.infrastructure.data_collection import Collector
from auvexo_alpha.infrastructure.data_store import DataStore
from auvexo_alpha.infrastructure.public_http import PublicHTTP, SourceError
from auvexo_alpha.infrastructure.source_registry import identity, rights
from auvexo_alpha.infrastructure.spot_parser import EPOCH, parse_rest


class ObservationFeed:
    """A separate checkpoint never supplies a historical request start or date credit."""

    def __init__(
        self,
        store: DataStore,
        http: PublicHTTP,
        revision: str,
        campaign_id: str,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store = store
        self.http = http
        self.revision = revision
        self.clock = clock
        self.campaign_tag = sha256(campaign_id.encode()).hexdigest()[:16]
        self.collector = Collector(store, http, revision, enabled=True)

    def require_ready(self, config: ObservationConfig, *, now: datetime) -> None:
        if rights("DS-02") != config.rights or identity("DS-02") != config.source:
            raise ValueError("OBSERVATION_SOURCE_OR_RIGHTS_PIN_MISMATCH")
        config.rights.require_research(now)

    def next_observation(
        self, symbol: Symbol, *, window_start: datetime, window_end: datetime
    ) -> ObservationFact | None:
        try:
            return self.poll(symbol, window_start=window_start, window_end=window_end)
        except SourceError as error:
            if error.code not in {
                "NETWORK",
                "STOPPED",
                "RATE_LIMIT",
                "PROVIDER_ACCESS_BLOCKED",
                "SOURCE_UNAVAILABLE",
                "PERSISTED_PROVIDER_COOLDOWN",
                "NETWORK_BUDGET",
            }:
                raise
            raise ObservationSourceUnavailable(error.code) from error

    def poll(
        self, symbol: Symbol, *, window_start: datetime, window_end: datetime
    ) -> ObservationFact | None:
        now, start_window, end_window = map(utc_time, (self.clock(), window_start, window_end))
        if symbol not in ("BTCUSDT", "ETHUSDT") or end_window <= start_window:
            raise ValueError("OBSERVATION_SOURCE_CONFIG")
        if now < start_window:
            raise ValueError("OBSERVATION_WINDOW_NOT_OPEN")
        if now >= end_window:
            return None
        self.collector.preflight(now)
        rights("DS-02").require_research(now)
        step = timedelta(minutes=1)
        # Provider-time evidence below independently proves finality. The original
        # collector is unchanged, and the original bar end remains market as_of.
        end = EPOCH + ((now - EPOCH) // step) * step
        if end < start_window:
            return None
        start = end - step
        feed = f"DS-02.obs.{self.campaign_tag}.{symbol}.1m"
        checkpoint = self.store.checkpoint(feed)
        if checkpoint is not None and checkpoint.next_open >= end:
            return None
        if checkpoint is not None and checkpoint.next_open < start:
            self.collector.record(feed, "STALE", "OBSERVATION_NO_BACKFILL", now)
        begin_ms = (start - EPOCH) // timedelta(milliseconds=1)
        end_ms = (end - EPOCH) // timedelta(milliseconds=1) - 1
        url = (
            "https://data-api.binance.vision/api/v3/klines?symbol="
            f"{symbol}&interval=1m&startTime={begin_ms}&endTime={end_ms}&limit=1000"
        )
        raw: bytes | None = None
        try:
            sent_at = utc_time(self.clock())
            raw = self.http.get("https://data-api.binance.vision/api/v3/time", 512)
            clock_received = utc_time(self.clock())
            raw_json = raw.decode("ascii")
            payload = json.loads(raw_json)
            if (
                not isinstance(payload, dict)
                or set(payload) != {"serverTime"}
                or type(payload["serverTime"]) is not int
            ):
                raise ValueError("OBSERVATION_PROVIDER_CLOCK_INVALID")
            try:
                server_at = EPOCH + timedelta(milliseconds=payload["serverTime"])
            except (OverflowError, ValueError) as error:
                raise ValueError("OBSERVATION_PROVIDER_CLOCK_INVALID") from error
            clock_proof = ObservationClockProof(
                source_url="https://data-api.binance.vision/api/v3/time",
                raw_json=raw_json,
                raw_hash=sha256(raw).hexdigest(),
                sent_at=sent_at,
                received_at=clock_received,
                server_at=server_at,
            )
            if not end <= server_at < end + step:
                raise ValueError("OBSERVATION_PROVIDER_FINALITY_OR_CURRENT_MINUTE_DENIED")
            raw = self.http.get(url, 2 * 1024 * 1024)
            received = utc_time(self.clock())
            if not start_window <= received < end_window:
                raise ValueError("OBSERVATION_RECEIPT_OUTSIDE_WINDOW")
            rights("DS-02").require_research(received)
            bars, report = parse_rest(raw, symbol, "1m", start, end, received, url)
            report.require_complete()
            if len(bars) != 1 or bars[0].end_at != end:
                raise ValueError("OBSERVATION_CURRENT_BAR_REQUIRED")
            processed_at = utc_time(self.clock())
            if not received <= processed_at < end_window:
                raise ValueError("OBSERVATION_PROCESSING_OUTSIDE_WINDOW")
            bars = [
                Candle.model_validate(
                    bar.model_dump()
                    | {
                        "availability": DataAvailabilityWindow.model_validate(
                            bar.availability.model_dump()
                            | {
                                "original_first_seen_at": received,
                                "processed_at": processed_at,
                                "available_at": processed_at,
                            }
                        )
                    }
                )
                for bar in bars
            ]
            manifest = self.store.publish(
                bars,
                report,
                identity("DS-02"),
                rights("DS-02"),
                f"{feed}.{begin_ms}.{end_ms}",
                url,
                raw,
                received,
                self.revision,
                feed,
            )
            self.store.verify(manifest)
            self.collector.record(feed, "FRESH", "OBSERVATION_CURRENT_BAR", received, manifest)
            return ObservationFact(
                observation_id=uuid4(), candle=bars[0], manifest=manifest, clock=clock_proof
            )
        except SourceError as error:
            self.collector.record(
                feed, "STALE", error.code, utc_time(self.clock()), cooldown=error.cooldown
            )
            raise
        except ValueError:
            self.collector.reject_input(feed, raw)
            raise
