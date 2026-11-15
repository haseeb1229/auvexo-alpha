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
    ObservationSpecCheck,
    observation_clock_bound_ms,
)
from auvexo_alpha.infrastructure.data_collection import (
    CLOCK_URL,
    Collector,
    exchange_info_terms,
)
from auvexo_alpha.infrastructure.data_store import DataStore
from auvexo_alpha.infrastructure.public_http import PublicHTTP, SourceError
from auvexo_alpha.infrastructure.source_registry import identity, rights
from auvexo_alpha.infrastructure.spot_parser import EPOCH, parse_rest

SPEC_URL = "https://data-api.binance.vision/api/v3/exchangeInfo?symbol="
UNAVAILABLE = frozenset(
    {
        "NETWORK",
        "STOPPED",
        "RATE_LIMIT",
        "PROVIDER_ACCESS_BLOCKED",
        "SOURCE_UNAVAILABLE",
        "PERSISTED_PROVIDER_COOLDOWN",
        "NETWORK_BUDGET",
    }
)


def _available[T](call: Callable[[], T]) -> T:
    """An expected provider outage becomes ObservationSourceUnavailable; others propagate."""
    try:
        return call()
    except SourceError as error:
        if error.code not in UNAVAILABLE:
            raise
        raise ObservationSourceUnavailable(error.code) from error


