"""Fixed-source OI transport with durable budgets and a killable bounded network worker."""

import base64
import http.client
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Lock
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from auvexo_alpha.domain.contracts import Contract, UTCTime, utc_time
from auvexo_alpha.domain.open_interest import OI_ENDPOINT, OISymbol
from auvexo_alpha.infrastructure.public_http import NoRedirect, SourceError

MAX_BODY = 4096
MAX_ATTEMPT_SECONDS = 10.0
# Allowance for the isolated interpreter to start and import this module (about one
# second measured on the reference laptop), the child's connect/read idle timeout and
# the parent's bounded kill-and-reap. An attempt that cannot fit all three is not viable.
WORKER_START_SECONDS = 2.0
SOCKET_TIMEOUT_SECONDS = 3.0
WORKER_CLEANUP_SECONDS = 1.0
MIN_ATTEMPT_SECONDS = WORKER_START_SECONDS + SOCKET_TIMEOUT_SECONDS + WORKER_CLEANUP_SECONDS

# A reserved attempt that ended without any admitted provider response. Its budget
# stays consumed and the exact cause stays in the append-only transport state.
OIAttemptFailure = Literal[
    "OI_STOPPED",
    "OI_ATTEMPT_DEADLINE",
    "OI_WORKER_FAILED",
    "OI_WORKER_CLEANUP_FAILED",
    "OI_JOB_DEADLINE",
    "OI_ATTEMPT_OUTCOME_UNKNOWN",
]
_UNADMITTED_ATTEMPT_CODES: tuple[OIAttemptFailure, ...] = (
    "OI_STOPPED",
    "OI_ATTEMPT_DEADLINE",
    "OI_WORKER_FAILED",
    "OI_WORKER_CLEANUP_FAILED",
    "OI_JOB_DEADLINE",
)


def allowed_oi_url(url: str) -> bool:
    # Exact string equality intentionally refuses alternate encodings, ports, credentials,
    # fragments, duplicate/extra queries and every non-source account/trading route.
    return url in tuple(OI_ENDPOINT + "?symbol=" + s for s in ("BTCUSDT", "ETHUSDT"))


@dataclass(frozen=True)
class OIResponse:
    status: int
    body: bytes
    retry_after: int = 0
    content_type: str = "application/json"


@dataclass(frozen=True)
class OIReceipt:
    body: bytes
    request_sent_at: datetime
    first_seen_at: datetime
    received_at: datetime


class OIBudgetState(Contract):
    hour_started_at: UTCTime
    day_started_at: UTCTime
    hour_attempts: Annotated[int, Field(ge=0, le=6)] = 0
    day_attempts: Annotated[int, Field(ge=0, le=144)] = 0
    last_attempt_at: UTCTime | None = None
    blocked_until: UTCTime | None = None
    pending_attempt: bool = False
    failed_attempt: OIAttemptFailure | None = None

    @model_validator(mode="after")
    def boundaries(self) -> Self:
        if (
            self.hour_started_at != self.hour_started_at.replace(minute=0, second=0, microsecond=0)
            or self.day_started_at
            != self.day_started_at.replace(hour=0, minute=0, second=0, microsecond=0)
            or not self.day_started_at
            <= self.hour_started_at
            < self.day_started_at + timedelta(days=1)
            or self.hour_attempts > self.day_attempts
        ):
            raise ValueError("OI_BUDGET_STATE")
        if (
            self.hour_attempts or self.day_attempts or self.pending_attempt
        ) and self.last_attempt_at is None:
            raise ValueError("OI_BUDGET_STATE")
        if self.failed_attempt is not None and (
            self.pending_attempt or self.last_attempt_at is None
        ):
            raise ValueError("OI_BUDGET_STATE")
        return self


def _retry_seconds(value: str) -> int:
    if value.isascii() and value.isdecimal() and len(value) <= 7:
        return min(max(60, int(value)), 366 * 86400)
    return 3 * 86400


