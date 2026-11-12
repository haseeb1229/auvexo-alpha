"""Synthetic provider-clock, failure-evidence and catch-up fixtures; never qualification."""

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import Event
from urllib.parse import parse_qs, urlsplit

import pytest
from test_data_parser import archive, row

from auvexo_alpha.domain.market_data import Checkpoint, DatasetManifest
from auvexo_alpha.infrastructure import data_collection
from auvexo_alpha.infrastructure.data_collection import CLOCK_URL, MAX_CLOCK_SKEW, Collector
from auvexo_alpha.infrastructure.public_http import PublicHTTP, Response, SourceError
from auvexo_alpha.infrastructure.spot_parser import EPOCH, parse_rest

MINUTE = timedelta(minutes=1)
MILLISECOND = timedelta(milliseconds=1)
# A provider instant inside the reviewed DS-02 rights window, forty seconds into a minute.
PROVIDER_NOW = datetime(2026, 10, 21, 18, 0, 40, tzinfo=UTC)
HEAD = PROVIDER_NOW.replace(second=0)
FEED = "DS-02.BTCUSDT.1m"
LEAK = "C:\\Users\\owner\\secret.txt password=hunter2"


def server_time(at):
    return json.dumps({"serverTime": (at - EPOCH) // MILLISECOND}).encode()


class World:
    """One provider timeline. The host clock is that timeline plus a fixed offset."""

    def __init__(self, offset=timedelta(0), latency=timedelta(0), provider_now=PROVIDER_NOW):
        self.provider_now, self.offset, self.latency = provider_now, offset, latency
        self.urls = []
        self.time_body = None
        self.klines_body = None
        self.archive = None
        self.missing = set()
        self.network_failures = 0
        self.status = 200

    def local_now(self):
        return self.provider_now + self.offset

    def wait(self, seconds):
        # PublicHTTP request spacing and retry backoff consume real time on both clocks.
        self.provider_now += timedelta(seconds=seconds)
        return False

    def klines(self, begin_ms, end_ms):
        """What the provider serves: every opened bar, including the one still in progress."""
        rows, opened = [], EPOCH + begin_ms * MILLISECOND
        while opened <= EPOCH + end_ms * MILLISECOND and opened <= self.provider_now:
            if opened not in self.missing and len(rows) < 1000:
                open_ms = (opened - EPOCH) // MILLISECOND
                rows.append(
                    [
                        open_ms,
                        "67250.01000000",
                        "67260.00000000",
                        "67240.50000000",
                        "67255.12000000",
                        "12.34500000",
                        open_ms + 59_999,
                        "830123.45678900",
                        321,
                        "6.00000000",
                        "403512.10000000",
                        "0",
                    ]
                )
            opened += MINUTE
        return json.dumps(rows).encode()

    def transport(self, url, limit):
        self.urls.append(url)
        self.provider_now += self.latency / 2
        if self.network_failures:
            self.network_failures -= 1
            raise SourceError("NETWORK")
        parts = urlsplit(url)
        if parts.hostname == "data.binance.vision":
            body = self.archive[url.endswith(".CHECKSUM")]
        elif parts.path == "/api/v3/time":
            body = self.time_body if self.time_body is not None else server_time(self.provider_now)
        elif self.klines_body is not None:
            body = self.klines_body
        else:
            query = parse_qs(parts.query)
            body = self.klines(int(query["startTime"][0]), int(query["endTime"][0]))
        self.provider_now += self.latency / 2
        return Response(self.status, body, 3600)

    def klines_urls(self):
        return [url for url in self.urls if urlsplit(url).path == "/api/v3/klines"]


class MemoryStore:
    """Checkpoint semantics of the real store without PostgreSQL: only PASS advances."""

    def __init__(self):
        self.events, self.published, self.quarantined, self.checkpoints = [], [], [], {}
        self.publish_error = None
        self.checkpoint_error = None

    def check_quota(self, extra):
        assert extra >= 0

    def cooldown(self, now):
        return False

    def event(self, value):
        self.events.append(value)

    def quarantine(self, raw):
        self.quarantined.append(raw)
        return sha256(raw).hexdigest()

    def checkpoint(self, feed):
        if self.checkpoint_error is not None:
            raise self.checkpoint_error
        return self.checkpoints.get(feed)

    def behind(self, feed, next_open):
        self.checkpoints[feed] = Checkpoint(
            feed_key=feed, next_open=next_open, dataset_version="0" * 64, recorded_at=next_open
        )

    def publish(
        self, bars, coverage, source, rights, key, url, raw, received, revision, checkpoint=None
    ):
        if self.publish_error is not None:
            raise self.publish_error
        digest = sha256(raw).hexdigest()
        version = sha256((key + ":" + digest).encode()).hexdigest()
        manifest = DatasetManifest(
            dataset_version=version,
            logical_key=key,
            source=source,
            rights=rights,
            source_url=url,
            source_hash=digest,
            checksum_verified=False,
            raw_bytes=len(raw),
            raw_relative_path=f"bronze/{digest}.raw",
            parquet_hash=digest,
            parquet_bytes=1,
            relative_path=f"partitions/{coverage.instrument_id}/{version}.parquet",
            normalized_hash=digest,
            code_revision=revision,
            code_hash=digest,
            created_at=received,
            processed_at=bars[0].availability.processed_at,
            coverage=coverage,
            supersedes=None,
            changed_rows=0,
        )
        self.published.append((bars, manifest))
        if checkpoint and coverage.status == "PASS":
            self.checkpoints[checkpoint] = Checkpoint(
                feed_key=checkpoint,
                next_open=coverage.requested_end,
                dataset_version=version,
                recorded_at=received,
            )
        return manifest


def collector_for(monkeypatch, world, store=None, max_requests=128):
    class HostClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return world.local_now()

    monkeypatch.setattr(data_collection, "datetime", HostClock)
    store = store or MemoryStore()
    http = PublicHTTP(Event(), world.transport, world.wait, max_requests=max_requests)
    return Collector(store, http, "synthetic-test", True), store


def assert_refused_without_market_request(world, store, code, checkpoint):
    """A clock refusal fetched no market payload: nothing stored, moved or quarantined."""
    assert world.urls == [CLOCK_URL]
    assert store.published == [] and store.quarantined == []
    assert store.checkpoints.get(FEED) == checkpoint
    assert len(store.events) == 1
    event = store.events[0]
    assert (event.feed_key, event.state, event.reason) == (FEED, "BLOCKED", code)
    assert event.quarantined_source_hash is None and event.dataset_version is None
    assert event.reason != "INPUT_REJECTED"


def test_synchronised_host_proves_provider_time_then_publishes_closed_bars(monkeypatch):
    world = World()
    collector, store = collector_for(monkeypatch, world)
    manifest = collector.poll("BTCUSDT")
    assert world.urls[0] == CLOCK_URL and len(world.urls) == 2 and collector.http.requests == 2
    bars, published = store.published[0]
    assert published == manifest and manifest.coverage.status == "PASS"
    assert [bar.open_at for bar in bars] == [HEAD - 2 * MINUTE, HEAD - MINUTE]
    assert all(bar.end_at <= world.provider_now for bar in bars)
    assert store.checkpoints[FEED].next_open == HEAD
    assert (store.events[0].state, store.events[0].reason) == ("FRESH", "CANDLES_PASS")


def test_fast_host_cannot_store_the_in_progress_minute_as_final(monkeypatch):
    # The host runs 33 seconds fast: it believes 18:01:13 while the provider is at 18:00:40.
    world = World(offset=timedelta(seconds=33))
    collector, store = collector_for(monkeypatch, world)
    store.behind(FEED, HEAD)
    before = store.checkpoints[FEED]

    # The hazard is real: the provider would serve the 18:00 bar, stamped with its
    # full-minute close time, and the local-time guard alone accepts it as FINAL.
    begin_ms = (HEAD - EPOCH) // MILLISECOND
    served = json.loads(world.klines(begin_ms, begin_ms + 59_999))
    assert [(r[0], r[6]) for r in served] == [(begin_ms, begin_ms + 59_999)]
    fooled, report = parse_rest(
        json.dumps(served).encode(),
        "BTCUSDT",
        "1m",
        HEAD,
        HEAD + MINUTE,
        world.local_now(),
        "https://fixture.invalid",
    )
    assert report.status == "PASS" and fooled[0].finalization == "FINAL"
    assert fooled[0].end_at > world.provider_now

    with pytest.raises(ValueError, match="^PROVIDER_FINALITY_DENIED$"):
        collector.poll("BTCUSDT")
    assert_refused_without_market_request(world, store, "PROVIDER_FINALITY_DENIED", before)


def test_slow_host_like_the_measured_33_seconds_is_refused(monkeypatch):
    world = World(offset=-timedelta(seconds=33))
    collector, store = collector_for(monkeypatch, world)
    with pytest.raises(ValueError, match="^LOCAL_CLOCK_SKEW$"):
        collector.poll("BTCUSDT")
    assert_refused_without_market_request(world, store, "LOCAL_CLOCK_SKEW", None)


@pytest.mark.parametrize(
    "offset_ms,accepted", [(2000, True), (-2000, True), (2001, False), (-2001, False)]
)
def test_skew_bound_is_exactly_two_seconds_inclusive(monkeypatch, offset_ms, accepted):
    assert MAX_CLOCK_SKEW == timedelta(seconds=2)
    world = World(offset=offset_ms * MILLISECOND)
    collector, store = collector_for(monkeypatch, world)
    if accepted:
        assert collector.poll("BTCUSDT").coverage.status == "PASS"
        assert store.checkpoints[FEED].next_open == HEAD and not store.quarantined
    else:
        with pytest.raises(ValueError, match="^LOCAL_CLOCK_SKEW$"):
            collector.poll("BTCUSDT")
        assert_refused_without_market_request(world, store, "LOCAL_CLOCK_SKEW", None)


@pytest.mark.parametrize("provider_lead_ms,accepted", [(0, True), (-1, False)])
def test_finality_requires_provider_time_at_or_after_the_requested_end(
    monkeypatch, provider_lead_ms, accepted
):
    # The host reads exactly 18:01:02, so it asks for bars ending 18:01:00.
    provider_now = HEAD + MINUTE + provider_lead_ms * MILLISECOND
    world = World(offset=HEAD + MINUTE + timedelta(seconds=2) - provider_now)
    world.provider_now = provider_now
    collector, store = collector_for(monkeypatch, world)
    if accepted:
        assert collector.poll("BTCUSDT").coverage.requested_end == HEAD + MINUTE
    else:
        with pytest.raises(ValueError, match="^PROVIDER_FINALITY_DENIED$"):
            collector.poll("BTCUSDT")
        assert_refused_without_market_request(world, store, "PROVIDER_FINALITY_DENIED", None)


@pytest.mark.parametrize(
    "offset_ms,accepted", [(-1500, True), (1500, True), (2500, False), (-2500, False)]
)
def test_request_spacing_retries_and_latency_do_not_bias_the_skew_measurement(
    monkeypatch, offset_ms, accepted
):
    # PublicHTTP waits two seconds before this request and backs off after the failed
    # attempt. Timing the whole call would misread a true 2.5 s skew as acceptable and a
    # true 1.5 s skew as excessive; only the answering exchange may be measured.
    world = World(offset=offset_ms * MILLISECOND, latency=timedelta(milliseconds=400))
    collector, store = collector_for(monkeypatch, world)
    collector.http.get(CLOCK_URL, 512)
    world.urls.clear()
    world.network_failures = 1
    if accepted:
        assert collector.poll("BTCUSDT").coverage.status == "PASS"
        assert world.urls[:2] == [CLOCK_URL, CLOCK_URL] and len(world.klines_urls()) == 1
    else:
        with pytest.raises(ValueError, match="^LOCAL_CLOCK_SKEW$"):
            collector.poll("BTCUSDT")
        assert world.klines_urls() == [] and not store.published
        assert store.events[-1].reason == "LOCAL_CLOCK_SKEW"
    assert collector.http.transport == world.transport


@pytest.mark.parametrize(
    "body",
    [
        b'{"serverTime":1792605640000,"extra":1}',
        b'{"serverTime":1792605640000.0}',
        b'{"serverTime":1.79260564e12}',
        b'{"serverTime":true}',
        b'{"serverTime":"1792605640000"}',
        b'{"serverTime":null}',
        b'{"serverTime":1000000000000000000000000000000}',
        b'{"servertime":1792605640000}',
        b"{}",
        b"[1792605640000]",
        b"1792605640000",
        b"<html>busy</html>",
        b'{"serverTime":1792605640000}\xff',
        b"",
    ],
)
def test_malformed_provider_clock_is_refused_without_quarantine(monkeypatch, body):
    assert server_time(PROVIDER_NOW) == b'{"serverTime": 1792605640000}'
    world = World()
    world.time_body = body
    collector, store = collector_for(monkeypatch, world)
    with pytest.raises(ValueError, match="^PROVIDER_CLOCK_INVALID$"):
        collector.poll("BTCUSDT")
    assert_refused_without_market_request(world, store, "PROVIDER_CLOCK_INVALID", None)


def test_provider_limit_on_the_clock_request_is_a_source_event_not_input(monkeypatch):
    world = World()
    world.status = 429
    collector, store = collector_for(monkeypatch, world)
    with pytest.raises(SourceError, match="^RATE_LIMIT$"):
        collector.poll("BTCUSDT")
    event = store.events[0]
    assert (event.state, event.reason) == ("STALE", "RATE_LIMIT")
    assert event.blocked_until == world.local_now() + timedelta(seconds=3600)
    assert world.urls == [CLOCK_URL] and not store.quarantined and not store.published


@pytest.mark.parametrize(
    "body,code",
    [
        (b"<html>busy</html>", "MALFORMED_JSON"),
        (b'{"code":-1003}', "SCHEMA"),
        (b"[]", "NO_ACCEPTED_ROWS"),
        (b'[["not","a","kline"]]', "NO_ACCEPTED_ROWS"),
    ],
)
def test_only_rejected_provider_bytes_are_quarantined_as_input(monkeypatch, body, code):
    world = World()
    world.klines_body = body
    collector, store = collector_for(monkeypatch, world)
    with pytest.raises(ValueError, match=f"^{code}$"):
        collector.poll("BTCUSDT")
    assert store.quarantined == [body] and not store.published
    event = store.events[0]
    assert (event.state, event.reason) == ("BLOCKED", "INPUT_REJECTED")
    assert event.quarantined_source_hash == sha256(body).hexdigest()
    assert FEED not in store.checkpoints


@pytest.mark.parametrize(
    "message,recorded",
    [
        ("QUOTA", "QUOTA"),
        ("COVERAGE_MISMATCH", "COVERAGE_MISMATCH"),
        ("RAW_SOURCE_MISMATCH", "RAW_SOURCE_MISMATCH"),
        (LEAK, "UNCLASSIFIED"),
    ],
)
def test_local_publication_failures_keep_their_code_and_quarantine_nothing(
    monkeypatch, message, recorded
):
    world = World()
    collector, store = collector_for(monkeypatch, world)
    store.publish_error = ValueError(message)
    with pytest.raises(ValueError) as failure:
        collector.poll("BTCUSDT")
    assert failure.value is store.publish_error
    assert store.quarantined == [] and len(world.klines_urls()) == 1
    event = store.events[0]
    assert (event.state, event.reason, event.quarantined_source_hash) == ("BLOCKED", recorded, None)
    assert "hunter2" not in event.model_dump_json()


def test_corrupt_prior_artifact_is_recorded_under_its_own_code_before_any_request(monkeypatch):
    world = World()
    collector, store = collector_for(monkeypatch, world)
    store.checkpoint_error = ValueError("MANIFEST_FILE_MISMATCH")
    with pytest.raises(ValueError, match="^MANIFEST_FILE_MISMATCH$"):
        collector.poll("BTCUSDT")
    assert world.urls == [] and store.quarantined == []
    assert (store.events[0].state, store.events[0].reason) == ("BLOCKED", "MANIFEST_FILE_MISMATCH")


@pytest.mark.parametrize("fault", ["checksum", "quota"])
def test_history_separates_rejected_archive_bytes_from_local_failures(monkeypatch, fault):
    day = datetime(2024, 12, 31, tzinfo=UTC)
    raw, checksum = archive([row(day + timedelta(hours=hour)) for hour in range(24)])
    world = World()
    world.archive = (raw, b"" if fault == "checksum" else checksum)
    collector, store = collector_for(monkeypatch, world)
    store.publish_error = ValueError("QUOTA") if fault == "quota" else None
    feed = "DS-01.BTCUSDT.1h.2024-12-31"
    with pytest.raises(ValueError, match="^CHECKSUM$" if fault == "checksum" else "^QUOTA$"):
        collector.history("BTCUSDT", "1h", "2024-12-31")
    event = store.events[0]
    if fault == "checksum":
        assert store.quarantined == [raw]
        assert (event.feed_key, event.state, event.reason) == (feed, "BLOCKED", "INPUT_REJECTED")
        assert event.quarantined_source_hash == sha256(raw).hexdigest()
    else:
        assert store.quarantined == []
        assert (event.feed_key, event.state, event.reason) == (feed, "BLOCKED", "QUOTA")
        assert event.quarantined_source_hash is None
    assert not store.published


def test_history_still_publishes_a_verified_archive(monkeypatch):
    day = datetime(2024, 12, 31, tzinfo=UTC)
    raw, checksum = archive([row(day + timedelta(hours=hour)) for hour in range(24)])
    world = World()
    world.archive = (raw, checksum)
    collector, store = collector_for(monkeypatch, world)
    manifest = collector.history("BTCUSDT", "1h", "2024-12-31")
    assert manifest.coverage.status == "PASS" and manifest.coverage.observed_rows == 24
    assert (store.events[0].state, store.events[0].reason) == ("FRESH", "HISTORY_PASS")
    assert CLOCK_URL not in world.urls


def no_stop():
    return None


def test_catch_up_repeats_capped_polls_until_the_checkpoint_reaches_the_head(monkeypatch):
    world = World()
    collector, store = collector_for(monkeypatch, world)
    store.behind(FEED, HEAD - 2500 * MINUTE)
    assert collector.catch_up("BTCUSDT", no_stop) == "CAUGHT_UP"
    assert [m.coverage.observed_rows for _, m in store.published] == [1000, 1000, 500]
    assert [e.state for e in store.events] == ["STALE", "STALE", "FRESH"]
    assert store.checkpoints[FEED].next_open == HEAD
    assert world.local_now() - store.checkpoints[FEED].next_open <= 2 * MINUTE
    # Every backlog poll still proves provider time first.
    assert world.urls[0::2] == [CLOCK_URL] * 3 and len(world.klines_urls()) == 3


def test_catch_up_with_nothing_owed_makes_no_request(monkeypatch):
    world = World()
    collector, store = collector_for(monkeypatch, world)
    store.behind(FEED, HEAD)
    assert collector.catch_up("BTCUSDT", no_stop) == "CAUGHT_UP"
    assert world.urls == [] and store.events == []


def test_catch_up_stops_at_the_deadline_without_another_poll(monkeypatch):
    world = World()
    collector, store = collector_for(monkeypatch, world)
    store.behind(FEED, HEAD - 2500 * MINUTE)
    answers = iter([None, None, "DEADLINE"])
    assert collector.catch_up("BTCUSDT", lambda: next(answers)) == "DEADLINE"
    assert len(store.published) == 2
    assert store.checkpoints[FEED].next_open == HEAD - 500 * MINUTE


def test_catch_up_stops_before_exhausting_the_request_budget(monkeypatch):
    world = World()
    collector, store = collector_for(monkeypatch, world, max_requests=9)
    store.behind(FEED, HEAD - 2500 * MINUTE)
    # Two polls use four requests; a third could need six attempts and nine are allowed.
    assert collector.catch_up("BTCUSDT", no_stop) == "NETWORK_BUDGET"
    assert collector.http.requests == 4 and len(store.published) == 2
    assert all(event.reason == "CANDLES_PASS" for event in store.events)


def test_catch_up_does_not_loop_on_a_provider_gap(monkeypatch):
    world = World()
    collector, store = collector_for(monkeypatch, world)
    start = HEAD - 2500 * MINUTE
    store.behind(FEED, start)
    world.missing = {start + 5 * MINUTE}
    assert collector.catch_up("BTCUSDT", no_stop) == "CHECKPOINT_NOT_ADVANCING"
    assert [m.coverage.status for _, m in store.published] == ["DEGRADED"]
    assert store.checkpoints[FEED].next_open == start