def _clock_proof(raw: bytes, sent_at: datetime, received_at: datetime) -> ObservationClockProof:
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
    return ObservationClockProof(
        source_url="https://data-api.binance.vision/api/v3/time",
        raw_json=raw_json,
        raw_hash=sha256(raw).hexdigest(),
        sent_at=sent_at,
        received_at=received_at,
        server_at=server_at,
    )


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
        clock_bound_ms: int | None = None,
    ) -> None:
        self.store = store
        self.http = http
        self.revision = revision
        self.clock = clock
        # Campaign v2 (OBV2-03): a bar whose proven clock bound exceeds the policy bound is
        # a missed bar (ADR-031 rule 5), never a fact the kernel would deny.
        self.clock_bound_ms = clock_bound_ms
        self.campaign_tag = sha256(campaign_id.encode()).hexdigest()[:16]
        self.collector = Collector(store, http, revision, enabled=True)
        # Bar end per feed whose finality/currentness could not be proven. Provider time
        # only moves forward, so one refused proof is final: the bar is never requested
        # again, never retried into the bounded request budget and never counted.
        self.missed: dict[str, datetime] = {}

    def _miss(self, feed: str, end: datetime, reason: str) -> None:
        """One durable STALE event for an unprovable bar: no fact, publication or quarantine."""
        self.missed[feed] = end
        self.collector.record(feed, "STALE", reason, utc_time(self.clock()))

    def require_ready(self, config: ObservationConfig, *, now: datetime) -> None:
        if rights("DS-02", now) != config.rights or identity("DS-02", now) != config.source:
            raise ValueError("OBSERVATION_SOURCE_OR_RIGHTS_PIN_MISMATCH")
        config.rights.require_research(now)

    def next_observation(
        self, symbol: Symbol, *, window_start: datetime, window_end: datetime
    ) -> ObservationFact | None:
        return _available(
            lambda: self.poll(symbol, window_start=window_start, window_end=window_end)
        )

    def provider_time(self) -> ObservationClockProof:
        """One provider-time proof outside any bar poll (OBV2-05 start and end guards)."""
        return _available(self._provider_time)

    def spec(self, symbol: Symbol) -> ObservationSpecCheck:
        """OBV2-04: the provider's current exchangeInfo terms for one symbol."""
        return _available(lambda: self._spec(symbol))

    def _provider_time(self) -> ObservationClockProof:
        feed = f"DS-02.obs.{self.campaign_tag}.clock"
        raw: bytes | None = None
        try:
            self.collector.preflight(utc_time(self.clock()))
            sent_at = utc_time(self.clock())
            raw = self.http.get(CLOCK_URL, 512)
            return _clock_proof(raw, sent_at, utc_time(self.clock()))
        except SourceError as error:
            self.collector.record(
                feed, "STALE", error.code, utc_time(self.clock()), cooldown=error.cooldown
            )
            raise
        except ValueError:
            self.collector.reject_input(feed, raw)
            raise

    def _spec(self, symbol: Symbol) -> ObservationSpecCheck:
        if symbol not in ("BTCUSDT", "ETHUSDT"):
            raise ValueError("OBSERVATION_SOURCE_CONFIG")
        feed = f"DS-02.obs.{self.campaign_tag}.{symbol}.spec"
        url = SPEC_URL + symbol
        raw: bytes | None = None
        try:
            now = utc_time(self.clock())
            self.collector.preflight(now)
            rights("DS-02", now).require_research(now)
            sent_at = utc_time(self.clock())
            raw = self.http.get(url, 2 * 1024 * 1024)
            received_at = utc_time(self.clock())
            # The accepted DS-02 parser retains the raw bytes; only the notional filter and
            # provider time are read beside it.
            snapshot = self.collector.parse_spec(symbol, url, raw)
            min_notional, server_ms = exchange_info_terms(raw, symbol)
            if (
                snapshot.price_tick is None
                or snapshot.quantity_step is None
                or snapshot.min_quantity is None
                or snapshot.max_quantity is None
            ):
                raise ValueError("OBSERVATION_SPEC_TERMS_MISSING")
            return ObservationSpecCheck(
                symbol=symbol,
                raw_hash=sha256(raw).hexdigest(),
                sent_at=sent_at,
                received_at=received_at,
                server_at=EPOCH + timedelta(milliseconds=server_ms),
                trade_status=snapshot.trade_status,
                price_tick=snapshot.price_tick,
                quantity_step=snapshot.quantity_step,
                min_quantity=snapshot.min_quantity,
                max_quantity=snapshot.max_quantity,
                min_notional=min_notional,
            )
        except SourceError as error:
            self.collector.record(
                feed, "STALE", error.code, utc_time(self.clock()), cooldown=error.cooldown
            )
            raise
        except (ValueError, KeyError, TypeError, IndexError, OverflowError) as error:
            self.collector.reject_input(feed, raw)
            raise ValueError("OBSERVATION_SPEC_INPUT_REJECTED") from error

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
        rights("DS-02", now).require_research(now)
        step = timedelta(minutes=1)
        # Provider-time evidence below independently proves finality. The original
        # collector is unchanged, and the original bar end remains market as_of.
        end = EPOCH + ((now - EPOCH) // step) * step
        if end < start_window:
            return None
        start = end - step
        feed = f"DS-02.obs.{self.campaign_tag}.{symbol}.1m"
        if self.missed.get(feed) == end:
            return None
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
            raw = self.http.get(CLOCK_URL, 512)
            clock_proof = _clock_proof(raw, sent_at, utc_time(self.clock()))
            server_at = clock_proof.server_at
            # The finality rule itself is unchanged. A bar it cannot prove is a missed bar,
            # not a failed run: the provider clock payload was valid, so nothing is
            # quarantined, no klines are requested and the 120 s gap rule judges the day.
            if (
                self.clock_bound_ms is not None
                and observation_clock_bound_ms(clock_proof) > self.clock_bound_ms
            ):
                self._miss(feed, end, "OBSERVATION_BAR_MISSED_CLOCK_BOUND")
                return None
            if server_at < end:
                self._miss(feed, end, "OBSERVATION_BAR_MISSED_PROVIDER_BEFORE_CLOSE")
                return None
            if server_at >= end + step:
                self._miss(feed, end, "OBSERVATION_BAR_MISSED_PROVIDER_PAST_MINUTE")
                return None
            raw = self.http.get(url, 2 * 1024 * 1024)
            received = utc_time(self.clock())
            if not start_window <= received < end_window:
                self._miss(feed, end, "OBSERVATION_BAR_MISSED_RECEIPT_OUTSIDE_WINDOW")
                return None
            rights("DS-02", received).require_research(received)
            bars, report = parse_rest(raw, symbol, "1m", start, end, received, url)
            report.require_complete()
            if len(bars) != 1 or bars[0].end_at != end:
                raise ValueError("OBSERVATION_CURRENT_BAR_REQUIRED")
            processed_at = utc_time(self.clock())
            if not received <= processed_at < end_window:
                self._miss(feed, end, "OBSERVATION_BAR_MISSED_PROCESSING_OUTSIDE_WINDOW")
                return None
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
                identity("DS-02", received),
                rights("DS-02", received),
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
