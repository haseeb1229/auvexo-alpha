"""Authenticated inherited-pipe framing for an inspection-only synthetic process.

The bootstrap key is generated for each local launch and travels only through its
inherited anonymous stdin pipe. It is a fake local authentication secret, never a
broker credential. The child accepts no state-changing command. Synthetic dispatch
belongs exclusively to the durable PAPER coordinator, not this inspection process.

Every frame MAC covers its direction, the parent's per-launch channel nonce, the child's
fresh session identity and the per-direction sequence, so a frame is valid only on the
one pipe, launch and position it was written for: reflection to its sender, replay in
the other direction and replay from another launch are all refused. On Windows the child
serves only inside the parent's exact kill-on-close, no-breakaway Job Object.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from queue import Empty, Queue
from threading import Thread
from typing import BinaryIO, cast
from uuid import UUID, uuid4

from auvexo_alpha.domain.contracts import InstrumentSpec, Mode, Product, Venue
from auvexo_alpha.domain.ds03_actual import Ds03Refusal
from auvexo_alpha.domain.gateway import (
    MAX_MESSAGE_BYTES,
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
    decode_message,
)
from auvexo_alpha.infrastructure.ds03_mt5_binding import (
    _current_job_pids,
    _validate_job_name,
)

MAX_FRAME_BYTES = MAX_MESSAGE_BYTES + 1024
MAX_INSPECTION_REQUESTS = 256
IDLE_TIMEOUT_SECONDS = 30.0
INSPECTION_ACCOUNT = "paper.offline-inspection"
_PROTOCOL = "synthetic-inspection.v2"
_FRAME_VERSION = 2
_ZERO_HASH = "0" * 64


class Direction(StrEnum):
    """Authenticated pipe direction; a frame never verifies on the opposite pipe."""

    PARENT_TO_CHILD = "PARENT_TO_CHILD"
    CHILD_TO_PARENT = "CHILD_TO_PARENT"


class PipeProtocolError(ValueError):
    """A stable redacted code; never expose input or authentication material."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PipeProtocolError("INVALID_MESSAGE")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise PipeProtocolError("INVALID_MESSAGE")


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("ascii")
    except (ValueError, TypeError, RecursionError) as error:
        raise PipeProtocolError("INVALID_MESSAGE") from error


def _load(raw: bytes) -> dict[str, object]:
    if not 0 < len(raw) <= MAX_FRAME_BYTES:
        raise PipeProtocolError("INVALID_MESSAGE")
    try:
        value: object = json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
        )
    except (ValueError, UnicodeError, RecursionError) as error:
        raise PipeProtocolError("INVALID_MESSAGE") from error
    if not isinstance(value, dict):
        raise PipeProtocolError("INVALID_MESSAGE")
    return cast(dict[str, object], value)


def _uuid(value: object) -> UUID:
    if not isinstance(value, str):
        raise PipeProtocolError("INVALID_MESSAGE")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise PipeProtocolError("INVALID_MESSAGE") from error
    if str(parsed) != value:
        raise PipeProtocolError("INVALID_MESSAGE")
    return parsed


def fake_pipe_secret() -> bytes:
    """Generate ephemeral local IPC key material; no credential-store integration."""
    return secrets.token_bytes(32)


def bootstrap_frame(key: bytes, channel: UUID, job_name: str | None) -> bytes:
    """Parent-only first line: key, fresh per-launch channel nonce and containment Job."""
    if not isinstance(key, bytes) or len(key) != 32 or not isinstance(channel, UUID):
        raise PipeProtocolError("UNAUTHORIZED")
    if job_name is not None and not isinstance(job_name, str):
        raise PipeProtocolError("UNAUTHORIZED")
    value = {"protocol": _PROTOCOL, "key": key.hex(), "channel": str(channel), "job": job_name}
    return _canonical(value) + b"\n"


def _bootstrap(raw: bytes) -> tuple[bytes, UUID, str | None]:
    value = _load(raw)
    if set(value) != {"protocol", "key", "channel", "job"} or value["protocol"] != _PROTOCOL:
        raise PipeProtocolError("UNAUTHORIZED")
    key_hex = value["key"]
    if not isinstance(key_hex, str) or len(key_hex) != 64:
        raise PipeProtocolError("UNAUTHORIZED")
    try:
        key = bytes.fromhex(key_hex)
    except ValueError as error:
        raise PipeProtocolError("UNAUTHORIZED") from error
    if key.hex() != key_hex or len(key) != 32:
        raise PipeProtocolError("UNAUTHORIZED")
    job = value["job"]
    if job is not None and not isinstance(job, str):
        raise PipeProtocolError("UNAUTHORIZED")
    return key, _uuid(value["channel"]), job


