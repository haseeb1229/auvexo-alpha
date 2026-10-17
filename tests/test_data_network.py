from threading import Event

import pytest

from auvexo_alpha.infrastructure.public_http import PublicHTTP, Response, SourceError, allowed_url

URL = "https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1m"


@pytest.mark.parametrize(
    "url",
    [
        "http://data-api.binance.vision/api/v3/klines",
        "https://evil.example/api/v3/klines",
        "https://data-api.binance.vision/api/v3/order",
        "https://" + "synthetic-user:synthetic-password@" + "data-api.binance.vision/api/v3/klines",
        "https://data-api.binance.vision:443/api/v3/klines",
        "https://data.binance.vision/data/spot/../../secret",
        URL + "#fragment",
    ],
)
def test_source_config_injection(url):
    assert not allowed_url(url)
    with pytest.raises(SourceError):
        PublicHTTP(Event(), wait=lambda _: False).get(url, 100)


@pytest.mark.parametrize("status", [429, 418, 403, 451, 404])
def test_no_retry_on_provider_limits_or_access_blocks(status):
    calls = []

    def transport(url, limit):
        calls.append(url)
        return Response(status, b"", 3600)

    http = PublicHTTP(Event(), transport, lambda _: False)
    with pytest.raises(SourceError) as error:
        http.get(URL, 100)
    assert len(calls) == 1
    if status in (429, 418):
        assert error.value.cooldown == 3600


def test_bounded_backoff_network_timeout_and_recovery():
    calls, waits = [], []

    def transport(url, limit):
        calls.append(url)
        if len(calls) == 1:
            raise SourceError("NETWORK")
        if len(calls) == 2:
            return Response(503, b"")
        return Response(200, b"[]")

    http = PublicHTTP(Event(), transport, lambda seconds: waits.append(seconds) or False)
    assert http.get(URL, 100) == b"[]" and len(calls) == 3
    assert sum(waits) >= 7


def test_persistent_failure_request_byte_budget_and_cancel():
    http = PublicHTTP(Event(), lambda url, limit: Response(500, b""), lambda _: False)
    with pytest.raises(SourceError):
        http.get(URL, 10)
    assert http.requests == 3
    cancelled = Event()
    cancelled.set()
    with pytest.raises(SourceError, match="STOPPED"):
        PublicHTTP(cancelled).get(URL, 10)
    http = PublicHTTP(
        Event(), lambda url, limit: Response(200, b"123"), lambda _: False, max_requests=1
    )
    assert http.get(URL, 10) == b"123"
    with pytest.raises(SourceError, match="BUDGET"):
        http.get(URL, 10)
    with pytest.raises(SourceError, match="BUDGET"):
        PublicHTTP(Event(), lambda url, limit: Response(200, b"123"), lambda _: False).get(URL, 2)


@pytest.mark.parametrize(
    "suffix", ["&apiKey=secret", "&symbol=ETHUSDT", "&limit=1001", "&limit=-1", "&startTime=NaN"]
)
def test_unrecognized_query_parameters_refused(suffix):
    assert not allowed_url(URL + suffix)
