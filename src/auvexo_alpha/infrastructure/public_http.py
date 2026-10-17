"""GET-only public source transport, bounded bytes, attempts, time and cancellation."""

import random
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event
from urllib.parse import parse_qs, urlsplit


class SourceError(ValueError):
    def __init__(self, code: str, cooldown: int = 0) -> None:
        super().__init__(code)
        self.code, self.cooldown = code, cooldown


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    retry_after: int = 0


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        raise SourceError("REDIRECT_BLOCKED")


def allowed_url(url: str) -> bool:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port
        or parsed.fragment
    ):
        return False
    if parsed.hostname == "data.binance.vision":
        match = re.fullmatch(
            r"/data/spot/(daily|monthly)/klines/(BTCUSDT|ETHUSDT)/(1m|1h)/([A-Z]+)-(1m|1h)-(\d{4}-\d{2}(?:-\d{2})?)\.zip(?:\.CHECKSUM)?",
            parsed.path,
        )
        return bool(match and match[2] == match[4] and match[3] == match[5] and not parsed.query)
    if parsed.hostname != "data-api.binance.vision" or len(parsed.query) > 256:
        return False
    if parsed.path == "/api/v3/time":
        return not parsed.query
    query = parse_qs(parsed.query, keep_blank_values=True)
    if any(len(values) != 1 for values in query.values()):
        return False
    if query.get("symbol") not in (["BTCUSDT"], ["ETHUSDT"]):
        return False
    if parsed.path == "/api/v3/exchangeInfo":
        return set(query) == {"symbol"}
    if parsed.path != "/api/v3/klines" or set(query) - {
        "symbol",
        "interval",
        "startTime",
        "endTime",
        "limit",
    }:
        return False
    if query.get("interval") not in (["1m"], ["1h"]):
        return False
    for field in ("startTime", "endTime", "limit"):
        if field in query and not re.fullmatch(r"[0-9]{1,16}", query[field][0]):
            return False
    return "limit" not in query or 1 <= int(query["limit"][0]) <= 1000


def request(url: str, limit: int) -> Response:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Auvexo-Research/0.2", "Accept-Encoding": "identity"},
        method="GET",
    )
    try:
        with opener.open(req, timeout=15) as response:
            started = time.monotonic()
            chunks, size = [], 0
            while chunk := response.read(min(65536, limit + 1 - size)):
                size += len(chunk)
                if size > limit or time.monotonic() - started > 30:
                    raise SourceError("RESPONSE_BUDGET")
                chunks.append(chunk)
            return Response(response.status, b"".join(chunks))
    except urllib.error.HTTPError as error:
        retry = error.headers.get("Retry-After", "")
        cooldown = (
            int(retry) if retry.isascii() and retry.isdecimal() and len(retry) <= 7 else 3 * 86400
        )
        if cooldown > 366 * 86400:
            raise SourceError("PROVIDER_ACCESS_BLOCKED", 366 * 86400) from error
        return Response(error.code, b"", cooldown)
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
        raise SourceError("NETWORK") from error


class PublicHTTP:
    def __init__(
        self,
        cancel: Event,
        transport: Callable[[str, int], Response] = request,
        wait: Callable[[float], bool] | None = None,
        max_requests: int = 128,
        max_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        if not 1 <= max_requests <= 256 or not 1 <= max_bytes <= 128 * 1024 * 1024:
            raise ValueError("NETWORK_BUDGET")
        self.cancel, self.transport, self.wait = cancel, transport, wait or cancel.wait
        self.max_requests, self.max_bytes = max_requests, max_bytes
        self.requests = self.bytes = 0
        self.blocked = False

    def get(self, url: str, limit: int) -> bytes:
        if not allowed_url(url) or not 1 <= limit <= 16 * 1024 * 1024:
            raise SourceError("SOURCE_CONFIG")
        for attempt in range(3):
            if self.blocked or self.cancel.is_set() or self.wait(2.0 if self.requests else 0):
                raise SourceError("STOPPED")
            if self.requests >= self.max_requests or self.bytes >= self.max_bytes:
                raise SourceError("NETWORK_BUDGET")
            self.requests += 1
            try:
                response = self.transport(url, min(limit, self.max_bytes - self.bytes))
                self.bytes += len(response.body)
                if len(response.body) > limit or self.bytes > self.max_bytes:
                    raise SourceError("RESPONSE_BUDGET")
                if response.status == 200:
                    return response.body
                if response.status in (418, 429):
                    self.blocked = True
                    raise SourceError("RATE_LIMIT", max(60, response.retry_after))
                if response.status in (403, 451):
                    self.blocked = True
                    raise SourceError("PROVIDER_ACCESS_BLOCKED", 3 * 86400)
                if response.status < 500:
                    raise SourceError("SOURCE_UNAVAILABLE")
                raise SourceError("NETWORK")
            except SourceError as error:
                if error.code != "NETWORK" or attempt == 2:
                    raise
            if self.wait(2**attempt + random.SystemRandom().uniform(0, 0.25)):
                raise SourceError("STOPPED")
        raise SourceError("NETWORK")
