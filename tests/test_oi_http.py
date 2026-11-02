"""Network-free transport proofs. All I/O endpoints and worker processes are synthetic."""

import base64
import json
import subprocess
from datetime import UTC, datetime, timedelta
from threading import Event, Thread

import pytest
from hypothesis import given
from hypothesis import strategies as st

from auvexo_alpha.infrastructure import oi_http
from auvexo_alpha.infrastructure.oi_http import (
    OIHTTP,
    OIBudgetState,
    OIResponse,
    allowed_oi_url,
    request_oi,
)
from auvexo_alpha.infrastructure.public_http import NoRedirect, SourceError, allowed_url

NOW = datetime(2026, 10, 27, 12, tzinfo=UTC)
URL = "https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT"


class Clock:
    def __init__(self):
        self.seconds = 0.0
        self.delays = []

    def now(self):
        return NOW + timedelta(seconds=self.seconds)

    def monotonic(self):
        return self.seconds

    def wait(self, seconds):
        self.delays.append(seconds)
        self.seconds += seconds
        return False


def http(transport, *, state=None, persist=None, clock=None, cancel=None):
    clock = clock or Clock()
    client = OIHTTP(
        cancel or Event(),
        state=state or OIBudgetState(hour_started_at=NOW, day_started_at=NOW.replace(hour=0)),
        persist=persist or (lambda _: None),
        transport=transport,
        now=clock.now,
        monotonic=clock.monotonic,
        wait=clock.wait,
    )
    return client, clock


@pytest.mark.parametrize(
    "url",
    [
        URL.replace("https:", "http:"),
        URL.replace("fapi.binance.com", "testnet.binancefuture.com"),
        URL.replace("fapi.binance.com", "fapi.binance.com.evil.invalid"),
        URL.replace("fapi.binance.com", "synthetic:credential@fapi.binance.com"),
        URL.replace("fapi.binance.com", "fapi.binance.com:443"),
        URL.replace("openInterest", "openInterestHist"),
        URL.replace("openInterest", "order"),
        URL + "&symbol=ETHUSDT",
        URL + "&apiKey=synthetic",
        URL + "#fragment",
        URL.replace("BTCUSDT", "btcusdt"),
        URL.replace("BTCUSDT", "%42TCUSDT"),
        URL.replace("BTCUSDT", "XAUUSDT"),
        URL + "&",
        URL.replace("?", "/?"),
    ],
)
def test_exact_url_policy_blocks_expansion(url):
    assert not allowed_oi_url(url)
    with pytest.raises(SourceError, match="SOURCE_CONFIG"):
        request_oi(url, 4096, 10)


@given(st.text(max_size=64))
def test_exact_url_fuzz_is_only_two_literal_strings(candidate):
    assert allowed_oi_url(candidate) == (candidate in (URL, URL.replace("BTC", "ETH")))


def test_spot_default_allowlist_and_typed_constructor_unchanged():
    assert allowed_oi_url(URL) and allowed_oi_url(URL.replace("BTC", "ETH"))
    assert not allowed_url(URL)
    assert allowed_url("https://data-api.binance.vision/api/v3/time")
    with pytest.raises(TypeError):
        OIHTTP(
            Event(),
            state=OIBudgetState(hour_started_at=NOW, day_started_at=NOW.replace(hour=0)),
            persist=lambda _: None,
            headers={"Authorization": "synthetic"},
        )


@pytest.mark.parametrize(
    "status,code",
    [
        (429, "RATE_LIMIT"),
        (418, "RATE_LIMIT"),
        (403, "ACCESS_BLOCKED"),
        (451, "ACCESS_BLOCKED"),
        (404, "UNAVAILABLE"),
        (302, "UNAVAILABLE"),
    ],
)
def test_limit_and_access_failures_never_retry(status, code):
    calls, states = [], []
    client, clock = http(
        lambda *args: calls.append(args) or OIResponse(status, b"", 3600), persist=states.append
    )
    with pytest.raises(SourceError, match=code):
        client.fetch("BTCUSDT")
    assert len(calls) == 1
    assert states[0].hour_attempts == 1
    if status in (418, 429, 403, 451):
        assert states[-1].blocked_until > clock.now()
        restarted, _ = http(lambda *_: pytest.fail("cooldown bypass"), state=states[-1])
        with pytest.raises(SourceError, match="COOLDOWN"):
            restarted.fetch("ETHUSDT")