def _worker_request(url: str, limit: int) -> OIResponse:
    """Child-only blocking I/O. Parent forcibly bounds DNS/connect/read/cleanup time."""
    if not allowed_oi_url(url) or limit != MAX_BODY:
        raise SourceError("OI_SOURCE_CONFIG")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Auvexo-Research/0.6",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
        method="GET",
    )
    try:
        with opener.open(req, timeout=SOCKET_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("Content-Type", "")
            if content_type.split(";", 1)[0].strip().lower() != "application/json":
                raise SourceError("OI_CONTENT_TYPE")
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise SourceError("OI_CONTENT_ENCODING")
            size_header = response.headers.get("Content-Length")
            if size_header is not None and (
                not size_header.isascii()
                or not size_header.isdecimal()
                or len(size_header) > 8
                or int(size_header) > limit
            ):
                raise SourceError("OI_RESPONSE_BUDGET")
            body = response.read(limit + 1)
            if len(body) > limit:
                raise SourceError("OI_RESPONSE_BUDGET")
            return OIResponse(response.status, body, content_type=content_type)
    except urllib.error.HTTPError as error:
        return OIResponse(error.code, b"", _retry_seconds(error.headers.get("Retry-After", "")))
    except SourceError:
        raise
    except (
        urllib.error.URLError,
        TimeoutError,
        ConnectionError,
        OSError,
        # IncompleteRead, BadStatusLine, LineTooLong and other malformed or truncated
        # responses are transient transport faults, never a reason to crash the worker.
        http.client.HTTPException,
    ) as error:
        raise SourceError("OI_NETWORK") from error


def _worker_main(url: str) -> int:
    try:
        response = _worker_request(url, MAX_BODY)
        result: dict[str, object] = {
            "status": response.status,
            "body": base64.b64encode(response.body).decode("ascii"),
            "retry_after": response.retry_after,
            "content_type": response.content_type,
        }
    except SourceError as error:
        result = {"error": error.code}
    # This private bounded IPC payload is never printed by the parent or placed in logs.
    sys.stdout.write(json.dumps(result, separators=(",", ":"), ensure_ascii=True))
    return 0


def _worker_command(url: str) -> list[str]:
    # Isolated mode ignores every PYTHON* variable and keeps the user site, the script
    # directory and the current directory off sys.path, so no file beside the launch
    # directory can shadow the standard library or the installed package.
    return [
        sys.executable,
        "-I",
        "-B",
        "-m",
        "auvexo_alpha.infrastructure.oi_http",
        "--worker",
        url,
    ]


def request_oi(url: str, limit: int, timeout: float, *, cancel: Event | None = None) -> OIResponse:
    if not allowed_oi_url(url) or limit != MAX_BODY or not 0 < timeout <= MAX_ATTEMPT_SECONDS:
        raise SourceError("OI_SOURCE_CONFIG")
    cancel = cancel or Event()
    if cancel.is_set():
        raise SourceError("OI_STOPPED")
    # Inherit no proxy, authentication, cookie, certificate override or Python startup hooks.
    env = {k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP") if k in os.environ}
    started = time.monotonic()
    cleanup_budget = min(WORKER_CLEANUP_SECONDS, timeout / 2)
    worker_budget = timeout - cleanup_budget
    process = subprocess.Popen(
        _worker_command(url),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        cwd=Path(__file__).resolve().parents[3],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        while True:
            remaining = worker_budget - (time.monotonic() - started)
            if cancel.is_set():
                raise SourceError("OI_STOPPED")
            if remaining <= 0:
                raise SourceError("OI_ATTEMPT_DEADLINE")
            try:
                output, _ = process.communicate(timeout=min(0.05, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode or len(output) > 8192:
            raise SourceError("OI_WORKER_FAILED")
        try:
            payload = json.loads(output)
            if not isinstance(payload, dict):
                raise ValueError("worker schema")
            if set(payload) == {"error"} and payload["error"] in {
                "OI_SOURCE_CONFIG",
                "OI_CONTENT_TYPE",
                "OI_CONTENT_ENCODING",
                "OI_RESPONSE_BUDGET",
                "REDIRECT_BLOCKED",
                "OI_NETWORK",
            }:
                raise SourceError(payload["error"])
            if set(payload) != {"status", "body", "retry_after", "content_type"}:
                raise ValueError("worker schema")
            if (
                type(payload["status"]) is not int
                or not 100 <= payload["status"] <= 599
                or type(payload["retry_after"]) is not int
                or not 0 <= payload["retry_after"] <= 366 * 86400
                or not isinstance(payload["body"], str)
                or not isinstance(payload["content_type"], str)
                or len(payload["content_type"]) > 256
            ):
                raise ValueError("worker schema")
            body = base64.b64decode(payload["body"], validate=True)
            if len(body) > MAX_BODY:
                raise ValueError("worker body")
            return OIResponse(
                payload["status"], body, payload["retry_after"], payload["content_type"]
            )
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as error:
            if isinstance(error, SourceError):
                raise
            raise SourceError("OI_WORKER_FAILED") from error
    finally:
        if process.poll() is None:
            process.kill()
        try:
            process.communicate(
                timeout=max(0.001, min(cleanup_budget, timeout - (time.monotonic() - started)))
            )
        except subprocess.TimeoutExpired as error:
            raise SourceError("OI_WORKER_CLEANUP_FAILED") from error


class OIHTTP:
    def __init__(
        self,
        cancel: Event,
        *,
        state: OIBudgetState,
        persist: Callable[[OIBudgetState], None],
        before_attempt: Callable[[datetime], None] | None = None,
        transport: Callable[[str, int, float], OIResponse] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        wait: Callable[[float], bool] | None = None,
    ) -> None:
        self.cancel = cancel
        self.state = OIBudgetState.model_validate(state.model_dump(mode="python"))
        self.persist = persist
        self.before_attempt = before_attempt
        self.transport = transport
        self.monotonic = monotonic
        self.now = now
        self.wait = wait or cancel.wait
        self._lock = Lock()

    def _record_attempt(self, at: datetime) -> None:
        state = self.state
        hour = at.replace(minute=0, second=0, microsecond=0)
        day = at.replace(hour=0, minute=0, second=0, microsecond=0)
        if (
            hour < state.hour_started_at
            or day < state.day_started_at
            or (state.last_attempt_at is not None and at < state.last_attempt_at)
        ):
            raise SourceError("OI_CLOCK_REGRESSION")
        hour_count = state.hour_attempts if hour == state.hour_started_at else 0
        day_count = state.day_attempts if day == state.day_started_at else 0
        if hour_count >= 6 or day_count >= 144:
            raise SourceError("OI_NETWORK_BUDGET")
        updated = OIBudgetState(
            hour_started_at=hour,
            day_started_at=day,
            hour_attempts=hour_count + 1,
            day_attempts=day_count + 1,
            last_attempt_at=at,
            blocked_until=state.blocked_until,
            pending_attempt=True,
        )
        # Persistence failure prevents the request. A crash may overcount but never undercount.
        self.persist(updated)
        self.state = updated

    def _cooldown(self, seconds: int) -> None:
        until = utc_time(self.now()) + timedelta(seconds=max(60, min(seconds, 366 * 86400)))
        if self.state.blocked_until is not None:
            until = max(until, self.state.blocked_until)
        updated = OIBudgetState.model_validate(
            {
                **self.state.model_dump(mode="python"),
                "blocked_until": until,
                "pending_attempt": False,
            }
        )
        # Keep the in-memory block even if persistence fails; durable pending remains.
        self.state = updated
        self.persist(updated)

    def _complete_attempt(self, failure: OIAttemptFailure | None = None) -> None:
        updated = OIBudgetState.model_validate(
            {
                **self.state.model_dump(mode="python"),
                "pending_attempt": False,
                "failed_attempt": failure,
            }
        )
        self.persist(updated)
        self.state = updated

    def _resolve_unknown_attempt(self, at: datetime) -> None:
        """A reservation with no recorded outcome fails closed for its own slot only.

        Its budget was reserved before the request and stays consumed, and no receipt
        was returned from it, so nothing was admitted. A later slot records it as a
        failed attempt: one crash, kill or lost completion cannot block every future slot.
        """
        reserved = self.state.last_attempt_at
        if reserved is None or at.replace(minute=0, second=0, microsecond=0) <= reserved.replace(
            minute=0, second=0, microsecond=0
        ):
            raise SourceError("OI_TRANSPORT_OUTCOME_REVIEW_REQUIRED")
        self._complete_attempt("OI_ATTEMPT_OUTCOME_UNKNOWN")

    def fetch(self, symbol: OISymbol, *, slot_deadline: float | None = None) -> OIReceipt:
        if symbol not in ("BTCUSDT", "ETHUSDT"):
            raise SourceError("OI_SOURCE_CONFIG")
        if not self._lock.acquire(blocking=False):
            raise SourceError("OI_SINGLE_INSTANCE")
        try:
            return self._fetch(symbol, slot_deadline)
        finally:
            self._lock.release()

    def _fetch(self, symbol: OISymbol, slot_deadline: float | None) -> OIReceipt:
        start = self.monotonic()
        deadline = min(start + 20.0, slot_deadline if slot_deadline is not None else start + 60.0)
        for attempt in range(3):
            if self.cancel.is_set():
                raise SourceError("OI_STOPPED")
            at = utc_time(self.now())
            if self.state.pending_attempt:
                self._resolve_unknown_attempt(at)
            if self.state.blocked_until is not None and at < self.state.blocked_until:
                raise SourceError("OI_COOLDOWN")
            gap = 0.0
            if self.state.last_attempt_at is not None:
                elapsed = (at - self.state.last_attempt_at).total_seconds()
                if elapsed < 0:
                    raise SourceError("OI_CLOCK_REGRESSION")
                gap = max(0.0, 2.0 - elapsed)
            nominal_backoff = float(2 ** (attempt - 1)) if attempt else 0.0
            delay = max(gap, nominal_backoff)
            if self.monotonic() + delay >= deadline:
                raise SourceError("OI_JOB_DEADLINE")
            if self.wait(delay) or self.cancel.is_set():
                raise SourceError("OI_STOPPED")
            at = utc_time(self.now())
            if (
                self.state.last_attempt_at is not None
                and (at - self.state.last_attempt_at).total_seconds() < 2
            ):
                raise SourceError("OI_CLOCK_SPACING")
            remaining = deadline - self.monotonic()
            if remaining < MIN_ATTEMPT_SECONDS:
                # Never reserve budget for a request that cannot start, connect and be
                # reaped inside the symbol/slot deadline; end cleanly, nothing pending.
                raise SourceError("OI_JOB_DEADLINE")
            if self.before_attempt is not None:
                try:
                    self.before_attempt(at)
                except ValueError as error:
                    raise SourceError("OI_ADMISSION_BLOCKED") from error
            self._record_attempt(at)
            try:
                timeout = min(MAX_ATTEMPT_SECONDS, remaining)
                url = OI_ENDPOINT + "?symbol=" + symbol
                response = (
                    request_oi(url, MAX_BODY, timeout, cancel=self.cancel)
                    if self.transport is None
                    else self.transport(url, MAX_BODY, timeout)
                )
                # Persist access/rate restrictions before cancellation, wall-clock or
                # body checks can hide a received provider restriction.
                if response.status in (418, 429):
                    self._cooldown(response.retry_after or 3 * 86400)
                    raise SourceError("OI_RATE_LIMIT", max(60, response.retry_after or 3 * 86400))
                if response.status in (403, 451):
                    self._cooldown(3 * 86400)
                    raise SourceError("OI_PROVIDER_ACCESS_BLOCKED", 3 * 86400)
                received = utc_time(self.now())
                if self.cancel.is_set():
                    raise SourceError("OI_STOPPED")
                if self.monotonic() > deadline or received < at:
                    raise SourceError("OI_JOB_DEADLINE")
                if len(response.body) > MAX_BODY:
                    raise SourceError("OI_RESPONSE_BUDGET")
                if response.status == 200:
                    if response.content_type.split(";", 1)[0].strip().lower() != "application/json":
                        raise SourceError("OI_CONTENT_TYPE")
                    # Earliest observation is deliberately the actual complete receipt;
                    # provider time is never substituted as first_seen.
                    self._complete_attempt()
                    return OIReceipt(response.body, at, received, received)
                if response.status >= 500:
                    raise SourceError("OI_NETWORK")
                raise SourceError("OI_SOURCE_UNAVAILABLE")
            except SourceError as error:
                if self.state.pending_attempt:
                    # A killed, timed-out, crashed or cancelled worker is a completed
                    # failed attempt: budget consumed, cause recorded, no data admitted.
                    self._complete_attempt(
                        next((c for c in _UNADMITTED_ATTEMPT_CODES if c == error.code), None)
                    )
                if error.code != "OI_NETWORK" or attempt == 2:
                    raise
        raise SourceError("OI_NETWORK")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--worker" or not allowed_oi_url(sys.argv[2]):
        raise SystemExit(2)
    raise SystemExit(_worker_main(sys.argv[2]))
