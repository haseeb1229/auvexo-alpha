"""Adversarial authentication/framing proofs for synthetic DS-03 pipes."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from auvexo_alpha.domain.ds03 import MAX_FRAME_BYTES
from auvexo_alpha.infrastructure.ds03_ipc import (
    Ds03ProtocolError,
    bootstrap_frame,
    canonical,
    decode_frame,
    encode_frame,
    new_pipe_key,
    read_bootstrap,
)


def test_bootstrap_and_authenticated_direction_roundtrip() -> None:
    key, session = new_pipe_key(), uuid4()
    assert len(key) == 32 and key != new_pipe_key()
    assert read_bootstrap(bootstrap_frame(key, session, "a" * 64), "a" * 64) == (key, session)
    request_id = uuid4()
    raw = encode_frame(
        "REQUEST",
        {"operation": "SYMBOLS"},
        key=key,
        session=session,
        sequence=1,
        request_id=request_id,
    )
    frame = decode_frame(raw, key=key, session=session, sequence=1, kind="REQUEST")
    assert frame.request_id == request_id
    assert frame.payload == {"operation": "SYMBOLS"}


@pytest.mark.parametrize("change", ["key", "session", "sequence", "direction", "payload", "extra"])
def test_frame_authentication_or_binding_tamper_denied(change: str) -> None:
    key, session = new_pipe_key(), uuid4()
    raw = encode_frame(
        "REQUEST",
        {"operation": "SYMBOLS"},
        key=key,
        session=session,
        sequence=1,
        request_id=uuid4(),
    )
    if change in {"payload", "extra"}:
        frame = json.loads(raw)
        if change == "payload":
            frame["payload"]["operation"] = "SPEC"
        else:
            frame["extra"] = "synthetic"
        raw = canonical(frame) + b"\n"
    with pytest.raises(Ds03ProtocolError, match="^DS03_UNAVAILABLE$"):
        decode_frame(
            raw,
            key=new_pipe_key() if change == "key" else key,
            session=uuid4() if change == "session" else session,
            sequence=2 if change == "sequence" else 1,
            kind="REPLY" if change == "direction" else "REQUEST",
        )


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{}",
        b"{}\n",
        b"null\n",
        b"[]\n",
        b"NaN\n",
        b'{"x":1,"x":2}\n',
        b'{"x":1.5}\n',
        b'{"x":Infinity}\n',
        b"\xff\n",
        b"x" * (MAX_FRAME_BYTES + 1),
    ],
    ids=[
        "empty",
        "no-newline",
        "object",
        "null",
        "array",
        "NaN",
        "duplicate-key",
        "float",
        "Infinity",
        "non-utf8",
        "oversize",
    ],
)
def test_malformed_noncanonical_duplicate_nonfinite_and_oversize_denied(raw: bytes) -> None:
    with pytest.raises(Ds03ProtocolError, match="^DS03_UNAVAILABLE$"):
        decode_frame(raw, key=new_pipe_key(), session=uuid4(), sequence=1, kind="REQUEST")


@pytest.mark.parametrize("sequence", [True, -1, 257])
def test_sequence_type_and_session_quota_are_exact(sequence: int) -> None:
    with pytest.raises(Ds03ProtocolError):
        encode_frame(
            "REQUEST",
            {},
            key=new_pipe_key(),
            session=uuid4(),
            sequence=sequence,
            request_id=uuid4(),
        )


def test_bootstrap_source_binding_and_fixed_shape_denied() -> None:
    key, session = new_pipe_key(), uuid4()
    raw = bootstrap_frame(key, session, "a" * 64)
    with pytest.raises(Ds03ProtocolError):
        read_bootstrap(raw, "b" * 64)
    value = json.loads(raw)
    value["executable"] = "synthetic.arbitrary"
    with pytest.raises(Ds03ProtocolError):
        read_bootstrap(canonical(value) + b"\n", "a" * 64)


def test_low_level_failure_never_outputs_authentication(capsys: pytest.CaptureFixture[str]) -> None:
    key = new_pipe_key()
    with pytest.raises(Ds03ProtocolError) as error:
        decode_frame(
            b"synthetic-private-marker\n", key=key, session=uuid4(), sequence=1, kind="REPLY"
        )
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert key.hex() not in str(error.value)
    assert "synthetic-private-marker" not in str(error.value)