def test_bounded_retry_global_spacing_pre_request_persistence_and_two_symbols():
    calls, states = [], []

    def transport(url, limit, timeout):
        assert states[-1].last_attempt_at is not None
        calls.append((url, limit, timeout))
        if len(calls) == 1:
            raise SourceError("OI_NETWORK")
        return OIResponse(503, b"") if len(calls) == 2 else OIResponse(200, b"{}")

    client, clock = http(transport, persist=states.append)
    receipt = client.fetch("BTCUSDT")
    assert len(calls) == 3 and calls[0][1] == 4096
    assert clock.delays == [0, 2, 2]
    assert [s.hour_attempts for s in states] == [1, 1, 2, 2, 3, 3]
    assert [s.pending_attempt for s in states] == [True, False, True, False, True, False]
    assert receipt.body == b"{}"
    assert receipt.first_seen_at == receipt.received_at == clock.now()
    client.fetch("ETHUSDT")
    assert calls[-1][0].endswith("symbol=ETHUSDT")
    assert clock.delays[-1] == 2


def test_network_failure_stops_at_three_and_deadline_includes_wait():
    calls = []
    client, clock = http(lambda *_: calls.append(1) or OIResponse(500, b""))
    with pytest.raises(SourceError, match="NETWORK"):
        client.fetch("BTCUSDT")
    assert len(calls) == 3 and clock.seconds == 4
    with pytest.raises(SourceError, match="DEADLINE"):
        client.fetch("BTCUSDT", slot_deadline=clock.seconds + 1)
    assert len(calls) == 3


def test_body_type_and_persistence_failure_are_fail_closed():
    client, _ = http(lambda *_: OIResponse(200, b"x" * 4097))
    with pytest.raises(SourceError, match="RESPONSE_BUDGET"):
        client.fetch("BTCUSDT")
    client, _ = http(lambda *_: OIResponse(200, b"{}", content_type="text/html"))
    with pytest.raises(SourceError, match="CONTENT_TYPE"):
        client.fetch("BTCUSDT")

    def refuse(_):
        raise ValueError("synthetic durable store unavailable")

    client, _ = http(lambda *_: pytest.fail("request before durable reservation"), persist=refuse)
    with pytest.raises(ValueError, match="durable store"):
        client.fetch("BTCUSDT")


@pytest.mark.parametrize(
    "state",
    [
        OIBudgetState(
            hour_started_at=NOW,
            day_started_at=NOW.replace(hour=0),
            hour_attempts=6,
            day_attempts=6,
            last_attempt_at=NOW - timedelta(seconds=2),
        ),
        OIBudgetState(
            hour_started_at=NOW,
            day_started_at=NOW.replace(hour=0),
            hour_attempts=0,
            day_attempts=144,
            last_attempt_at=NOW - timedelta(seconds=2),
        ),
    ],
)
def test_hour_and_day_budgets_are_reserved_before_network(state):
    client, _ = http(lambda *_: pytest.fail("budget bypass"), state=state)
    with pytest.raises(SourceError, match="BUDGET"):
        client.fetch("BTCUSDT")


def test_rollover_does_not_clear_cooldown_or_allow_clock_rewind():
    state = OIBudgetState(
        hour_started_at=NOW,
        day_started_at=NOW.replace(hour=0),
        hour_attempts=6,
        day_attempts=144,
        last_attempt_at=NOW,
        blocked_until=NOW + timedelta(days=3),
    )
    clock = Clock()
    clock.seconds = 86400
    client, _ = http(lambda *_: pytest.fail("cooldown rollover bypass"), state=state, clock=clock)
    with pytest.raises(SourceError, match="COOLDOWN"):
        client.fetch("BTCUSDT")
    state = OIBudgetState(
        hour_started_at=NOW,
        day_started_at=NOW.replace(hour=0),
        last_attempt_at=NOW + timedelta(seconds=1),
    )
    client, _ = http(lambda *_: pytest.fail("clock rewind"), state=state)
    with pytest.raises(SourceError, match="CLOCK_REGRESSION"):
        client.fetch("BTCUSDT")


