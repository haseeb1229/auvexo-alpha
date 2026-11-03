"""Bounded authenticated frames for the DS-03 synthetic-only connector."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from enum import Enum
from typing import Literal, cast
from uuid import UUID

from auvexo_alpha.domain.ds03 import MAX_FRAME_BYTES, MAX_REQUESTS

REQUEST_TIMEOUT_SECONDS = 10


class ProtocolFamily(Enum):
    SYNTHETIC = "auvexo.ds03.synthetic.v1"
    MT5_READONLY = "auvexo.ds03.mt5-readonly.v1"


def _protocol(family: ProtocolFamily) -> str:
    if type(family) is not ProtocolFamily:
        raise Ds03ProtocolError()
    return family.value


_KEYS = {"protocol", "kind", "session", "sequence", "request_id", "payload", "mac"}
FrameKind = Literal["HELLO", "REQUEST", "REPLY", "ERROR"]


class Ds03ProtocolError(ValueError):
    """Fixed redaction boundary: no frame or authentication material in errors."""

    def __init__(self) -> None:
        super().__init__("DS03_UNAVAILABLE")


def new_pipe_key() -> bytes:
    return secrets.token_bytes(32)


def canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("ascii")
    except (TypeError, ValueError, RecursionError):
        raise Ds03ProtocolError() from None


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise Ds03ProtocolError()
        result[key] = value
    return result


def _reject_number(value: str) -> None:
    raise Ds03ProtocolError()


def _load(raw: bytes) -> dict[str, object]:
    if type(raw) is not bytes or not 1 < len(raw) <= MAX_FRAME_BYTES or not raw.endswith(b"\n"):
        raise Ds03ProtocolError()
    try:
        value: object = json.loads(
            raw,
            object_pairs_hook=_unique,
            parse_constant=_reject_number,
            parse_float=_reject_number,
        )
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise Ds03ProtocolError() from None
    if not isinstance(value, dict) or canonical(value) + b"\n" != raw:
        raise Ds03ProtocolError()
    return cast(dict[str, object], value)


def _key(key: bytes) -> None:
    if type(key) is not bytes or len(key) != 32:
        raise Ds03ProtocolError()


def _digest(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise Ds03ProtocolError()
    return value


def _uuid(value: object) -> UUID:
    if not isinstance(value, str):
        raise Ds03ProtocolError()
    try:
        parsed = UUID(value)
    except ValueError:
        raise Ds03ProtocolError() from None
    if str(parsed) != value:
        raise Ds03ProtocolError()
    return parsed


def bootstrap_frame(
    key: bytes, session: UUID, binding: str, *, family: ProtocolFamily = ProtocolFamily.SYNTHETIC
) -> bytes:
    _key(key)
    if not isinstance(session, UUID):
        raise Ds03ProtocolError()
    return (
        canonical(
            {
                "protocol": _protocol(family),
                "key": key.hex(),
                "session": str(session),
                "binding": _digest(binding),
            }
        )
        + b"\n"
    )


def read_bootstrap(
    raw: bytes, expected_binding: str, *, family: ProtocolFamily = ProtocolFamily.SYNTHETIC
) -> tuple[bytes, UUID]:
    frame = _load(raw)
    if set(frame) != {"protocol", "key", "session", "binding"} or frame["protocol"] != _protocol(
        family
    ):
        raise Ds03ProtocolError()
    key = bytes.fromhex(_digest(frame["key"]))
    _key(key)
    if not hmac.compare_digest(_digest(frame["binding"]), _digest(expected_binding)):
        raise Ds03ProtocolError()
    return key, _uuid(frame["session"])


@dataclass(frozen=True)
class Ds03Frame:
    kind: FrameKind
    request_id: UUID | None
    payload: dict[str, object]


def encode_frame(
    kind: FrameKind,
    payload: dict[str, object],
    *,
    key: bytes,
    session: UUID,
    sequence: int,
    request_id: UUID | None,
    family: ProtocolFamily = ProtocolFamily.SYNTHETIC,
) -> bytes:
    _key(key)
    if kind not in {"HELLO", "REQUEST", "REPLY", "ERROR"}:
        raise Ds03ProtocolError()
    if type(sequence) is not int or not 0 <= sequence <= MAX_REQUESTS:
        raise Ds03ProtocolError()
    if not isinstance(session, UUID) or (
        request_id is not None and not isinstance(request_id, UUID)
    ):
        raise Ds03ProtocolError()
    if not isinstance(payload, dict):
        raise Ds03ProtocolError()
    body = {
        "protocol": _protocol(family),
        "kind": kind,
        "session": str(session),
        "sequence": sequence,
        "request_id": str(request_id) if request_id is not None else None,
        "payload": payload,
    }
    raw = (
        canonical({**body, "mac": hmac.new(key, canonical(body), hashlib.sha256).hexdigest()})
        + b"\n"
    )
    if len(raw) > MAX_FRAME_BYTES:
        raise Ds03ProtocolError()
    return raw


def decode_frame(
    raw: bytes,
    *,
    key: bytes,
    session: UUID,
    sequence: int,
    kind: FrameKind,
    family: ProtocolFamily = ProtocolFamily.SYNTHETIC,
) -> Ds03Frame:
    _key(key)
    frame = _load(raw)
    if set(frame) != _KEYS:
        raise Ds03ProtocolError()
    supplied = _digest(frame.pop("mac"))
    if not hmac.compare_digest(
        supplied, hmac.new(key, canonical(frame), hashlib.sha256).hexdigest()
    ):
        raise Ds03ProtocolError()
    if (
        frame["protocol"] != _protocol(family)
        or frame["kind"] != kind
        or type(frame["sequence"]) is not int
        or frame["sequence"] != sequence
        or type(sequence) is not int
        or not 0 <= sequence <= MAX_REQUESTS
        or _uuid(frame["session"]) != session
    ):
        raise Ds03ProtocolError()
    request_id = None if frame["request_id"] is None else _uuid(frame["request_id"])
    payload = frame["payload"]
    if not isinstance(payload, dict):
        raise Ds03ProtocolError()
    return Ds03Frame(kind, request_id, cast(dict[str, object], payload))
