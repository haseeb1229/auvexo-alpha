"""Real isolated child, bounded IO and fail-closed recovery proofs; synthetic only."""

from __future__ import annotations

import io
import os
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import UUID, uuid4

import pytest

from auvexo_alpha.domain.ds03 import (
    MAX_FRAME_BYTES,
    Ds03Error,
    Ds03Request,
    SpecPayload,
    SymbolsPayload,
    TickPayload,
    request_adapter,
)
from auvexo_alpha.infrastructure import ds03_process as module
from auvexo_alpha.infrastructure.ds03_fake import SyntheticDs03Terminal, synthetic_identity
from auvexo_alpha.infrastructure.ds03_ipc import (
    bootstrap_frame,
    decode_frame,
    encode_frame,
    new_pipe_key,
)
from auvexo_alpha.infrastructure.ds03_process import Ds03Process, serve_synthetic, source_binding


def request(operation: str, **fields: object) -> Ds03Request:
    now, identity = datetime.now(UTC), synthetic_identity()
    return request_adapter.validate_python(
        {
            "operation": operation,
            "request_id": uuid4(),
            "created_at": now,
            "expires_at": now + timedelta(seconds=10),
            "release_hash": identity.release_hash,
            "config_hash": identity.config_hash,
            **fields,
        }
    )


def _frames(
    raw_requests: list[tuple[Ds03Request, int, UUID | None]], *, key: bytes, session: UUID
) -> bytes:
    raw = bootstrap_frame(key, session, source_binding())
    for message, sequence, request_id in raw_requests:
        raw += encode_frame(
            "REQUEST",
            message.model_dump(mode="json"),
            key=key,
            session=session,
            sequence=sequence,
            request_id=request_id if request_id is not None else message.request_id,
        )
    return raw


def test_real_child_reads_every_allowed_shape_then_disconnects() -> None:
    with Ds03Process() as child:
        assert child._process is not None and child._process.pid != os.getpid()
        assert child.attest().identity == synthetic_identity()
        symbols = child.read(request("SYMBOLS"))
        assert isinstance(symbols.payload, SymbolsPayload)
        assert symbols.payload.symbols == ("synthetic.BTCUSDm", "synthetic.ETHUSDm")
        symbol = symbols.payload.symbols[0]
        spec = child.read(request("SPEC", symbol=symbol))
        assert isinstance(spec.payload, SpecPayload)
        assert spec.payload.spec.sessions is None and spec.payload.spec.history_start is None
        tick = child.read(request("TICK", symbol=symbol))
        assert isinstance(tick.payload, TickPayload)
        assert tick.envelope.spec_hash == spec.payload.spec.content_hash()
        assert tick.envelope.clock_status == "STRUCTURAL_ONLY_CLOCK_BLOCKED"
        end = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=1)
        start = end - timedelta(minutes=5)
        bars = child.read(
            request("BARS", symbol=symbol, start=start, end=end, limit=2, timeframe_seconds=60)
        )
        assert bars.payload.kind == "BARS" and bars.payload.coverage == "PARTIAL"
        assert len(bars.payload.bars) == 2 and len(bars.payload.gaps) == 1
        ticks = child.read(request("TICKS", symbol=symbol, start=start, end=end, limit=2))
        assert ticks.payload.kind == "TICKS" and ticks.payload.coverage == "UNKNOWN"
        assert child.read(request("ORDERS")).payload.kind == "ORDERS"
        assert child.read(request("POSITIONS")).payload.kind == "POSITIONS"
        assert child.read(request("DEALS", start=start, end=end, limit=2)).payload.kind == "DEALS"
        assert (
            child.read(request("ORDER_HISTORY", start=start, end=end, limit=2)).payload.kind
            == "ORDER_HISTORY"
        )
        child.disconnect()
        assert child._process is None
        child.disconnect()


def test_duplicate_request_closes_process_before_second_read() -> None:
    with Ds03Process() as child:
        message = request("SYMBOLS")
        child.read(message)
        with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE$"):
            child.read(message)
        assert child._process is None


