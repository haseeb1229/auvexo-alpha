"""Real child-process and tamper negatives for fake, inspection-only local pipes."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from queue import Queue
from threading import Thread
from uuid import UUID, uuid4

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
from auvexo_alpha.infrastructure.gateway_ipc import (
    INSPECTION_ACCOUNT,
    MAX_FRAME_BYTES,
    PipeProtocolError,
    bootstrap_frame,
    decode_authenticated,
    encode_authenticated,
    fake_pipe_secret,
)


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


@pytest.fixture
def child() -> Iterator[tuple[subprocess.Popen[bytes], bytes, UUID]]:
    env = {**os.environ, "PYTHONPATH": str(Path.cwd() / "src")}
    process = subprocess.Popen(
        [sys.executable, "-m", "tools.offline_gateway"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    key = fake_pipe_secret()
    assert process.stdin is not None
    process.stdin.write(bootstrap_frame(key))
    process.stdin.flush()
    try:
        hello = decode_authenticated(
            _readline(process), key=key, session_id=None, expected_sequence=0
        )
        assert isinstance(hello.payload, GatewayHello)
        assert hello.payload.gateway_id == "synthetic.inspection-gateway"
        yield process, key, hello.payload.session_id
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        assert (
            process.stdin is not None and process.stdout is not None and process.stderr is not None
        )
        process.stdin.close()
        process.stdout.close()
        error = process.stderr.read()
        process.stderr.close()
        assert error == b""
        assert key.hex().encode() not in error


def _exchange(
    child: tuple[subprocess.Popen[bytes], bytes, UUID],
    request: GatewayMessage,
    sequence: int = 1,
    *,
    raw: bytes | None = None,
) -> GatewayMessage:
    process, key, session = child
    assert process.stdin is not None
    process.stdin.write(
        raw or encode_authenticated(request, key=key, session_id=session, sequence=sequence)
    )
    process.stdin.flush()
    return decode_authenticated(
        _readline(process), key=key, session_id=session, expected_sequence=sequence
    )


def test_real_process_health_and_empty_reconcile(
    child: tuple[subprocess.Popen[bytes], bytes, UUID],
) -> None:
    health = _exchange(child, message())
    assert isinstance(health.payload, GatewayHealth)
    assert health.payload.status == "RECONCILE_ONLY"
    snapshot = _exchange(child, message(GatewayReconcile()), sequence=2)
    assert isinstance(snapshot.payload, GatewaySnapshot)
    assert snapshot.payload.orders == snapshot.payload.deals == snapshot.payload.positions == ()
    assert snapshot.payload.cursor == 0


def test_process_duplicate_command_refused(
    child: tuple[subprocess.Popen[bytes], bytes, UUID],
) -> None:
    request = message()
    _exchange(child, request)
    reply = _exchange(child, request, sequence=2)
    assert isinstance(reply.payload, GatewayError) and reply.payload.code == "REPLAY"
    assert child[0].wait(timeout=10) == 2


def test_process_replayed_frame_refused(child: tuple[subprocess.Popen[bytes], bytes, UUID]) -> None:
    request = message()
    raw = encode_authenticated(request, key=child[1], session_id=child[2], sequence=1)
    _exchange(child, request, raw=raw)
    reply = _exchange(child, request, sequence=2, raw=raw)
    assert isinstance(reply.payload, GatewayError) and reply.payload.code == "REPLAY"
    assert child[0].wait(timeout=10) == 2


@pytest.mark.parametrize("tamper", ["key", "payload", "account", "release", "unicode_mac", "extra"])
def test_process_auth_tampering_redacted(
    child: tuple[subprocess.Popen[bytes], bytes, UUID],
    tamper: str,
) -> None:
    request = message()
    raw = encode_authenticated(request, key=child[1], session_id=child[2], sequence=1)
    frame = json.loads(raw)
    if tamper == "key":
        raw = encode_authenticated(request, key=fake_pipe_secret(), session_id=child[2], sequence=1)
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
    assert child[0].wait(timeout=10) == 2


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
def test_process_inspection_bindings(
    child: tuple[subprocess.Popen[bytes], bytes, UUID],
    changes: dict[str, object],
    code: str,
) -> None:
    reply = _exchange(child, message(**changes))
    assert isinstance(reply.payload, GatewayError) and reply.payload.code == code


def test_process_cannot_accept_acks_as_commands(
    child: tuple[subprocess.Popen[bytes], bytes, UUID],
) -> None:
    reply = _exchange(child, message(GatewayError(code="UNAVAILABLE")))
    assert isinstance(reply.payload, GatewayError) and reply.payload.code == "UNSUPPORTED"


def test_process_oversize_frame_closes_redacted(
    child: tuple[subprocess.Popen[bytes], bytes, UUID],
) -> None:
    reply = _exchange(child, message(), raw=b"x" * (MAX_FRAME_BYTES + 1) + b"\n")
    assert isinstance(reply.payload, GatewayError) and reply.payload.code == "INVALID_MESSAGE"
    assert child[0].wait(timeout=10) == 2


def test_new_process_session_rejects_previous_session(
    child: tuple[subprocess.Popen[bytes], bytes, UUID],
) -> None:
    # Even reuse of a valid HMAC key cannot make an old process session valid here.
    old_session = uuid4()
    raw = encode_authenticated(message(), key=child[1], session_id=old_session, sequence=1)
    reply = _exchange(child, message(), raw=raw)
    assert isinstance(reply.payload, GatewayError) and reply.payload.code == "REPLAY"
    assert child[0].wait(timeout=10) == 2


@pytest.mark.parametrize("raw", [b"[]", b"{}", b'{"x":1,"x":2}', b'{"x":NaN}', b"\xff"])
def test_frame_malformed(raw: bytes) -> None:
    with pytest.raises(PipeProtocolError, match="INVALID_MESSAGE"):
        decode_authenticated(raw, key=fake_pipe_secret(), session_id=uuid4(), expected_sequence=1)


def test_entire_envelope_auth_and_constant_time_compare(monkeypatch: pytest.MonkeyPatch) -> None:
    key, session = fake_pipe_secret(), uuid4()
    request = message()
    raw = encode_authenticated(request, key=key, session_id=session, sequence=1)
    calls: list[tuple[str, str]] = []
    original = hmac.compare_digest

    def compare(left: str, right: str) -> bool:
        calls.append((left, right))
        return original(left, right)

    monkeypatch.setattr(hmac, "compare_digest", compare)
    assert decode_authenticated(raw, key=key, session_id=session, expected_sequence=1) == request
    assert len(calls) == 1 and len(calls[0][0]) == 64
    frame = json.loads(raw)
    supplied = frame.pop("mac")
    canonical = json.dumps(
        frame, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode()
    assert supplied == hmac.new(key, canonical, hashlib.sha256).hexdigest()


def test_bootstrap_rejected_without_secret_disclosure() -> None:
    process = subprocess.run(
        [sys.executable, "-m", "tools.offline_gateway"],
        input=b'{"key":"sensitive-owner-text"}\n',
        capture_output=True,
        timeout=10,
        env={**os.environ, "PYTHONPATH": str(Path.cwd() / "src")},
    )
    assert process.returncode == 2
    assert process.stdout == process.stderr == b""


def test_real_process_typed_synthetic_attestation_and_spec(
    child: tuple[subprocess.Popen[bytes], bytes, UUID],
) -> None:
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


def test_real_process_dispatch_always_refused(
    child: tuple[subprocess.Popen[bytes], bytes, UUID],
) -> None:
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


def test_actual_process_restart_rejects_captured_session(
    child: tuple[subprocess.Popen[bytes], bytes, UUID],
) -> None:
    key, old_session = child[1:]
    captured = encode_authenticated(message(), key=key, session_id=old_session, sequence=1)
    second = subprocess.Popen(
        [sys.executable, "-m", "tools.offline_gateway"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "PYTHONPATH": str(Path.cwd() / "src")},
    )
    assert second.stdin is not None and second.stdout is not None and second.stderr is not None
    try:
        second.stdin.write(bootstrap_frame(key))
        second.stdin.flush()
        hello = decode_authenticated(
            _readline(second), key=key, session_id=None, expected_sequence=0
        )
        assert isinstance(hello.payload, GatewayHello)
        assert hello.payload.session_id != old_session
        second.stdin.write(captured)
        second.stdin.flush()
        reply = decode_authenticated(
            _readline(second),
            key=key,
            session_id=hello.payload.session_id,
            expected_sequence=1,
        )
        assert isinstance(reply.payload, GatewayError) and reply.payload.code == "REPLAY"
        assert second.wait(timeout=10) == 2
    finally:
        if second.poll() is None:
            second.kill()
        second.wait(timeout=10)
        second.stdin.close()
        second.stdout.close()
        assert second.stderr.read() == b""
        second.stderr.close()
