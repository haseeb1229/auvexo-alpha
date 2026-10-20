"""Synthetic feed adapter checks; no network, DB or observation credit."""

import json
from datetime import timedelta
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