def test_real_connector_crash_requires_fresh_authenticated_session() -> None:
    child = Ds03Process().start()
    original_session = child._session
    assert child._process is not None
    child._process.kill()
    child._process.wait(timeout=2)
    with pytest.raises(Ds03Error):
        child.read(request("SYMBOLS"))
    assert child._process is None
    with child:
        assert child._session != original_session
        assert isinstance(child.read(request("SYMBOLS")).payload, SymbolsPayload)
        child.disconnect()


@pytest.mark.parametrize("symbol", ["synthetic.XAUUSD", "synthetic.BTCUSD", "synthetic.ABSENT"])
def test_absent_symbol_or_assumed_suffix_is_refused(symbol: str) -> None:
    with Ds03Process() as child:
        child.read(request("SYMBOLS"))
        with pytest.raises(Ds03Error):
            child.read(request("SPEC", symbol=symbol))
        assert child._process is None


def test_server_replay_sequence_and_duplicate_id_close() -> None:
    for duplicate_id in (False, True):
        key, session, message = new_pipe_key(), uuid4(), request("SYMBOLS")
        rows = [(message, 1, None), (message, 2 if duplicate_id else 1, None)]
        output = io.BytesIO()
        assert serve_synthetic(io.BytesIO(_frames(rows, key=key, session=session)), output) == 2
        lines = output.getvalue().splitlines(keepends=True)
        assert len(lines) == 3
        assert decode_frame(
            lines[2], key=key, session=session, sequence=2, kind="ERROR"
        ).payload == {"code": "DS03_UNAVAILABLE"}


def test_server_request_id_correlation_mismatch_refused() -> None:
    key, session, message = new_pipe_key(), uuid4(), request("SYMBOLS")
    output = io.BytesIO()
    assert (
        serve_synthetic(
            io.BytesIO(_frames([(message, 1, uuid4())], key=key, session=session)), output
        )
        == 2
    )
    lines = output.getvalue().splitlines(keepends=True)
    assert decode_frame(lines[-1], key=key, session=session, sequence=1, kind="ERROR").payload == {
        "code": "DS03_UNAVAILABLE"
    }


