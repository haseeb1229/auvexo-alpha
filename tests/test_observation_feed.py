"""Synthetic feed adapter checks; no network, DB or observation credit."""

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import Event
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from observation_fixtures import BEGIN, END, changed, fact_for

from auvexo_alpha.infrastructure.observation_feed import ObservationFeed
from auvexo_alpha.infrastructure.public_http import PublicHTTP, Response


class MemorySource:
    def __init__(self, checkpoint=None):
        self.saved_checkpoint = checkpoint
        self.keys = []
        self.events = []
        self.published = []
        self.verified = []
        self.quarantined = []

    def check_quota(self, extra):
        assert extra >= 0

    def cooldown(self, now):
        return False

    def event(self, value):
        self.events.append(value)

    def checkpoint(self, key):
        self.keys.append(key)
        return self.saved_checkpoint

    def publish(
        self, bars, coverage, source, rights, key, url, raw, received, revision, checkpoint
    ):
        template = fact_for(bars[0].symbol, 10).manifest
        manifest = changed(
            template,
            source=source,
            rights=rights,
            logical_key=key,
            source_url=url,
            source_hash=sha256(raw).hexdigest(),
            raw_bytes=len(raw),
            normalized_hash=sha256(bars[0].canonical_bytes()).hexdigest(),
            created_at=received,
            processed_at=bars[0].availability.processed_at,
            coverage=coverage,
            code_revision=revision,
        )
        self.published.append((bars, manifest, checkpoint))
        self.saved_checkpoint = SimpleNamespace(next_open=coverage.requested_end)
        return manifest

    def verify(self, manifest):
        self.verified.append(manifest)

    def quarantine(self, raw):
        self.quarantined.append(raw)
        return sha256(raw).hexdigest()


def feed_fixture(*, checkpoint=None, now=None, raw_override=None):
    now = now or BEGIN + timedelta(minutes=10, seconds=3)
    store, urls = MemorySource(checkpoint), []

    def transport(url, limit):
        urls.append(url)
        if urlsplit(url).path == "/api/v3/time":
            epoch = BEGIN.replace(year=1970, month=1, day=1, hour=0)
            server_ms = int((now - epoch).total_seconds() * 1000)
            return Response(200, json.dumps({"serverTime": server_ms}).encode())
        query = parse_qs(urlsplit(url).query)
        opened = int(query["startTime"][0])
        ended = int(query["endTime"][0])
        row = [opened, "50000", "50000", "50000", "50000", "1", ended, "50000", 1, "1", "1", "0"]
        return Response(
            200, raw_override if raw_override is not None else json.dumps([row]).encode()
        )

    http = PublicHTTP(Event(), transport=transport, wait=lambda _: False)
    return (
        ObservationFeed(store, http, "1" * 40, "synthetic.noncounting", clock=lambda: now),
        store,
        urls,
    )


def test_observation_feed_requests_only_current_minute_despite_old_checkpoint():
    feed, store, urls = feed_fixture(
        checkpoint=SimpleNamespace(next_open=BEGIN - timedelta(days=50))
    )
    fact = feed.poll("BTCUSDT", window_start=BEGIN, window_end=END)
    assert fact.candle.end_at == BEGIN + timedelta(minutes=10)
    assert fact.candle.open_at == BEGIN + timedelta(minutes=9)
    assert fact.candle.availability.original_first_seen_at == fact.candle.source.received_at
    assert fact.candle.availability.available_at == fact.candle.source.received_at
    assert fact.candle.end_at < fact.candle.availability.available_at
    assert len(urls) == 2 and all("data-api.binance.vision" in url for url in urls)
    assert store.keys[0].startswith("DS-02.obs.")
    assert store.keys[0] != "DS-02.BTCUSDT.1m"
    assert any(event.reason == "OBSERVATION_NO_BACKFILL" for event in store.events)
    assert store.verified == [fact.manifest]
    assert feed.poll("BTCUSDT", window_start=BEGIN, window_end=END) is None
    assert len(urls) == 2


@pytest.mark.parametrize("symbol", ("XAUUSD", "BTCUSD", "ETHBTC"))
def test_observation_feed_wrong_symbol_never_requests(symbol):
    feed, _, urls = feed_fixture()
    with pytest.raises(ValueError, match="SOURCE_CONFIG"):
        feed.poll(symbol, window_start=BEGIN, window_end=END)
    assert urls == []


@pytest.mark.parametrize("time", (BEGIN - timedelta(seconds=1), END, END + timedelta(days=1)))
def test_observation_feed_outside_window_no_request(time):
    feed, _, urls = feed_fixture(now=time)
    if time < BEGIN:
        with pytest.raises(ValueError, match="WINDOW_NOT_OPEN"):
            feed.poll("BTCUSDT", window_start=BEGIN, window_end=END)
    else:
        assert feed.poll("BTCUSDT", window_start=BEGIN, window_end=END) is None
    assert urls == []