def _require_containment(job_name: str | None) -> None:
    """Windows: serve only inside the parent's exact session Job (DS-03 helpers).

    That Job has KILL_ON_JOB_CLOSE and neither BREAKAWAY_OK nor SILENT_BREAKAWAY_OK, so
    the child cannot outlive the parent's handle. Other platforms carry no Job; there the
    inherited-pipe EOF and the idle bound end the child.
    """
    if sys.platform == "win32":
        try:
            _current_job_pids(_validate_job_name(job_name))
        except Ds03Refusal as error:
            raise PipeProtocolError("UNAUTHORIZED") from error
    elif job_name is not None:
        raise PipeProtocolError("UNAUTHORIZED")


def encode_authenticated(
    message: GatewayMessage,
    *,
    key: bytes,
    channel: UUID,
    session_id: UUID,
    sequence: int,
    direction: Direction,
) -> bytes:
    if not isinstance(key, bytes) or len(key) != 32:
        raise PipeProtocolError("UNAUTHORIZED")
    if type(sequence) is not int or not 0 <= sequence <= MAX_INSPECTION_REQUESTS:
        raise PipeProtocolError("REPLAY")
    if not isinstance(direction, Direction):
        raise PipeProtocolError("INVALID_MESSAGE")
    decoded = decode_message(message.canonical_bytes())
    body = {
        "version": _FRAME_VERSION,
        "direction": direction.value,
        "channel": str(channel),
        "session_id": str(session_id),
        "sequence": sequence,
        "message": decoded.model_dump(mode="json"),
    }
    mac = hmac.new(key, _canonical(body), hashlib.sha256).hexdigest()
    raw = _canonical({**body, "mac": mac})
    if len(raw) + 1 > MAX_FRAME_BYTES:
        raise PipeProtocolError("INVALID_MESSAGE")
    return raw + b"\n"


def decode_authenticated(
    raw: bytes,
    *,
    key: bytes,
    channel: UUID,
    session_id: UUID | None,
    expected_sequence: int,
    direction: Direction,
) -> GatewayMessage:
    """Verify one frame read from the ``direction`` pipe of this channel and session.

    ``session_id`` is None only for the parent reading the child's sequence-zero hello.
    """
    if not isinstance(key, bytes) or len(key) != 32:
        raise PipeProtocolError("UNAUTHORIZED")
    if not isinstance(direction, Direction):
        raise PipeProtocolError("INVALID_MESSAGE")
    frame = _load(raw)
    if set(frame) != {
        "version",
        "direction",
        "channel",
        "session_id",
        "sequence",
        "message",
        "mac",
    }:
        raise PipeProtocolError("INVALID_MESSAGE")
    supplied = frame.pop("mac")
    if (
        not isinstance(supplied, str)
        or len(supplied) != 64
        or any(char not in "0123456789abcdef" for char in supplied)
    ):
        raise PipeProtocolError("UNAUTHORIZED")
    expected = hmac.new(key, _canonical(frame), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise PipeProtocolError("UNAUTHORIZED")
    if type(frame["version"]) is not int or frame["version"] != _FRAME_VERSION:
        raise PipeProtocolError("INVALID_MESSAGE")
    # Authentic but written for the other pipe: a reflection or cross-direction replay.
    if frame["direction"] != direction.value:
        raise PipeProtocolError("REPLAY")
    if _uuid(frame["channel"]) != channel:
        raise PipeProtocolError("REPLAY")
    if type(frame["sequence"]) is not int or frame["sequence"] != expected_sequence:
        raise PipeProtocolError("REPLAY")
    parsed_session = _uuid(frame["session_id"])
    if session_id is not None and parsed_session != session_id:
        raise PipeProtocolError("REPLAY")
    try:
        message = decode_message(_canonical(frame["message"]))
    except (ValueError, TypeError, RecursionError) as error:
        raise PipeProtocolError("INVALID_MESSAGE") from error
    if session_id is None and (
        direction is not Direction.CHILD_TO_PARENT
        or not isinstance(message.payload, GatewayHello)
        or message.payload.session_id != parsed_session
        or expected_sequence != 0
    ):
        raise PipeProtocolError("BINDING_DENIED")
    return message


def _message(
    payload: GatewayPayload, now: datetime, request: GatewayMessage | None
) -> GatewayMessage:
    return build_message(
        payload,
        command_id=uuid4(),
        correlation_id=request.correlation_id if request else uuid4(),
        causation_id=request.command_id if request else None,
        source_id="synthetic.inspection-gateway",
        account_ref=INSPECTION_ACCOUNT,
        mode=Mode.PAPER,
        writer_epoch=0,
        intent_hash=_ZERO_HASH,
        authorization_hash=_ZERO_HASH,
        reservation_hash=_ZERO_HASH,
        release_hash=_ZERO_HASH,
        config_hash=_ZERO_HASH,
        created_at=now,
        expires_at=now + timedelta(seconds=30),
    )


def _inspection(request: GatewayMessage, now: datetime) -> GatewayPayload:
    if isinstance(request.payload, GatewayDispatch):
        return GatewayError(code="UNSUPPORTED")
    if request.account_ref != INSPECTION_ACCOUNT or request.mode != Mode.PAPER:
        return GatewayError(code="BINDING_DENIED")
    if request.writer_epoch != 0 or any(
        value != _ZERO_HASH
        for value in (
            request.intent_hash,
            request.authorization_hash,
            request.reservation_hash,
            request.release_hash,
            request.config_hash,
        )
    ):
        return GatewayError(code="BINDING_DENIED")
    try:
        request.require_current(now)
    except ValueError:
        return GatewayError(code="EXPIRED")
    if isinstance(request.payload, GatewayHealth):
        return GatewayHealth(status="RECONCILE_ONLY", observed_at=now)
    if isinstance(request.payload, GatewayReconcile):
        # No external state or ledger lives in this process. Cursor zero only.
        return (
            GatewaySnapshot() if request.payload.cursor == 0 else GatewayError(code="UNSUPPORTED")
        )
    if isinstance(request.payload, AccountAttestation):
        return AccountAttestation(
            account_ref=INSPECTION_ACCOUNT,
            venue=Venue.BINANCE,
            server="synthetic.offline",
            account_identifier="synthetic.no-broker-account",
            account_kind="DEMO",
            currency="USDT",
            account_mode="NETTING",
            observed_at=now,
            capability_hash=hashlib.sha256(b"INSPECTION_ONLY_NO_DISPATCH").hexdigest(),
        )
    if isinstance(request.payload, GatewayInstrumentSnapshot):
        return GatewayInstrumentSnapshot(
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
                spec_version="synthetic.inspection.v1",
                observed_at=now,
            ),
            supported_fill=("IOC",),
        )
    return GatewayError(code="UNSUPPORTED")


