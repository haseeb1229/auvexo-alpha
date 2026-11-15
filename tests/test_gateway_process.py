"""Real child-process and tamper negatives for fake, inspection-only local pipes."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import partial
from pathlib import Path
from queue import Queue
from threading import Thread
from uuid import UUID, uuid4

import psutil
import pytest
from paper_fixtures import fixture_bundle

from auvexo_alpha.domain.contracts import InstrumentSpec, Mode, Product, Venue
from auvexo_alpha.domain.gateway import (
    AccountAttestation,
    GatewayDispatch,
    GatewayError,
    GatewayHealth,
    GatewayHello,
    GatewayInstrumentSnapshot,
    GatewayMessage,
    GatewayPayload,
    GatewayReconcile,
    GatewaySnapshot,
    build_message,
)
from auvexo_alpha.domain.paper import PaperReservation, bind_authorization
from auvexo_alpha.domain.paper_risk import assess_paper
from auvexo_alpha.infrastructure.ds03_mt5_binding import ProviderJob, provider_job
from auvexo_alpha.infrastructure.gateway_ipc import (
    IDLE_TIMEOUT_SECONDS,
    INSPECTION_ACCOUNT,
    MAX_FRAME_BYTES,
    Direction,
    PipeProtocolError,
    bootstrap_frame,
    decode_authenticated,
    encode_authenticated,
    fake_pipe_secret,
    serve_inspection,
)

P2C, C2P = Direction.PARENT_TO_CHILD, Direction.CHILD_TO_PARENT
_GATEWAY = [sys.executable, "-m", "tools.offline_gateway"]
# Test-only launcher with an injected short idle bound; the shipped tool takes no argument.
_IDLE_CHILD = [
    sys.executable,
    "-c",
    "import sys;from auvexo_alpha.infrastructure.gateway_ipc import serve_inspection;"
    "stdin=open(sys.stdin.fileno(),'rb',buffering=0,closefd=False);"
    "raise SystemExit(serve_inspection(stdin,sys.stdout.buffer,"
    "idle_timeout=float(sys.argv[1])))",
]
_SUSPENDED = 0x00000004


def _environment() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": str(Path.cwd() / "src")}


@dataclass(frozen=True)
class Child:
    process: subprocess.Popen[bytes]
    key: bytes
    channel: UUID
    session: UUID


def message(payload: GatewayPayload | None = None, **changes: object) -> GatewayMessage:
    now = datetime.now(UTC)
    result = build_message(
        payload or GatewayHealth(status="READY", observed_at=now),
        command_id=uuid4(),
        correlation_id=uuid4(),
        source_id="synthetic.test-client",
        account_ref=INSPECTION_ACCOUNT,
        mode=Mode.PAPER,
        writer_epoch=0,
        intent_hash="0" * 64,
        authorization_hash="0" * 64,
        reservation_hash="0" * 64,
        release_hash="0" * 64,
        config_hash="0" * 64,
        created_at=now,
        expires_at=now + timedelta(seconds=30),
    )
    # Strict validation after replacement preserves negative fixtures' valid contract shape.
    return GatewayMessage.model_validate_json(result.model_copy(update=changes).canonical_bytes())


def _readline(process: subprocess.Popen[bytes]) -> bytes:
    output: Queue[bytes] = Queue()
    assert process.stdout is not None
    reader = Thread(
        target=lambda: output.put(process.stdout.readline(MAX_FRAME_BYTES + 1)), daemon=True
    )
    reader.start()
    return output.get(timeout=10)


def _send(process: subprocess.Popen[bytes], raw: bytes) -> None:
    assert process.stdin is not None
    process.stdin.write(raw)
    process.stdin.flush()


def _launch(command: list[str]) -> tuple[subprocess.Popen[bytes], ProviderJob | None]:
    """Contain the child before its first instruction, as the child itself demands."""
    if sys.platform != "win32":
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_environment(),
        )
        return process, None
    job = provider_job()
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_environment(),
        creationflags=subprocess.CREATE_NO_WINDOW | _SUSPENDED,
    )
    try:
        job.assign(process)
    except BaseException:
        process.kill()
        process.wait(timeout=10)
        job.close()
        raise
    return process, job


def _close(process: subprocess.Popen[bytes], job: ProviderJob | None, key: bytes) -> None:
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    process.stdin.close()
    process.stdout.close()
    error = process.stderr.read()
    process.stderr.close()
    if job is not None:
        job.close()
    assert error == b""
    assert key.hex().encode() not in error


def _hello(process: subprocess.Popen[bytes], key: bytes, channel: UUID) -> UUID:
    hello = decode_authenticated(
        _readline(process),
        key=key,
        channel=channel,
        session_id=None,
        expected_sequence=0,
        direction=C2P,
    )
    assert isinstance(hello.payload, GatewayHello)
    assert hello.payload.gateway_id == "synthetic.inspection-gateway"
    return hello.payload.session_id


@pytest.fixture
def child() -> Iterator[Child]:
    key, channel = fake_pipe_secret(), uuid4()
    process, job = _launch(_GATEWAY)
    try:
        _send(process, bootstrap_frame(key, channel, job.name if job else None))
        yield Child(process, key, channel, _hello(process, key, channel))
    finally:
        _close(process, job, key)


def _frame(
    child: Child,
    request: GatewayMessage,
    sequence: int = 1,
    *,
    direction: Direction = P2C,
    channel: UUID | None = None,
    session: UUID | None = None,
) -> bytes:
    return encode_authenticated(
        request,
        key=child.key,
        channel=channel or child.channel,
        session_id=session or child.session,
        sequence=sequence,
        direction=direction,
    )


def _reply(child: Child, sequence: int) -> GatewayMessage:
    return decode_authenticated(
        _readline(child.process),
        key=child.key,
        channel=child.channel,
        session_id=child.session,
        expected_sequence=sequence,
        direction=C2P,
    )


def _exchange(
    child: Child,
    request: GatewayMessage,
    sequence: int = 1,
    *,
    raw: bytes | None = None,
) -> GatewayMessage:
    _send(child.process, raw or _frame(child, request, sequence))
    return _reply(child, sequence)


def test_real_process_health_and_empty_reconcile(child: Child) -> None:
    health = _exchange(child, message())
    assert isinstance(health.payload, GatewayHealth)
    assert health.payload.status == "RECONCILE_ONLY"
    snapshot = _exchange(child, message(GatewayReconcile()), sequence=2)
    assert isinstance(snapshot.payload, GatewaySnapshot)
    assert snapshot.payload.orders == snapshot.payload.deals == snapshot.payload.positions == ()
    assert snapshot.payload.cursor == 0


def test_process_duplicate_command_refused(child: Child) -> None:
    request = message()
    _exchange(child, request)
    reply = _exchange(child, request, sequence=2)
    assert isinstance(reply.payload, GatewayError) and reply.payload.code == "REPLAY"
    assert child.process.wait(timeout=10) == 2


def test_process_replayed_frame_refused(child: Child) -> None:
    request = message()
    raw = _frame(child, request)
    _exchange(child, request, raw=raw)
    reply = _exchange(child, request, sequence=2, raw=raw)
    assert isinstance(reply.payload, GatewayError) and reply.payload.code == "REPLAY"
    assert child.process.wait(timeout=10) == 2


def test_direction_is_inside_the_mac() -> None:
    key, channel, session = fake_pipe_secret(), uuid4(), uuid4()
    request = message()
    raw = encode_authenticated(
        request, key=key, channel=channel, session_id=session, sequence=1, direction=P2C
    )
    decode = partial(
        decode_authenticated, key=key, channel=channel, session_id=session, expected_sequence=1
    )
    assert decode(raw, direction=P2C) == request
    with pytest.raises(PipeProtocolError, match="REPLAY"):
        decode(raw, direction=C2P)
    # Relabelling the direction breaks the MAC instead of moving the frame to the other pipe.
    frame = json.loads(raw)
    frame["direction"] = C2P.value
    with pytest.raises(PipeProtocolError, match="UNAUTHORIZED"):
        decode(json.dumps(frame).encode() + b"\n", direction=C2P)


def test_frame_reflected_to_its_sender_refused(child: Child) -> None:
    # A pipe adversary echoes the parent's own authentic request back as the awaited reply.
    request_raw = _frame(child, message())
    with pytest.raises(PipeProtocolError, match="REPLAY"):
        decode_authenticated(
            request_raw,
            key=child.key,
            channel=child.channel,
            session_id=child.session,
            expected_sequence=1,
            direction=C2P,
        )
    _send(child.process, request_raw)
    reply_raw = _readline(child.process)
    reply = decode_authenticated(
        reply_raw,
        key=child.key,
        channel=child.channel,
        session_id=child.session,
        expected_sequence=1,
        direction=C2P,
    )
    assert isinstance(reply.payload, GatewayHealth)
    # ...and echoes the child's own authentic reply back into the child.
    refused = _exchange(child, message(), sequence=2, raw=reply_raw)
    assert isinstance(refused.payload, GatewayError) and refused.payload.code == "REPLAY"
    assert child.process.wait(timeout=10) == 2


def test_frame_replayed_in_the_other_direction_refused(child: Child) -> None:
    # Authentic key, channel, session and the exact awaited sequence: only direction differs.
    raw = _frame(child, message(), direction=C2P)
    reply = _exchange(child, message(), raw=raw)
    assert isinstance(reply.payload, GatewayError) and reply.payload.code == "REPLAY"
    assert child.process.wait(timeout=10) == 2


def test_frame_from_another_launch_channel_refused(child: Child) -> None:
    raw = _frame(child, message(), channel=uuid4())
    reply = _exchange(child, message(), raw=raw)
    assert isinstance(reply.payload, GatewayError) and reply.payload.code == "REPLAY"
    assert child.process.wait(timeout=10) == 2


def test_parent_refuses_hello_from_another_launch(child: Child) -> None:
    # Even with a reused key, a different launch's hello never binds this parent.
    channel = uuid4()
    process, job = _launch(_GATEWAY)
    try:
        _send(process, bootstrap_frame(child.key, channel, job.name if job else None))
        raw = _readline(process)
        with pytest.raises(PipeProtocolError, match="REPLAY"):
            decode_authenticated(
                raw,
                key=child.key,
                channel=child.channel,
                session_id=None,
                expected_sequence=0,
                direction=C2P,
            )
        hello = decode_authenticated(
            raw,
            key=child.key,
            channel=channel,
            session_id=None,
            expected_sequence=0,
            direction=C2P,
        )
        assert isinstance(hello.payload, GatewayHello)
        assert hello.payload.session_id != child.session
        # The parent-side hello path cannot be used to read the parent's own pipe.
        with pytest.raises(PipeProtocolError, match="REPLAY"):
            decode_authenticated(
                raw,
                key=child.key,
                channel=channel,
                session_id=None,
                expected_sequence=0,
                direction=P2C,
            )
    finally:
        _close(process, job, child.key)


@pytest.mark.parametrize("tamper", ["key", "payload", "account", "release", "unicode_mac", "extra"])
def test_process_auth_tampering_redacted(child: Child, tamper: str) -> None:
    request = message()
    raw = _frame(child, request)
    frame = json.loads(raw)
    if tamper == "key":
        raw = encode_authenticated(
            request,
            key=fake_pipe_secret(),
            channel=child.channel,
            session_id=child.session,
            sequence=1,
            direction=P2C,
        )
    else:
        if tamper == "payload":
            frame["message"]["payload"]["status"] = "DISCONNECTED"
        elif tamper == "account":
            frame["message"]["account_ref"] = "paper.other"
        elif tamper == "release":
            frame["message"]["release_hash"] = "a" * 64
        elif tamper == "unicode_mac":
            frame["mac"] = "é" * 64
        else:
            frame["secret_owner_input"] = "sensitive-owner-text"
        raw = json.dumps(frame).encode() + b"\n"
    reply = _exchange(child, request, raw=raw)
    assert isinstance(reply.payload, GatewayError)
    assert reply.payload.code in ("UNAUTHORIZED", "INVALID_MESSAGE")
    assert b"sensitive-owner-text" not in reply.canonical_bytes()
    assert child.process.wait(timeout=10) == 2


@pytest.mark.parametrize(
    "changes, code",
    [
        ({"account_ref": "paper.other"}, "BINDING_DENIED"),
        ({"mode": Mode.DEMO}, "BINDING_DENIED"),
        ({"release_hash": "a" * 64}, "BINDING_DENIED"),
        ({"config_hash": "a" * 64}, "BINDING_DENIED"),
        ({"writer_epoch": 1}, "BINDING_DENIED"),
        (
            {
                "created_at": datetime.now(UTC) - timedelta(seconds=60),
                "expires_at": datetime.now(UTC) - timedelta(seconds=30),
            },
            "EXPIRED",
        ),
    ],
)
def test_process_inspection_bindings(child: Child, changes: dict[str, object], code: str) -> None:
    reply = _exchange(child, message(**changes))
    assert isinstance(reply.payload, GatewayError) and reply.payload.code == code


def test_process_cannot_accept_acks_as_commands(child: Child) -> None:
    reply = _exchange(child, message(GatewayError(code="UNAVAILABLE")))
    assert isinstance(reply.payload, GatewayError) and reply.payload.code == "UNSUPPORTED"


def test_process_oversize_frame_closes_redacted(child: Child) -> None:
    reply = _exchange(child, message(), raw=b"x" * (MAX_FRAME_BYTES + 1) + b"\n")
    assert isinstance(reply.payload, GatewayError) and reply.payload.code == "INVALID_MESSAGE"
    assert child.process.wait(timeout=10) == 2


def test_new_process_session_rejects_previous_session(child: Child) -> None:
    # Even reuse of a valid HMAC key cannot make an old process session valid here.
    raw = _frame(child, message(), session=uuid4())
    reply = _exchange(child, message(), raw=raw)
    assert isinstance(reply.payload, GatewayError) and reply.payload.code == "REPLAY"
    assert child.process.wait(timeout=10) == 2


@pytest.mark.parametrize("raw", [b"[]", b"{}", b'{"x":1,"x":2}', b'{"x":NaN}', b"\xff"])
def test_frame_malformed(raw: bytes) -> None:
    with pytest.raises(PipeProtocolError, match="INVALID_MESSAGE"):
        decode_authenticated(
            raw,
            key=fake_pipe_secret(),
            channel=uuid4(),
            session_id=uuid4(),
            expected_sequence=1,
            direction=P2C,
        )


def test_entire_envelope_auth_and_constant_time_compare(monkeypatch: pytest.MonkeyPatch) -> None:
    key, channel, session = fake_pipe_secret(), uuid4(), uuid4()
    request = message()
    raw = encode_authenticated(
        request, key=key, channel=channel, session_id=session, sequence=1, direction=P2C
    )
    calls: list[tuple[str, str]] = []
    original = hmac.compare_digest

    def compare(left: str, right: str) -> bool:
        calls.append((left, right))
        return original(left, right)

    monkeypatch.setattr(hmac, "compare_digest", compare)
    decoded = decode_authenticated(
        raw, key=key, channel=channel, session_id=session, expected_sequence=1, direction=P2C
    )
    assert decoded == request
    assert len(calls) == 1 and len(calls[0][0]) == 64
    frame = json.loads(raw)
    supplied = frame.pop("mac")
    assert set(frame) == {"version", "direction", "channel", "session_id", "sequence", "message"}
    canonical = json.dumps(
        frame, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode()
    assert supplied == hmac.new(key, canonical, hashlib.sha256).hexdigest()


def test_bootstrap_rejected_without_secret_disclosure() -> None:
    process = subprocess.run(
        _GATEWAY,
        input=b'{"key":"sensitive-owner-text"}\n',
        capture_output=True,
        timeout=10,
        env=_environment(),
    )
    assert process.returncode == 2
    assert process.stdout == process.stderr == b""


@pytest.mark.parametrize("case", ["nonexistent", "foreign_name", "absent"])
def test_child_refuses_to_serve_outside_its_parent_job(case: str) -> None:
    # Launched uncontained: a nonexistent, foreign or absent Job is refused before hello.
    if case == "absent" and sys.platform != "win32":
        pytest.skip("only Windows demands a Job; elsewhere an absent Job is the protocol")
    job_name = {
        "nonexistent": "Local" + chr(92) + "AuvexoAlphaDS03Readonly-" + uuid4().hex,
        "foreign_name": "Global" + chr(92) + "unrelated",
        "absent": None,
    }[case]
    process = subprocess.Popen(
        _GATEWAY,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_environment(),
    )
    key = fake_pipe_secret()
    try:
        _send(process, bootstrap_frame(key, uuid4(), job_name))
        assert process.wait(timeout=10) == 2
        assert process.stdout is not None and process.stdout.read() == b""
    finally:
        _close(process, None, key)


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows Job Object proof")
def test_child_refuses_a_real_job_it_was_not_assigned_to() -> None:
    with provider_job() as foreign:
        process = subprocess.Popen(
            _GATEWAY,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_environment(),
        )
        key = fake_pipe_secret()
        try:
            _send(process, bootstrap_frame(key, uuid4(), foreign.name))
            assert process.wait(timeout=10) == 2
            assert process.stdout is not None and process.stdout.read() == b""
        finally:
            _close(process, None, key)


# The holder is the parent: it alone owns the Job handle, and the test kills it abruptly.
_HOLDER = (
    "import os,subprocess,sys,threading;"
    "from auvexo_alpha.infrastructure.ds03_mt5_binding import provider_job;"
    "job=provider_job();print(os.getpid(),job.name,flush=True);"
    "p=subprocess.Popen([sys.executable,'-m','tools.offline_gateway'],"
    "stdin=sys.stdin.fileno(),stdout=sys.stdout.fileno(),stderr=subprocess.DEVNULL,"
    "creationflags=subprocess.CREATE_NO_WINDOW|4);"
    "job.assign(p);threading.Event().wait()"
)


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows Job Object proof")
def test_child_dies_when_the_parent_job_handle_closes() -> None:
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLDER],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_environment(),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    key, channel = fake_pipe_secret(), uuid4()
    started: list[psutil.Process] = []
    try:
        pid, job_name = _readline(holder).decode("ascii").split()
        parent = psutil.Process(int(pid))
        started.append(parent)
        _send(holder, bootstrap_frame(key, channel, job_name))
        served = Child(holder, key, channel, _hello(holder, key, channel))
        health = _exchange(served, message())
        assert isinstance(health.payload, GatewayHealth)
        gateway = [p for p in parent.children(recursive=True) if p.name().lower() == "python.exe"]
        assert gateway
        started.extend(gateway)
        killed_at = time.monotonic()
        # TerminateProcess runs no parent cleanup and no TerminateJobObject: the OS closes
        # the parent's only Job handle, and KILL_ON_JOB_CLOSE must end the whole child tree.
        parent.kill()
        _, alive = psutil.wait_procs(gateway, timeout=10)
        assert alive == []
        assert time.monotonic() - killed_at < IDLE_TIMEOUT_SECONDS
        # This test still holds the child's stdin writer, so pipe EOF did not end it.
        assert holder.stdin is not None and not holder.stdin.closed
        assert _readline(holder) == b""
    finally:
        for process in started:
            if process.is_running():
                process.kill()
        _close(holder, None, key)


def test_child_idle_timeout_records_reason_and_exits_cleanly() -> None:
    key, channel, idle = fake_pipe_secret(), uuid4(), 2.0
    process, job = _launch([*_IDLE_CHILD, str(idle)])
    try:
        _send(process, bootstrap_frame(key, channel, job.name if job else None))
        served = Child(process, key, channel, _hello(process, key, channel))
        # Each valid frame restarts the bound: these exchanges outlast one idle interval.
        for sequence in (1, 2, 3):
            time.sleep(idle / 2)
            reply = _exchange(served, message(), sequence=sequence)
            assert isinstance(reply.payload, GatewayHealth)
        waited_from = time.monotonic()
        timed_out = _reply(served, 4)
        assert time.monotonic() - waited_from >= idle / 2
        assert isinstance(timed_out.payload, GatewayError)
        assert timed_out.payload.code == "IDLE_TIMEOUT"
        assert timed_out.causation_id is None
        assert process.wait(timeout=10) == 0
        assert process.stdin is not None and not process.stdin.closed
    finally:
        _close(process, job, key)


def test_child_idle_before_bootstrap_exits_without_output() -> None:
    key = fake_pipe_secret()
    process, job = _launch([*_IDLE_CHILD, "1.0"])
    try:
        assert process.wait(timeout=10) == 2
        assert process.stdout is not None and process.stdout.read() == b""
    finally:
        _close(process, job, key)


@pytest.mark.parametrize("idle", [0.0, -1.0, IDLE_TIMEOUT_SECONDS + 1, float("inf")])
def test_idle_bound_cannot_be_disabled(idle: float) -> None:
    with pytest.raises(ValueError, match="IDLE_TIMEOUT"):
        serve_inspection(io.BytesIO(), io.BytesIO(), idle_timeout=idle)


def test_real_process_typed_synthetic_attestation_and_spec(child: Child) -> None:
    now = datetime.now(UTC)
    attestation = AccountAttestation(
        account_ref=INSPECTION_ACCOUNT,
        venue=Venue.BINANCE,
        server="synthetic.request",
        account_identifier="synthetic.request",
        account_kind="DEMO",
        currency="USDT",
        account_mode="NETTING",
        observed_at=now,
        capability_hash="0" * 64,
    )
    reply = _exchange(child, message(attestation))
    assert isinstance(reply.payload, AccountAttestation)
    assert reply.payload.account_identifier == "synthetic.no-broker-account"
    assert reply.payload.server == "synthetic.offline"
    assert (
        reply.payload.capability_hash == hashlib.sha256(b"INSPECTION_ONLY_NO_DISPATCH").hexdigest()
    )
    spec = GatewayInstrumentSnapshot(
        spec=InstrumentSpec(
            instrument_id="synthetic.BTCUSDT",
            venue=Venue.BINANCE,
            product=Product.SPOT,
            symbol="synthetic.BTCUSDT",
            base_currency="BTC",
            quote_currency="USDT",
            quantity_unit="BASE_UNIT",
            contract_multiplier=Decimal("1"),
            price_tick=Decimal("0.01"),
            quantity_step=Decimal("0.00001"),
            min_quantity=Decimal("0.00001"),
            max_quantity=Decimal("1"),
            spec_version="synthetic.request",
            observed_at=now,
        ),
        supported_fill=("IOC",),
    )
    reply = _exchange(child, message(spec), sequence=2)
    assert isinstance(reply.payload, GatewayInstrumentSnapshot)
    assert reply.payload.spec.spec_version == "synthetic.inspection.v1"
    assert reply.payload.spec.symbol == "synthetic.BTCUSDT"
    assert reply.payload.supported_fill == ("IOC",)


def test_real_process_dispatch_always_refused(child: Child) -> None:
    b = fixture_bundle(account_ref=INSPECTION_ACCOUNT, now=datetime.now(UTC))
    decision = assess_paper(
        b.intent, b.policy, b.market, b.spec, b.account, b.release, (), now=b.now
    )
    assert decision.exposure is not None
    e = decision.exposure
    reservation = PaperReservation(
        reservation_id=uuid4(),
        intent_hash=b.intent.content_hash(),
        logical_key=b.intent.logical_key,
        account_ref=b.intent.account_ref,
        instrument_id=b.intent.instrument_id,
        bucket=e.bucket,
        action=b.intent.action,
        intent_id=b.intent.intent_id,
        quantity=e.quantity,
        notional=e.notional,
        modeled_loss=e.modeled_loss,
        margin=e.margin_required,
        created_at=b.now,
        expires_at=b.intent.expires_at,
    )
    authorization = bind_authorization(
        decision, b.intent, b.account, reservation.reservation_id, uuid4(), b.now
    )
    dispatch = GatewayDispatch(
        intent=b.intent, authorization=authorization, reservation=reservation
    )
    request = build_message(
        dispatch,
        command_id=uuid4(),
        correlation_id=uuid4(),
        source_id="synthetic.test-client",
        account_ref=INSPECTION_ACCOUNT,
        mode=Mode.PAPER,
        writer_epoch=authorization.writer_epoch,
        intent_hash=b.intent.content_hash(),
        authorization_hash=authorization.content_hash(),
        reservation_hash=reservation.content_hash(),
        release_hash=b.intent.release_hash,
        config_hash="0" * 64,
        created_at=b.now,
        expires_at=authorization.expires_at,
    )
    reply = _exchange(child, request)
    assert isinstance(reply.payload, GatewayError) and reply.payload.code == "UNSUPPORTED"
    reply = _exchange(child, message(GatewayReconcile()), sequence=2)
    assert isinstance(reply.payload, GatewaySnapshot)
    assert reply.payload.orders == reply.payload.deals == reply.payload.positions == ()


def test_actual_process_restart_rejects_captured_session(child: Child) -> None:
    # Same key and the same parent channel: only the child's fresh session differs.
    captured = _frame(child, message())
    process, job = _launch(_GATEWAY)
    try:
        _send(process, bootstrap_frame(child.key, child.channel, job.name if job else None))
        session = _hello(process, child.key, child.channel)
        assert session != child.session
        _send(process, captured)
        reply = decode_authenticated(
            _readline(process),
            key=child.key,
            channel=child.channel,
            session_id=session,
            expected_sequence=1,
            direction=C2P,
        )
        assert isinstance(reply.payload, GatewayError) and reply.payload.code == "REPLAY"
        assert process.wait(timeout=10) == 2
    finally:
        _close(process, job, child.key)
