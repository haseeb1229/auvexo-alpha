"""Actual-family IPC/process tests use typed fake ports, never native SDK/session/stores."""

from __future__ import annotations

import io
import json
import sys
from uuid import uuid4

import pytest
from mt5_fixtures import SYNTHETIC_PASSWORD, fixture, request

from auvexo_alpha.domain.ds03 import Ds03Error
from auvexo_alpha.infrastructure import ds03_mt5_process as module
from auvexo_alpha.infrastructure.ds03_ipc import (
    Ds03ProtocolError,
    ProtocolFamily,
    bootstrap_frame,
    canonical,
    decode_frame,
    encode_frame,
    new_pipe_key,
    read_bootstrap,
)
from auvexo_alpha.infrastructure.ds03_mt5 import actual_rights
from auvexo_alpha.infrastructure.ds03_mt5_process import ActualDs03Process, _serve_actual_session

FAMILY = ProtocolFamily.MT5_READONLY


def packet(message, *, key, session, sequence, family=FAMILY):
    return encode_frame(
        "REQUEST",
        message.model_dump(mode="json"),
        key=key,
        session=session,
        sequence=sequence,
        request_id=message.request_id,
        family=family,
    )


def serve(f, incoming, key, session):
    output = io.BytesIO()
    code = _serve_actual_session(
        io.BytesIO(incoming),
        output,
        key=key,
        session=session,
        port=f.port,
        rights=actual_rights(f.admission),
        source_hash=f.admission.binding.connector_source_hash,
    )
    return code, output.getvalue().splitlines(keepends=True)


def test_original_synthetic_bootstrap_bytes_remain_exact_and_family_is_closed():
    key, session = b"x" * 32, uuid4()
    expected = (
        canonical(
            {
                "protocol": "auvexo.ds03.synthetic.v1",
                "key": key.hex(),
                "session": str(session),
                "binding": "b" * 64,
            }
        )
        + b"\n"
    )
    assert bootstrap_frame(key, session, "b" * 64) == expected
    actual = bootstrap_frame(key, session, "b" * 64, family=FAMILY)
    assert read_bootstrap(actual, "b" * 64, family=FAMILY) == (key, session)
    with pytest.raises(Ds03ProtocolError):
        read_bootstrap(actual, "b" * 64)
    with pytest.raises(Ds03ProtocolError):
        bootstrap_frame(key, session, "b" * 64, family="arbitrary.protocol")


def test_actual_fake_session_discovery_spec_tick_and_clean_disconnect():
    f = fixture()
    key, session = new_pipe_key(), uuid4()
    messages = [
        request(f, "SYMBOLS"),
        request(f, "SPEC", symbol=f.sdk.symbols[0]),
        request(f, "TICK", symbol=f.sdk.symbols[0]),
        request(f, "DISCONNECT"),
    ]
    incoming = b"".join(
        packet(m, key=key, session=session, sequence=i) for i, m in enumerate(messages, 1)
    )
    code, frames = serve(f, incoming, key, session)
    assert code == 0 and len(frames) == 5
    hello = decode_frame(
        frames[0], key=key, session=session, sequence=0, kind="HELLO", family=FAMILY
    )
    assert hello.payload["binding"] == f.admission.binding.connector_source_hash
    for i, message in enumerate(messages, 1):
        frame = decode_frame(
            frames[i], key=key, session=session, sequence=i, kind="REPLY", family=FAMILY
        )
        assert frame.request_id == message.request_id
        assert frame.payload["protocol_family"] == "DS03_MT5_READONLY_V1"
        assert frame.payload["envelope"]["synthetic"] is False
    assert f.sdk.shutdown_count == 1


@pytest.mark.parametrize(
    "attack",
    [
        "bad-mac",
        "wrong-session",
        "reflection",
        "wrong-correlation",
        "duplicate-id",
        "duplicate-sequence",
    ],
)
def test_actual_session_authentication_and_replay_fail_closed(attack):
    f = fixture()
    key, session = new_pipe_key(), uuid4()
    message = request(f, "SYMBOLS")
    incoming = b""
    sequence = 1
    if attack in ("duplicate-id", "duplicate-sequence"):
        incoming = packet(message, key=key, session=session, sequence=1)
        sequence = 2
    raw = packet(
        message,
        key=key,
        session=uuid4() if attack == "wrong-session" else session,
        sequence=1 if attack == "duplicate-sequence" else sequence,
    )
    if attack == "bad-mac":
        value = json.loads(raw)
        value["mac"] = "0" * 64
        raw = canonical(value) + b"\n"
    elif attack == "reflection":
        raw = encode_frame(
            "REPLY",
            message.model_dump(mode="json"),
            key=key,
            session=session,
            sequence=sequence,
            request_id=message.request_id,
            family=FAMILY,
        )
    elif attack == "wrong-correlation":
        raw = encode_frame(
            "REQUEST",
            message.model_dump(mode="json"),
            key=key,
            session=session,
            sequence=sequence,
            request_id=uuid4(),
            family=FAMILY,
        )
    code, frames = serve(f, incoming + raw, key, session)
    assert code == 2 and f.sdk.shutdown_count == 1
    failure = decode_frame(
        frames[-1], key=key, session=session, sequence=sequence, kind="ERROR", family=FAMILY
    )
    assert failure.payload == {"code": "DS03_UNAVAILABLE"}


