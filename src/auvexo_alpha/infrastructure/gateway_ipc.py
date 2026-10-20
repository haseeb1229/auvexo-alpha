"""Authenticated inherited-pipe framing for an inspection-only synthetic process.

The bootstrap key is generated for each local launch and travels only through its
inherited anonymous stdin pipe. It is a fake local authentication secret, never a
broker credential. The child accepts no state-changing command. Synthetic dispatch
belongs exclusively to the durable PAPER coordinator, not this inspection process.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import BinaryIO, cast
from uuid import UUID, uuid4

from auvexo_alpha.domain.contracts import InstrumentSpec, Mode, Product, Venue
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

MAX_FRAME_BYTES = MAX_MESSAGE_BYTES + 1024
MAX_INSPECTION_REQUESTS = 256
INSPECTION_ACCOUNT = "paper.offline-inspection"
_ZERO_HASH = "0" * 64


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


def fake_pipe_secret() -> bytes:
    """Generate ephemeral local IPC key material; no credential-store integration."""
    return secrets.token_bytes(32)


def bootstrap_frame(key: bytes) -> bytes:
    if not isinstance(key, bytes) or len(key) != 32:
        raise PipeProtocolError("UNAUTHORIZED")
    return _canonical({"protocol": "synthetic-inspection.v1", "key": key.hex()}) + b"\n"


def _bootstrap_key(raw: bytes) -> bytes:
    value = _load(raw)
    if set(value) != {"protocol", "key"} or value["protocol"] != "synthetic-inspection.v1":
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
    return key


def encode_authenticated(
    message: GatewayMessage, *, key: bytes, session_id: UUID, sequence: int
) -> bytes:
    if not isinstance(key, bytes) or len(key) != 32:
        raise PipeProtocolError("UNAUTHORIZED")
    if type(sequence) is not int or not 0 <= sequence <= MAX_INSPECTION_REQUESTS:
        raise PipeProtocolError("REPLAY")
    decoded = decode_message(message.canonical_bytes())
    body = {
        "version": 1,
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
    raw: bytes, *, key: bytes, session_id: UUID | None, expected_sequence: int
) -> GatewayMessage:
    if not isinstance(key, bytes) or len(key) != 32:
        raise PipeProtocolError("UNAUTHORIZED")
    frame = _load(raw)
    if set(frame) != {"version", "session_id", "sequence", "message", "mac"}:
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
    if type(frame["version"]) is not int or frame["version"] != 1:
        raise PipeProtocolError("INVALID_MESSAGE")
    if type(frame["sequence"]) is not int or frame["sequence"] != expected_sequence:
        raise PipeProtocolError("REPLAY")
    identity = frame["session_id"]
    if not isinstance(identity, str):
        raise PipeProtocolError("INVALID_MESSAGE")
    try:
        parsed_session = UUID(identity)
    except ValueError as error:
        raise PipeProtocolError("INVALID_MESSAGE") from error
    if str(parsed_session) != identity:
        raise PipeProtocolError("INVALID_MESSAGE")
    if session_id is not None and parsed_session != session_id:
        raise PipeProtocolError("REPLAY")
    try:
        message = decode_message(_canonical(frame["message"]))
    except (ValueError, TypeError, RecursionError) as error:
        raise PipeProtocolError("INVALID_MESSAGE") from error
    if session_id is None and (
        not isinstance(message.payload, GatewayHello)
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


def serve_inspection(reader: BinaryIO, writer: BinaryIO) -> int:
    """Bounded fake process, inherited pipes only; never starts a listener or sends."""
    try:
        key = _bootstrap_key(reader.readline(MAX_FRAME_BYTES + 1))
    except PipeProtocolError:
        return 2
    session_id = uuid4()
    hello = _message(
        GatewayHello(gateway_id="synthetic.inspection-gateway", session_id=session_id),
        datetime.now(UTC),
        None,
    )
    writer.write(encode_authenticated(hello, key=key, session_id=session_id, sequence=0))
    writer.flush()
    seen: set[UUID] = set()
    for sequence in range(1, MAX_INSPECTION_REQUESTS + 1):
        raw = reader.readline(MAX_FRAME_BYTES + 1)
        if not raw:
            return 0
        request: GatewayMessage | None = None
        fatal = False
        now = datetime.now(UTC)
        try:
            request = decode_authenticated(
                raw, key=key, session_id=session_id, expected_sequence=sequence
            )
            if request.command_id in seen:
                raise PipeProtocolError("REPLAY")
            seen.add(request.command_id)
            payload = _inspection(request, now)
        except PipeProtocolError as error:
            # Auth/protocol failure closes the session; never resynchronize or resend.
            payload = GatewayError.model_validate({"code": error.code})
            fatal = True
        reply = _message(payload, now, request)
        writer.write(encode_authenticated(reply, key=key, session_id=session_id, sequence=sequence))
        writer.flush()
        if fatal:
            return 2
    return 0
