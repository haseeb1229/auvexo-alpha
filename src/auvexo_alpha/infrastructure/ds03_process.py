"""Dedicated isolated synthetic connector process; no SDK, terminal or broker account."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from queue import Empty, Queue
from threading import Lock, Thread
from time import monotonic
from types import TracebackType
from typing import IO, Literal
from uuid import UUID, uuid4

from auvexo_alpha.application.ds03 import Ds03Reader
from auvexo_alpha.domain.ds03 import (
    MAX_FRAME_BYTES,
    MAX_REQUESTS,
    AttestationPayload,
    AttestRequest,
    DisconnectRequest,
    Ds03Attestation,
    Ds03Error,
    Ds03Reply,
    Ds03Request,
    Ds03Rights,
    decode_reply,
    decode_request,
)
from auvexo_alpha.infrastructure.ds03_fake import (
    SyntheticDs03Terminal,
    synthetic_identity,
    synthetic_rights,
)
from auvexo_alpha.infrastructure.ds03_ipc import (
    Ds03ProtocolError,
    bootstrap_frame,
    canonical,
    decode_frame,
    encode_frame,
    new_pipe_key,
    read_bootstrap,
)

_IO_TIMEOUT_SECONDS = 10


def source_binding() -> str:
    """Hash only fixed implementation files and this interpreter; accept no caller path."""
    package = Path(__file__).resolve().parents[1]
    names = (
        "domain/contracts.py",
        "domain/ds03.py",
        "application/ds03.py",
        "application/ds03_ports.py",
        "infrastructure/ds03_fake.py",
        "infrastructure/ds03_ipc.py",
        "infrastructure/ds03_process.py",
    )
    manifest = {name: hashlib.sha256((package / name).read_bytes()).hexdigest() for name in names}
    manifest["python"] = hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
    return hashlib.sha256(canonical(manifest)).hexdigest()


def _child_environment() -> dict[str, str]:
    # The isolated interpreter ignores Python environment injection. No owner secret,
    # arbitrary PATH, Python path, home override or account variable reaches the child.
    return {
        name: value
        for name, value in os.environ.items()
        if name.upper() in {"SYSTEMROOT", "WINDIR"}
    }


def _bounded(action: Callable[[], bytes], *, budget: float | None = None) -> bytes:
    wait = _IO_TIMEOUT_SECONDS if budget is None else min(_IO_TIMEOUT_SECONDS, budget)
    if wait <= 0:
        raise Ds03ProtocolError()
    result: Queue[bytes | None] = Queue(maxsize=1)

    def work() -> None:
        try:
            result.put(action())
        except Exception:
            # One IPC redaction boundary; partial output is never accepted.
            result.put(None)

    Thread(target=work, daemon=True).start()
    try:
        value = result.get(timeout=wait)
    except Empty:
        raise Ds03ProtocolError() from None
    if value is None:
        raise Ds03ProtocolError()
    return value


def _write(writer: IO[bytes], raw: bytes) -> bytes:
    if not 0 < len(raw) <= MAX_FRAME_BYTES:
        raise Ds03ProtocolError()
    offset = 0
    while offset < len(raw):
        count = writer.write(raw[offset:])
        if count is None or count <= 0:
            raise Ds03ProtocolError()
        offset += count
    writer.flush()
    return b""


def _read(reader: IO[bytes]) -> bytes:
    raw = reader.readline(MAX_FRAME_BYTES + 1)
    if not raw or len(raw) > MAX_FRAME_BYTES or not raw.endswith(b"\n"):
        raise Ds03ProtocolError()
    return raw


def _exchange(reader: IO[bytes], writer: IO[bytes], raw: bytes) -> bytes:
    _write(writer, raw)
    return _read(reader)


def _control_request(
    operation: Literal["ATTEST", "DISCONNECT"],
) -> AttestRequest | DisconnectRequest:
    now = datetime.now(UTC)
    expected = synthetic_identity()
    if operation == "ATTEST":
        return AttestRequest(
            request_id=uuid4(),
            created_at=now,
            expires_at=now + timedelta(seconds=10),
            release_hash=expected.release_hash,
            config_hash=expected.config_hash,
        )
    return DisconnectRequest(
        request_id=uuid4(),
        created_at=now,
        expires_at=now + timedelta(seconds=10),
        release_hash=expected.release_hash,
        config_hash=expected.config_hash,
    )


class Ds03Process:
    """High-level guarded reader; the child owns Ds03Reader over the fixed fake port.

    This is not the raw Ds03ReadPort: wrapping it in a second reader would duplicate
    attestation and conflict with the final acknowledged DISCONNECT lifecycle.
    """

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._key = b""
        self._session: UUID | None = None
        self._sequence = 1
        self._seen: set[UUID] = set()
        self._lock = Lock()
        self._generation = 0

    def start(self) -> Ds03Process:
        if not self._lock.acquire(blocking=False):
            self.close()
            raise Ds03Error()
        try:
            return self._start()
        finally:
            self._lock.release()

    def _start(self) -> Ds03Process:
        generation = self._generation
        if self._process is not None:
            raise Ds03Error()
        try:
            key, session, binding = new_pipe_key(), uuid4(), source_binding()
            flags = 0
            if sys.platform == "win32":
                flags = subprocess.CREATE_NO_WINDOW
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    "-m",
                    "auvexo_alpha.infrastructure.ds03_process",
                    "--synthetic-child",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                shell=False,
                cwd=Path(sys.executable).resolve().parent,
                env=_child_environment(),
                creationflags=flags,
                bufsize=0,
            )
            self._process, self._key, self._session = process, key, session
            self._sequence, self._seen = 1, set()
            if process.stdin is None or process.stdout is None:
                raise Ds03Error()
            reader, writer = process.stdout, process.stdin
            raw = _bounded(
                lambda: _exchange(reader, writer, bootstrap_frame(key, session, binding))
            )
            if self._process is not process or self._generation != generation:
                raise Ds03Error()
            hello = decode_frame(raw, key=key, session=session, sequence=0, kind="HELLO")
            if hello.request_id is not None or set(hello.payload) != {
                "binding",
                "attestation",
                "rights",
            }:
                raise Ds03Error()
            observed = Ds03Attestation.model_validate_json(canonical(hello.payload["attestation"]))
            rights = Ds03Rights.model_validate_json(canonical(hello.payload["rights"]))
            if (
                hello.payload["binding"] != binding
                or observed.identity != synthetic_identity()
                or rights != synthetic_rights()
                or not timedelta(0)
                <= datetime.now(UTC) - observed.observed_at
                <= timedelta(seconds=30)
            ):
                raise Ds03Error()
            return self
        except Exception:
            self.close()
            raise Ds03Error() from None

    def read(self, request: Ds03Request) -> Ds03Reply:
        if not self._lock.acquire(blocking=False):
            self.close()
            raise Ds03Error()
        try:
            started = monotonic()
            process, session, key = self._process, self._session, self._key
            generation = self._generation
            request = decode_request(request.canonical_bytes())
            expected = synthetic_identity()
            now = datetime.now(UTC)
            if (
                process is None
                or session is None
                or process.stdin is None
                or process.stdout is None
                or process.poll() is not None
                or self._sequence > MAX_REQUESTS
                or request.request_id in self._seen
                or request.release_hash != expected.release_hash
                or request.config_hash != expected.config_hash
                or not request.created_at <= now < request.expires_at
            ):
                raise Ds03Error()
            request_budget = (request.expires_at - now).total_seconds()
            deadline = started + request_budget
            self._seen.add(request.request_id)
            sequence = self._sequence
            self._sequence += 1
            outgoing = encode_frame(
                "REQUEST",
                request.model_dump(mode="json"),
                key=key,
                session=session,
                sequence=sequence,
                request_id=request.request_id,
            )
            reader, writer = process.stdout, process.stdin
            remaining = min(
                (request.expires_at - datetime.now(UTC)).total_seconds(), deadline - monotonic()
            )
            raw = _bounded(lambda: _exchange(reader, writer, outgoing), budget=remaining)
            if (
                self._process is not process
                or self._session != session
                or self._generation != generation
            ):
                raise Ds03Error()
            frame = decode_frame(raw, key=key, session=session, sequence=sequence, kind="REPLY")
            if frame.request_id != request.request_id:
                raise Ds03Error()
            reply = decode_reply(canonical(frame.payload))
            completed_at = datetime.now(UTC)
            if (
                reply.request_id != request.request_id
                or reply.operation != request.operation
                or reply.envelope.identity != expected
                or reply.envelope.connector_hash != expected.release_hash
                or reply.envelope.clock_status != "STRUCTURAL_ONLY_CLOCK_BLOCKED"
                or not request.created_at <= completed_at < request.expires_at
                or monotonic() >= deadline
                or not request.created_at
                <= reply.envelope.received_at
                <= reply.envelope.available_at
                <= completed_at
            ):
                raise Ds03Error()
            if isinstance(request, DisconnectRequest):
                # Acknowledged teardown shares the original request's UTC/monotonic
                # deadline; an unrelated shorter shutdown cutoff is not a protocol gate.
                remaining = min(
                    (request.expires_at - datetime.now(UTC)).total_seconds(), deadline - monotonic()
                )
                if remaining <= 0 or process.wait(timeout=remaining) != 0:
                    raise Ds03Error()
                if datetime.now(UTC) >= request.expires_at or monotonic() >= deadline:
                    raise Ds03Error()
                self.close()
            return reply
        except Exception:
            self.close()
            raise Ds03Error() from None
        finally:
            self._lock.release()

    def attest(self) -> Ds03Attestation:
        reply = self.read(_control_request("ATTEST"))
        if not isinstance(reply.payload, AttestationPayload):
            self.close()
            raise Ds03Error()
        return reply.payload.attestation

    def disconnect(self) -> None:
        if self._process is not None:
            self.read(_control_request("DISCONNECT"))

    def close(self) -> None:
        self._generation += 1
        process, self._process = self._process, None
        self._key, self._session, self._seen = b"", None, set()
        if process is None:
            return
        failed = False
        try:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            failed = True
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    failed = True
        if failed:
            raise Ds03Error()

    def __enter__(self) -> Ds03Process:
        return self.start()

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def serve_synthetic(reader: IO[bytes], writer: IO[bytes]) -> int:
    """Fixed inherited-pipe server; unknown input closes instead of resynchronizing."""
    terminal: SyntheticDs03Terminal | None = None
    try:
        binding = source_binding()
        key, session = read_bootstrap(_bounded(lambda: _read(reader)), binding)
        terminal = SyntheticDs03Terminal()
        service = Ds03Reader(
            terminal, synthetic_identity(), synthetic_rights(), clock=lambda: datetime.now(UTC)
        )
        hello: dict[str, object] = {
            "binding": binding,
            "attestation": terminal.attest().model_dump(mode="json"),
            "rights": synthetic_rights().model_dump(mode="json"),
        }
        _bounded(
            lambda: _write(
                writer,
                encode_frame("HELLO", hello, key=key, session=session, sequence=0, request_id=None),
            )
        )
        seen: set[UUID] = set()
        for sequence in range(1, MAX_REQUESTS + 1):
            request_id: UUID | None = None
            try:
                incoming = _bounded(lambda: _read(reader))
                frame = decode_frame(
                    incoming, key=key, session=session, sequence=sequence, kind="REQUEST"
                )
                request_id = frame.request_id
                request = decode_request(canonical(frame.payload))
                if request_id != request.request_id or request.request_id in seen:
                    raise Ds03Error()
                seen.add(request.request_id)
                reply = service.read(request, now=datetime.now(UTC))
                encoded = encode_frame(
                    "REPLY",
                    reply.model_dump(mode="json"),
                    key=key,
                    session=session,
                    sequence=sequence,
                    request_id=request_id,
                )
            except Exception:
                # Fixed authenticated error only; never include input or backend detail.
                encoded = encode_frame(
                    "ERROR",
                    {"code": "DS03_UNAVAILABLE"},
                    key=key,
                    session=session,
                    sequence=sequence,
                    request_id=request_id,
                )
                _bounded(partial(_write, writer, encoded))
                return 2
            _bounded(partial(_write, writer, encoded))
            if isinstance(request, DisconnectRequest):
                return 0
        return 0
    except (Exception, KeyboardInterrupt):
        return 2
    finally:
        if terminal is not None:
            terminal.disconnect()


def main() -> int:
    if sys.argv[1:] != ["--synthetic-child"]:
        return 2
    return serve_synthetic(sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    raise SystemExit(main())