@pytest.mark.parametrize(
    "operation",
    [
        "order_send",
        "order_check",
        "modify",
        "cancel",
        "symbol_select",
        "market_book_add",
        "login",
        "arbitrary_method",
    ],
)
def test_arbitrary_and_state_mutation_operations_never_reach_sdk(operation):
    f = fixture()
    key, session = new_pipe_key(), uuid4()
    message = request(f, "SYMBOLS")
    payload = message.model_dump(mode="json")
    payload["operation"] = operation
    raw = encode_frame(
        "REQUEST",
        payload,
        key=key,
        session=session,
        sequence=1,
        request_id=message.request_id,
        family=FAMILY,
    )
    code, frames = serve(f, raw, key, session)
    assert code == 2
    assert not any(c[0] in ("symbols_get", "symbol_info", "symbol_info_tick") for c in f.sdk.calls)
    assert len([c for c in f.sdk.calls if c[0] == "initialize"]) == 1  # Fake initialization only.
    assert f.sdk.shutdown_count == 1
    assert decode_frame(
        frames[-1], key=key, session=session, sequence=1, kind="ERROR", family=FAMILY
    ).payload == {"code": "DS03_UNAVAILABLE"}


def test_synthetic_frame_cannot_be_reflected_into_actual_session():
    f = fixture()
    key, session = new_pipe_key(), uuid4()
    code, frames = serve(
        f,
        packet(
            request(f, "SYMBOLS"),
            key=key,
            session=session,
            sequence=1,
            family=ProtocolFamily.SYNTHETIC,
        ),
        key,
        session,
    )
    assert code == 2 and f.sdk.shutdown_count == 1
    with pytest.raises(Ds03ProtocolError):
        decode_frame(frames[0], key=key, session=session, sequence=0, kind="HELLO")


def test_actual_parent_static_gate_precedes_process_or_provider_effects(monkeypatch):
    f = fixture(initialize=False)

    def unavailable(authority):
        raise Ds03Error()

    def forbidden(*args, **kwargs):
        raise AssertionError("No process/provider effect admitted")

    monkeypatch.setattr(module, "_measurement", unavailable)
    monkeypatch.setattr(module.subprocess, "Popen", forbidden)
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE$"):
        ActualDs03Process(f.static).start()
    assert f.sdk.calls == []


def test_actual_parent_bootstrap_has_no_password_or_private_metadata_and_job_precedes_bytes(
    monkeypatch,
):
    f = fixture()
    state = {"assigned": False, "closed": False}

    class Job:
        name = "Local" + chr(92) + "AuvexoAlphaDS03Readonly-" + "a" * 32

        def assign(self, process):
            state["assigned"] = True

        def close(self):
            state["closed"] = True

    class Process:
        def __init__(self, args, **kwargs):
            state["command"] = args
            state["flags"] = kwargs["creationflags"]
            self.stdin, self.stdout = io.BytesIO(), io.BytesIO()
            self.done = False

        def poll(self):
            return 0 if self.done else None

        def kill(self):
            self.done = True

        def wait(self, timeout=None):
            self.done = True
            return 0

    def exchange(reader, writer, raw):
        assert state["assigned"]
        assert SYNTHETIC_PASSWORD.encode() not in raw
        assert f.admission.metadata.assigned_server.encode() not in raw
        lines = raw.splitlines(keepends=True)
        key, session = read_bootstrap(
            lines[0], f.admission.binding.connector_source_hash, family=FAMILY
        )
        context = decode_frame(
            lines[1], key=key, session=session, sequence=0, kind="REQUEST", family=FAMILY
        )
        assert set(context.payload) == {"authority", "accepted_digest", "provider_job"}
        hello = {
            "binding": f.admission.binding.connector_source_hash,
            "attestation": f.port.attest().model_dump(mode="json"),
            "rights": actual_rights(f.admission).model_dump(mode="json"),
        }
        return encode_frame(
            "HELLO", hello, key=key, session=session, sequence=0, request_id=None, family=FAMILY
        )

    monkeypatch.setattr(module, "_measurement", lambda authority: f.admission.binding)
    monkeypatch.setattr(
        module.measured, "source_binding", lambda: f.admission.binding.connector_source_hash
    )
    monkeypatch.setattr(module.measured, "provider_job", Job)
    monkeypatch.setattr(
        module.measured, "probe_terminal_process", lambda bound: f.observer.evidence
    )
    monkeypatch.setattr(module.subprocess, "Popen", Process)
    monkeypatch.setattr(module, "_exchange", exchange)
    fixed = module.measured.runtime_root() / ".venv" / "Scripts" / "python.exe"
    monkeypatch.setattr(sys, "executable", str(fixed))
    process = ActualDs03Process(f.static).start()
    assert state["command"] == [
        str(fixed),
        "-I",
        "-B",
        "-m",
        "auvexo_alpha.infrastructure.ds03_mt5_process",
        "--actual-provider-child",
    ]
    if sys.platform == "win32":
        assert state["flags"] & 0x00000004
    process.close()
    assert state["closed"]
    f.port.disconnect()


def test_parent_cancellation_during_hello_pin_does_not_return_started_session(monkeypatch):
    # The exact final gate rejects lifecycle changes after the first IO gate.
    f = fixture()
    client = ActualDs03Process(f.static)
    expected = f.port.attest().identity
    process = object()
    session = uuid4()
    client._life._process, client._life._session = process, session
    client._expected = expected
    generation = client._life._generation
    client._require_current(process, session, generation, expected)
    client._life._generation += 1
    with pytest.raises(Ds03Error):
        client._require_current(process, session, generation, expected)
    client._life._process = None
    client.close()
    f.port.disconnect()


@pytest.mark.parametrize("bad", [None, object(), 1, "unaccepted"])
def test_constructor_rejects_untyped_admission_before_any_native_effect(bad, monkeypatch):
    calls = []
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: calls.append("launch"))
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE$"):
        ActualDs03Process(bad)
    assert calls == []