def test_timeout_discards_partial_output_and_invalidates_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = Ds03Process().start()
    released = Event()

    def stalled(reader: object, writer: object, raw: bytes) -> bytes:
        released.wait(timeout=1)
        return b"partial-untrusted-output"

    monkeypatch.setattr(module, "_IO_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(module, "_exchange", stalled)
    try:
        with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE$"):
            child.read(request("SYMBOLS"))
        assert child._process is None
    finally:
        released.set()
        child.close()


def test_concurrent_request_latches_process_closed() -> None:
    with Ds03Process() as child:
        assert child._lock.acquire(blocking=False)
        try:
            with pytest.raises(Ds03Error):
                child.read(request("SYMBOLS"))
            assert child._process is None
        finally:
            child._lock.release()


def test_read_without_bootstrap_and_session_quota_refuse(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(Ds03Error):
        Ds03Process().read(request("SYMBOLS"))
    with Ds03Process() as child:
        monkeypatch.setattr(module, "MAX_REQUESTS", 1)
        child.read(request("SYMBOLS"))
        with pytest.raises(Ds03Error):
            child.attest()
        assert child._process is None


def test_deadline_close_cannot_return_completed_stale_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Ds03Process() as child:
        original = module._exchange

        def closing(reader: object, writer: object, raw: bytes) -> bytes:
            # Same-user lifecycle invalidation during IO must not return prior output.
            reply = original(reader, writer, raw)
            child.close()
            return reply

        monkeypatch.setattr(module, "_exchange", closing)
        with pytest.raises(Ds03Error):
            child.read(request("SYMBOLS"))
        assert child._process is None


def test_fixed_launcher_rejects_options_and_filters_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHONPATH", "synthetic.injection")
    monkeypatch.setenv("PYTHONHOME", "synthetic.injection")
    monkeypatch.setenv("DS03_FAKE_SECRET", "synthetic.secret.marker")
    assert set(name.upper() for name in module._child_environment()) <= {"SYSTEMROOT", "WINDIR"}
    with pytest.raises(TypeError):
        Ds03Process(executable="synthetic.arbitrary")
    with pytest.raises(TypeError):
        Ds03Process().start(backend="synthetic.arbitrary")
    with Ds03Process() as child:
        assert child.attest().identity == synthetic_identity()
        child.disconnect()


def test_bounded_reader_never_requests_unlimited_bytes() -> None:
    class Oversize(io.BytesIO):
        def readline(self, size: int = -1) -> bytes:
            assert size == MAX_FRAME_BYTES + 1
            return b"x" * size

    with pytest.raises(ValueError, match="^DS03_UNAVAILABLE$"):
        module._read(Oversize())


def test_history_empty_payload_query_scope_and_first_seen_are_preserved() -> None:
    from auvexo_alpha.application.ds03 import Ds03Reader
    from auvexo_alpha.infrastructure.ds03_fake import synthetic_rights

    backend = SyntheticDs03Terminal()
    service = Ds03Reader(
        backend, synthetic_identity(), synthetic_rights(), clock=lambda: datetime.now(UTC)
    )
    end = datetime.now(UTC) - timedelta(seconds=2)
    first = request("DEALS", start=end - timedelta(minutes=2), end=end, limit=2)
    reply1 = service.read(first, now=datetime.now(UTC))
    repeated = request("DEALS", start=first.start, end=first.end, limit=2)
    reply2 = service.read(repeated, now=datetime.now(UTC))
    assert reply1.envelope.raw_hash == reply2.envelope.raw_hash
    assert reply1.envelope.first_seen_at == reply2.envelope.first_seen_at
    end2 = datetime.now(UTC) - timedelta(seconds=1)
    reply3 = service.read(
        request("DEALS", start=end2 - timedelta(minutes=2), end=end2, limit=2),
        now=datetime.now(UTC),
    )
    assert reply3.envelope.raw_hash != reply2.envelope.raw_hash
    backend.disconnect()


def test_expired_request_denied_before_backend_and_remaining_lifetime_bounds_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from time import monotonic

    with Ds03Process() as child:
        expired = request(
            "SYMBOLS",
            created_at=datetime.now(UTC) - timedelta(seconds=2),
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        with pytest.raises(Ds03Error):
            child.read(expired)
        assert child._process is None
    child = Ds03Process().start()
    released = Event()

    def stalled(reader: object, writer: object, raw: bytes) -> bytes:
        released.wait(timeout=1)
        return b"partial-untrusted-output"

    monkeypatch.setattr(module, "_exchange", stalled)
    try:
        message = request("SYMBOLS", expires_at=datetime.now(UTC) + timedelta(milliseconds=50))
        started = monotonic()
        with pytest.raises(Ds03Error):
            child.read(message)
        assert monotonic() - started < 2
        assert child._process is None
    finally:
        released.set()
        child.close()


def test_acknowledged_shutdown_uses_same_remaining_request_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    with Ds03Process() as child:
        process = child._process
        assert process is not None
        original = process.wait
        shutdown_budgets: list[float] = []

        def wait_with_simulated_clean_exit(timeout: float | None = None) -> int:
            # Simulate a native process requiring 2.5s to exit without sleeping:
            # it is within the frozen 10s request budget, beyond the old 2s cutoff.
            if not shutdown_budgets:
                assert timeout is not None
                shutdown_budgets.append(timeout)
                if timeout < 2.5:
                    raise subprocess.TimeoutExpired("synthetic-child", timeout)
            return original(timeout=timeout)

        monkeypatch.setattr(process, "wait", wait_with_simulated_clean_exit)
        child.disconnect()
        assert shutdown_budgets and 2.5 <= shutdown_budgets[0] <= 10
        assert child._process is None