def test_observation_feed_rejects_empty_or_historical_payload():
    feed, store, _ = feed_fixture(raw_override=b"[]")
    with pytest.raises(ValueError):
        feed.poll("BTCUSDT", window_start=BEGIN, window_end=END)
    assert not store.published
    assert store.events[-1].reason == "INPUT_REJECTED"


@pytest.mark.parametrize("code", ("NETWORK", "RATE_LIMIT", "PROVIDER_ACCESS_BLOCKED", "STOPPED"))
def test_feed_port_translates_only_expected_provider_failures(monkeypatch, code):
    from auvexo_alpha.application.observation_ports import ObservationSourceUnavailable
    from auvexo_alpha.infrastructure.public_http import SourceError

    feed, _, _ = feed_fixture()
    error = SourceError(code)

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(feed, "poll", fail)
    with pytest.raises(ObservationSourceUnavailable) as caught:
        feed.next_observation("BTCUSDT", window_start=BEGIN, window_end=END)
    assert caught.value.code == code and caught.value.__cause__ is error


@pytest.mark.parametrize("kind", ("config", "redirect", "identity", "hash", "programmer"))
def test_feed_port_does_not_swallow_security_corruption_or_unexpected_errors(monkeypatch, kind):
    from auvexo_alpha.infrastructure.paper_identity import PaperIdentityError
    from auvexo_alpha.infrastructure.public_http import SourceError

    error = {
        "config": SourceError("SOURCE_CONFIG"),
        "redirect": SourceError("REDIRECT_BLOCKED"),
        "identity": PaperIdentityError("IDENTITY_DENIED"),
        "hash": ValueError("HASH_CORRUPT"),
        "programmer": TypeError("PROGRAMMER_ERROR"),
    }[kind]
    feed, _, _ = feed_fixture()

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(feed, "poll", fail)
    with pytest.raises(type(error)) as caught:
        feed.next_observation("BTCUSDT", window_start=BEGIN, window_end=END)
    assert caught.value is error


def at(hour, minute, second, microsecond=0):
    return datetime(2026, 10, 21, hour, minute, second, microsecond, tzinfo=UTC)