def test_default_cancel_and_single_instance():
    cancel = Event()
    cancel.set()
    client, _ = http(lambda *_: pytest.fail("cancelled request"), cancel=cancel)
    with pytest.raises(SourceError, match="STOPPED"):
        client.fetch("BTCUSDT")
    entered, release = Event(), Event()

    def transport(*_):
        entered.set()
        assert release.wait(2)
        return OIResponse(200, b"{}")

    client, _ = http(transport)
    errors = []

    def fetch():
        try:
            client.fetch("BTCUSDT")
        except Exception as error:
            errors.append(error)

    thread = Thread(target=fetch)
    thread.start()
    assert entered.wait(2)
    with pytest.raises(SourceError, match="SINGLE_INSTANCE"):
        client.fetch("ETHUSDT")
    release.set()
    thread.join(2)
    assert not thread.is_alive() and not errors


def test_child_request_fixed_headers_no_proxy_no_redirect_and_bytes(monkeypatch):
    captured = {}

    class Response:
        status = 200
        headers = {"Content-Type": "application/json", "Content-Length": "2"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            captured["read_limit"] = limit
            return b"{}"

    class Opener:
        def open(self, req, timeout):
            captured.update(request=req, timeout=timeout)
            return Response()

    def opener(*handlers):
        captured["handlers"] = handlers
        return Opener()

    monkeypatch.setattr(oi_http.urllib.request, "build_opener", opener)
    response = oi_http._worker_request(URL, 4096)
    assert response.body == b"{}" and captured["timeout"] == 3
    assert captured["handlers"][0].proxies == {}
    assert isinstance(captured["handlers"][1], NoRedirect)
    headers = {key.lower(): value for key, value in captured["request"].header_items()}
    assert set(headers) == {"user-agent", "accept", "accept-encoding"}
    assert captured["request"].get_method() == "GET"
    with pytest.raises(SourceError, match="REDIRECT_BLOCKED"):
        captured["handlers"][1].redirect_request(
            None, None, 302, "redirect", {}, "https://evil.invalid"
        )


def test_network_worker_uses_sanitized_environment_and_never_logs_body(monkeypatch):
    captured = {}
    payload = json.dumps(
        dict(
            status=200,
            body=base64.b64encode(b"{}").decode(),
            retry_after=0,
            content_type="application/json",
        )
    ).encode()

    class Process:
        returncode = 0

        def communicate(self, timeout):
            return payload, None

        def poll(self):
            return 0

    def popen(args, **kwargs):
        captured.update(args=args, **kwargs)
        return Process()

    monkeypatch.setenv("HTTPS_PROXY", "https://synthetic-credential.invalid")
    monkeypatch.setenv("SSL_CERT_FILE", "synthetic-untrusted.pem")
    monkeypatch.setenv("X_MBX_APIKEY", "synthetic-not-allowed")
    monkeypatch.setattr(oi_http.subprocess, "Popen", popen)
    assert request_oi(URL, 4096, 10).body == b"{}"
    assert not {"HTTPS_PROXY", "SSL_CERT_FILE", "X_MBX_APIKEY"} & set(captured["env"])
    assert captured["stdin"] == subprocess.DEVNULL
    assert captured["stderr"] == subprocess.DEVNULL
    assert captured["args"][-1] == URL and "-B" in captured["args"]


def test_hung_dns_worker_is_killed_and_reaped_at_deadline(monkeypatch):
    clock = Clock()

    class Process:
        killed = False
        returncode = None

        def communicate(self, timeout):
            if self.killed:
                self.returncode = -9
                return b"", None
            clock.seconds += timeout
            raise subprocess.TimeoutExpired("synthetic worker", timeout)

        def poll(self):
            return self.returncode

        def kill(self):
            self.killed = True

    process = Process()
    monkeypatch.setattr(oi_http.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(oi_http.subprocess, "Popen", lambda *a, **kw: process)
    with pytest.raises(SourceError, match="ATTEMPT_DEADLINE"):
        request_oi(URL, 4096, 0.2)
    assert process.killed and process.returncode == -9
    assert clock.seconds <= 0.21


def test_unknown_reserved_attempt_blocks_restart_and_completion_failure():
    state = OIBudgetState(
        hour_started_at=NOW,
        day_started_at=NOW.replace(hour=0),
        hour_attempts=1,
        day_attempts=1,
        last_attempt_at=NOW,
        pending_attempt=True,
    )
    with pytest.raises(SourceError, match="OUTCOME_REVIEW_REQUIRED"):
        http(lambda *_: pytest.fail("unknown attempt restart"), state=state)
    states = []

    def persist(value):
        if not value.pending_attempt:
            raise ValueError("synthetic completion persistence failure")
        states.append(value)

    client, _ = http(lambda *_: OIResponse(200, b"{}"), persist=persist)
    with pytest.raises(ValueError, match="completion persistence"):
        client.fetch("BTCUSDT")
    assert states[-1].pending_attempt and client.state.pending_attempt
    with pytest.raises(SourceError, match="OUTCOME_REVIEW_REQUIRED"):
        client.fetch("ETHUSDT")


def test_failed_cooldown_persistence_retains_inmemory_block_and_durable_unknown():
    states = []

    def persist(value):
        if value.blocked_until is not None:
            raise ValueError("synthetic cooldown persistence failure")
        states.append(value)

    client, _ = http(lambda *_: OIResponse(429, b"", 3600), persist=persist)
    with pytest.raises(ValueError, match="cooldown persistence"):
        client.fetch("BTCUSDT")
    assert states[-1].pending_attempt
    assert client.state.blocked_until > NOW
    with pytest.raises(SourceError, match="COOLDOWN"):
        client.fetch("ETHUSDT")


def test_midflight_cancel_kills_reaps_network_worker(monkeypatch):
    cancel = Event()

    class Process:
        killed = False
        returncode = None

        def communicate(self, timeout):
            if self.killed:
                self.returncode = -9
                return b"", None
            cancel.set()
            raise subprocess.TimeoutExpired("synthetic worker", timeout)

        def poll(self):
            return self.returncode

        def kill(self):
            self.killed = True

    process = Process()
    monkeypatch.setattr(oi_http.subprocess, "Popen", lambda *a, **kw: process)
    with pytest.raises(SourceError, match="STOPPED"):
        request_oi(URL, 4096, 10, cancel=cancel)
    assert process.killed and process.returncode == -9


@pytest.mark.parametrize("status", [429, 418, 403, 451])
@pytest.mark.parametrize("interrupt", ["cancel", "deadline"])
def test_received_restriction_is_durable_before_cancel_or_deadline(status, interrupt):
    cancel, states, clock = Event(), [], Clock()

    def transport(*_):
        if interrupt == "cancel":
            cancel.set()
        else:
            clock.seconds = 30
        return OIResponse(status, b"", 3600)

    client, _ = http(transport, cancel=cancel, clock=clock, persist=states.append)
    with pytest.raises(SourceError, match="RATE_LIMIT|ACCESS_BLOCKED"):
        client.fetch("BTCUSDT")
    assert states[-1].blocked_until is not None and not states[-1].pending_attempt


@pytest.mark.parametrize(
    "code", ["OI_STOPPED", "OI_ATTEMPT_DEADLINE", "OI_WORKER_FAILED", "OI_WORKER_CLEANUP_FAILED"]
)
def test_unknown_worker_outcome_stays_reserved_for_review(code):
    states = []

    def transport(*_):
        raise SourceError(code)

    client, _ = http(transport, persist=states.append)
    with pytest.raises(SourceError, match=code):
        client.fetch("BTCUSDT")
    assert states[-1].pending_attempt and client.state.pending_attempt
    with pytest.raises(SourceError, match="OUTCOME_REVIEW_REQUIRED"):
        client.fetch("ETHUSDT")


def test_per_attempt_admission_rejects_before_request_or_budget_reservation():
    from datetime import UTC, datetime
    from threading import Event

    from auvexo_alpha.infrastructure.oi_http import OIHTTP, OIBudgetState, OIResponse

    now = datetime(2026, 10, 30, 12, tzinfo=UTC)
    persisted, calls = [], []

    def refuse(at):
        assert at == now
        raise ValueError("OI_RIGHTS_EXPIRED")

    http = OIHTTP(
        Event(),
        state=OIBudgetState(hour_started_at=now, day_started_at=now.replace(hour=0)),
        persist=persisted.append,
        before_attempt=refuse,
        now=lambda: now,
        transport=lambda *args: calls.append(args) or OIResponse(200, b"{}"),
    )
    with pytest.raises(SourceError, match="OI_ADMISSION_BLOCKED"):
        http.fetch("BTCUSDT")
    assert calls == [] and persisted == [] and http.state.hour_attempts == 0