def _pump(reader: BinaryIO, lines: Queue[bytes | None]) -> None:
    """Sole reader of the inherited pipe; b"" marks EOF and None a failed read."""
    try:
        while raw := reader.readline(MAX_FRAME_BYTES + 1):
            lines.put(raw)
    except OSError:
        # Reported to the serving loop, which closes the session with exit status 2.
        lines.put(None)
        return
    lines.put(b"")


def _next_line(lines: Queue[bytes | None], idle_timeout: float) -> bytes | None:
    """The next raw line (b"" at EOF), or None when none arrived within the idle bound."""
    try:
        raw = lines.get(timeout=idle_timeout)
    except Empty:
        return None
    if raw is None:
        raise PipeProtocolError("UNAVAILABLE")
    return raw


def serve_inspection(
    reader: BinaryIO, writer: BinaryIO, *, idle_timeout: float = IDLE_TIMEOUT_SECONDS
) -> int:
    """Bounded fake process, inherited pipes only; never starts a listener or sends.

    ``reader`` must be unbuffered: after an idle exit the daemon pump thread can remain
    blocked in it, and a buffered reader's lock would abort interpreter shutdown.
    """
    if not 0 < idle_timeout <= IDLE_TIMEOUT_SECONDS:
        raise ValueError("IDLE_TIMEOUT")
    lines: Queue[bytes | None] = Queue(maxsize=1)
    Thread(target=_pump, args=(reader, lines), daemon=True).start()
    try:
        raw_bootstrap = _next_line(lines, idle_timeout)
        if raw_bootstrap is None:
            return 2
        key, channel, job_name = _bootstrap(raw_bootstrap)
        _require_containment(job_name)
    except PipeProtocolError:
        return 2
    session_id = uuid4()
    hello = _message(
        GatewayHello(gateway_id="synthetic.inspection-gateway", session_id=session_id),
        datetime.now(UTC),
        None,
    )
    writer.write(
        encode_authenticated(
            hello,
            key=key,
            channel=channel,
            session_id=session_id,
            sequence=0,
            direction=Direction.CHILD_TO_PARENT,
        )
    )
    writer.flush()
    seen: set[UUID] = set()
    for sequence in range(1, MAX_INSPECTION_REQUESTS + 1):
        request: GatewayMessage | None = None
        status: int | None = None
        try:
            raw = _next_line(lines, idle_timeout)
            if raw == b"":
                return 0
            if raw is None:
                # Nothing valid within the bound: record why on the authenticated pipe in
                # place of the awaited reply, then end cleanly instead of waiting forever.
                payload: GatewayPayload = GatewayError(code="IDLE_TIMEOUT")
                status = 0
            else:
                request = decode_authenticated(
                    raw,
                    key=key,
                    channel=channel,
                    session_id=session_id,
                    expected_sequence=sequence,
                    direction=Direction.PARENT_TO_CHILD,
                )
                if request.command_id in seen:
                    raise PipeProtocolError("REPLAY")
                seen.add(request.command_id)
                payload = _inspection(request, datetime.now(UTC))
        except PipeProtocolError as error:
            # Auth/protocol failure closes the session; never resynchronize or resend.
            payload = GatewayError.model_validate({"code": error.code})
            status = 2
        reply = _message(payload, datetime.now(UTC), request)
        writer.write(
            encode_authenticated(
                reply,
                key=key,
                channel=channel,
                session_id=session_id,
                sequence=sequence,
                direction=Direction.CHILD_TO_PARENT,
            )
        )
        writer.flush()
        if status is not None:
            return status
    return 0