class SkewedProvider:
    """Fake HTTP transport and an injected host clock that are set independently.

    `ticks` scripts successive host clock readings (the last one repeats); `provider` is
    the time the fake `/api/v3/time` endpoint reports. No real clock or network is used.
    """

    def __init__(self, *, clock_body=None):
        self.ticks, self.provider, self.clock_body = [], None, clock_body
        self.store, self.paths = MemorySource(), []
        http = PublicHTTP(Event(), transport=self.transport, wait=lambda _: False)
        self.feed = ObservationFeed(
            self.store, http, "1" * 40, "synthetic.noncounting", clock=self.clock
        )

    def clock(self):
        return self.ticks.pop(0) if len(self.ticks) > 1 else self.ticks[0]

    def transport(self, url, limit):
        self.paths.append(urlsplit(url).path)
        if urlsplit(url).path == "/api/v3/time":
            if self.clock_body is not None:
                return Response(200, self.clock_body)
            server_ms = (self.provider - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(
                milliseconds=1
            )
            return Response(200, json.dumps({"serverTime": server_ms}).encode())
        query = parse_qs(urlsplit(url).query)
        opened, ended = int(query["startTime"][0]), int(query["endTime"][0])
        row = [opened, "50000", "50000", "50000", "50000", "1", ended, "50000", 1, "1", "1", "0"]
        return Response(200, json.dumps([row]).encode())

    def poll(self, host, provider):
        self.ticks, self.provider = list(host), provider
        return self.feed.next_observation("BTCUSDT", window_start=BEGIN, window_end=END)


def test_host_33_seconds_slow_late_poll_is_a_missed_bar_and_the_run_continues():
    source = SkewedProvider()
    # Host second 10 is provider second 43 of the same minute: final and current.
    fact = source.poll([at(16, 10, 10)], at(16, 10, 43))
    assert fact.candle.end_at == at(16, 10, 0) and fact.clock.server_at == at(16, 10, 43)
    assert source.paths == ["/api/v3/time", "/api/v3/klines"]
    # Host 16:11:40 is provider 16:12:13: the provider is already in the next minute.
    assert source.poll([at(16, 11, 40)], at(16, 12, 13)) is None
    assert source.paths == ["/api/v3/time", "/api/v3/klines", "/api/v3/time"]
    missed = source.store.events[-1]
    assert (missed.state, missed.reason) == ("STALE", "OBSERVATION_BAR_MISSED_PROVIDER_PAST_MINUTE")
    assert missed.feed_key.startswith("DS-02.obs.") and missed.observed_at == at(16, 11, 40)
    assert missed.dataset_version is None and missed.quarantined_source_hash is None
    assert len(source.store.published) == 1 and source.store.quarantined == []
    # The refused bar is never probed again and leaves no second event.
    assert source.poll([at(16, 11, 41)], at(16, 12, 14)) is None
    assert len(source.paths) == 3 and source.store.events[-1] is missed
    # The next host minute is provable again: only the one bar was missed.
    later = source.poll([at(16, 12, 5)], at(16, 12, 38))
    assert later.candle.end_at == at(16, 12, 0)
    assert [bars[0].end_at for bars, _, _ in source.store.published] == [
        at(16, 10, 0),
        at(16, 12, 0),
    ]
    assert [event.reason for event in source.store.events] == [
        "OBSERVATION_CURRENT_BAR",
        "OBSERVATION_BAR_MISSED_PROVIDER_PAST_MINUTE",
        "OBSERVATION_NO_BACKFILL",
        "OBSERVATION_CURRENT_BAR",
    ]
    assert source.store.quarantined == []


def test_first_poll_at_host_second_40_with_33_second_slow_host_is_missed_not_raised():
    source = SkewedProvider()
    assert source.poll([at(16, 10, 40)], at(16, 11, 13)) is None
    assert source.paths == ["/api/v3/time"]
    assert [(e.state, e.reason) for e in source.store.events] == [
        ("STALE", "OBSERVATION_BAR_MISSED_PROVIDER_PAST_MINUTE")
    ]
    assert source.store.published == [] and source.store.quarantined == []


@pytest.mark.parametrize(
    "provider,accepted",
    (
        (at(16, 9, 59, 999000), False),
        (at(16, 10, 0), True),
        (at(16, 10, 59, 999000), True),
        (at(16, 11, 0), False),
    ),
)
def test_provider_finality_rule_is_not_widened_at_its_exact_boundaries(provider, accepted):
    source = SkewedProvider()
    fact = source.poll([at(16, 10, 3)], provider)
    assert (fact is not None) is accepted
    assert len(source.store.published) == (1 if accepted else 0)
    assert ("/api/v3/klines" in source.paths) is accepted


def test_host_clock_ahead_of_provider_is_a_missed_bar_without_a_klines_request():
    source = SkewedProvider()
    # Host 16:10:03 while the provider is still at 16:09:58: that minute is not final.
    assert source.poll([at(16, 10, 3)], at(16, 9, 58)) is None
    assert source.paths == ["/api/v3/time"]
    assert [(e.state, e.reason) for e in source.store.events] == [
        ("STALE", "OBSERVATION_BAR_MISSED_PROVIDER_BEFORE_CLOSE")
    ]
    assert source.store.published == [] and source.store.quarantined == []


@pytest.mark.parametrize(
    "ticks,reason",
    (
        (
            # poll, clock sent, clock received, then klines received exactly at the window end
            [at(16, 59, 58), at(16, 59, 58), at(16, 59, 59), at(17, 0, 0)],
            "OBSERVATION_BAR_MISSED_RECEIPT_OUTSIDE_WINDOW",
        ),
        (
            # klines received inside the window, processing finished after it closed
            [
                at(16, 59, 58),
                at(16, 59, 58),
                at(16, 59, 59),
                at(16, 59, 59, 500000),
                at(17, 0, 0, 1),
            ],
            "OBSERVATION_BAR_MISSED_PROCESSING_OUTSIDE_WINDOW",
        ),
    ),
)
def test_receipt_or_processing_outside_window_is_missed_and_valid_payload_not_quarantined(
    ticks, reason
):
    source = SkewedProvider()
    assert source.poll(ticks, at(16, 59, 59)) is None
    assert source.paths == ["/api/v3/time", "/api/v3/klines"]
    assert [(e.state, e.reason) for e in source.store.events] == [("STALE", reason)]
    assert source.store.published == [] and source.store.quarantined == []


def test_invalid_provider_clock_payload_is_still_rejected_and_quarantined():
    source = SkewedProvider(clock_body=b'{"serverTime":"1792685410000"}')
    with pytest.raises(ValueError, match="OBSERVATION_PROVIDER_CLOCK_INVALID"):
        source.poll([at(16, 10, 10)], at(16, 10, 43))
    assert source.paths == ["/api/v3/time"]
    assert source.store.events[-1].reason == "INPUT_REJECTED"
    assert source.store.quarantined == [b'{"serverTime":"1792685410000"}']
    assert source.store.published == []
