"""R12-7: every actual-family refusal carries one closed, non-secret reason code.

Fake SDK, fake ports and synthetic values only.
"""

from __future__ import annotations

import ast
import inspect
import io
import json
import re
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from mt5_fixtures import SYNTHETIC_PASSWORD, fixture, request
from pydantic import ValidationError
from test_ds03_actual_contracts import identity

from auvexo_alpha.application import ds03 as application
from auvexo_alpha.domain.ds03 import Ds03Error
from auvexo_alpha.domain.ds03_actual import (
    REASON_CODES,
    Ds03Reasoned,
    Ds03Refusal,
    closed_reason,
    refusal,
)
from auvexo_alpha.domain.ds03_authority import Ds03AuthorityError
from auvexo_alpha.infrastructure import ds03_mt5, ds03_mt5_process
from auvexo_alpha.infrastructure.ds03_ipc import (
    Ds03Frame,
    Ds03ProtocolError,
    ProtocolFamily,
    decode_frame,
    decode_outcome,
    encode_frame,
    error_payload,
    error_reason,
    new_pipe_key,
    read_bootstrap,
)
from auvexo_alpha.infrastructure.ds03_metadata import (
    Ds03MetadataUnavailable,
    Ds03ReferenceKeyUnavailable,
)
from auvexo_alpha.infrastructure.ds03_mt5 import actual_rights
from auvexo_alpha.infrastructure.ds03_mt5_process import ActualDs03Process, _serve_actual_session
from auvexo_alpha.infrastructure.ds03_secrets import Ds03SecretUnavailable

FAMILY = ProtocolFamily.MT5_READONLY


def secrets_of(f):
    info = f.admission.metadata
    return (
        str(info.login),
        info.assigned_server,
        SYNTHETIC_PASSWORD,
        "SYNTHETIC_PERSON_NEVER_LOG",
        info.account_digest,
        info.server_digest,
    )


def test_reason_set_is_closed_upper_case_and_cannot_hold_a_value():
    assert 30 <= len(REASON_CODES) <= 64
    for code in REASON_CODES:
        assert re.fullmatch(r"[A-Z][A-Z_]{2,39}", code), code
        error = Ds03Refusal(code)
        assert error.reason == code and error.args == ("DS03_UNAVAILABLE:" + code,)
        assert isinstance(error, Ds03Error) and isinstance(error, Ds03Reasoned)


@pytest.mark.parametrize(
    "value",
    [
        "123456789",
        "synthetic-server.invalid",
        SYNTHETIC_PASSWORD,
        "ds03.account." + "a" * 64,
        "C:\\Users\\owner\\AppData",
        "account_not_demo",
        "ACCOUNT_NOT_DEMO ",
        "ACCOUNT_NOT_DEMO:123",
        None,
        123,
        ["ACCOUNT_NOT_DEMO"],
        b"ACCOUNT_NOT_DEMO",
    ],
)
def test_anything_outside_the_closed_set_is_unclassified_and_never_echoed(value):
    error = Ds03Refusal(value)
    assert error.reason == closed_reason(value) == "UNCLASSIFIED"
    assert str(error) == "DS03_UNAVAILABLE:UNCLASSIFIED"
    assert error_payload(value) == {"code": "DS03_UNAVAILABLE", "reason": "UNCLASSIFIED"}


def test_refusal_keeps_only_a_closed_reason_and_drops_text_and_context():
    try:
        try:
            raise KeyError(SYNTHETIC_PASSWORD)
        except KeyError as error:
            raise refusal(error, "PROVIDER_DATA_INVALID") from None
    except Ds03Refusal as caught:
        assert str(caught) == "DS03_UNAVAILABLE:PROVIDER_DATA_INVALID"
        assert caught.__cause__ is None and caught.__suppress_context__
        assert SYNTHETIC_PASSWORD not in repr(caught)
    assert refusal(Ds03Refusal("ACCOUNT_NOT_DEMO"), "UNCLASSIFIED").reason == "ACCOUNT_NOT_DEMO"
    assert refusal(Ds03Error(), "SPEC_DRIFT").reason == "SPEC_DRIFT"
    with pytest.raises(ValidationError) as captured:
        identity(time_basis_hash=None)
    assert refusal(captured.value, "UNCLASSIFIED").reason == "TIME_BASIS_MISMATCH"


@pytest.mark.parametrize(
    "error,reason",
    [
        (Ds03ProtocolError(), "IPC_PROTOCOL"),
        (Ds03SecretUnavailable(), "CREDENTIAL_UNAVAILABLE"),
        (Ds03MetadataUnavailable(), "METADATA_UNAVAILABLE"),
        (Ds03MetadataUnavailable("REFERENCE_MISMATCH"), "REFERENCE_MISMATCH"),
        (Ds03ReferenceKeyUnavailable(), "REFERENCE_KEY_UNAVAILABLE"),
        (Ds03AuthorityError(), "AUTHORITY_INVALID"),
        (Ds03AuthorityError("AUTHORITY_EXPIRED"), "AUTHORITY_EXPIRED"),
    ],
)
def test_every_project_error_class_on_the_actual_path_maps_to_one_closed_code(error, reason):
    assert error.reason == reason and reason in REASON_CODES
    assert refusal(error, "UNCLASSIFIED").reason == reason
    # Messages of the slot/protocol classes are unchanged fixed constants.
    assert str(error).split(":")[0] in (
        "DS03_UNAVAILABLE",
        "DS03_SECRET_UNAVAILABLE",
        "DS03_METADATA_UNAVAILABLE",
        "DS03_REFERENCE_KEY_UNAVAILABLE",
        "DS03_AUTHORITY_UNAVAILABLE",
    )


def _raises(module):
    return [
        node
        for node in ast.walk(ast.parse(Path(inspect.getsourcefile(module)).read_text("utf8")))
        if isinstance(node, ast.Raise)
    ]


def _constant_codes(node):
    if isinstance(node, ast.Name) and node.id == "_INVALID":
        return {ds03_mt5._INVALID}
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return _constant_codes(node.body) | _constant_codes(node.orelse)
    return None


@pytest.mark.parametrize("module", [ds03_mt5, ds03_mt5_process, application])
def test_static_every_raise_on_the_actual_path_names_a_closed_code(module):
    """No bare Ds03Error survives on the actual path; every raise is a closed reason."""
    for node in _raises(module):
        exc = node.exc
        assert exc is not None, ("bare re-raise", node.lineno)
        assert isinstance(exc, ast.Call), node.lineno
        name = exc.func.id if isinstance(exc.func, ast.Name) else exc.func.attr
        if name == "Ds03Refusal":
            (argument,) = exc.args
            codes = _constant_codes(argument)
            if codes is None:
                # Only an authenticated ERROR-frame reason, itself closed by error_reason.
                assert isinstance(argument, ast.Call) and argument.func.id == "error_reason", (
                    node.lineno
                )
            else:
                assert codes <= REASON_CODES, (node.lineno, codes - REASON_CODES)
        elif name == "refusal":
            assert _constant_codes(exc.args[1]) <= REASON_CODES, node.lineno
            assert isinstance(node.cause, ast.Constant) and node.cause.value is None
        elif name == "SystemExit":
            # Only the child's ``__main__`` guard exits with main()'s status code.
            assert module is ds03_mt5_process and exc.args[0].func.id == "main"
        else:
            # The shared session's codec decides: synthetic stays bare, actual is reasoned.
            assert name == "refuse" and module is application, (node.lineno, name)
    assert ds03_mt5._INVALID in REASON_CODES


def test_actual_codec_refuses_with_reasons_and_synthetic_codec_stays_unchanged():
    error = Ds03Refusal("SPEC_DRIFT")
    assert str(application._ActualCodec().refuse(error)) == "DS03_UNAVAILABLE:SPEC_DRIFT"
    synthetic = application._SyntheticCodec().refuse(error)
    assert type(synthetic) is Ds03Error and str(synthetic) == "DS03_UNAVAILABLE"


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("trade_mode", 2, "ACCOUNT_NOT_DEMO"),
        ("login", 111, "ACCOUNT_IDENTITY"),
        ("server", "synthetic-wrong.invalid", "ACCOUNT_IDENTITY"),
        ("trade_allowed", True, "TRADE_FLAG_TRUE"),
    ],
)
def test_child_reports_pre_hello_refusal_reason_without_any_private_value(field, value, reason):
    f = fixture()
    secret_values = secrets_of(f)
    f.sdk.account[field] = value
    key, session = new_pipe_key(), uuid4()
    output = io.BytesIO()
    code = _serve_actual_session(
        io.BytesIO(b""),
        output,
        key=key,
        session=session,
        port=f.port,
        rights=actual_rights(f.admission),
        source_hash=f.admission.binding.connector_source_hash,
    )
    assert code == 2 and f.sdk.shutdown_count == 1
    raw = output.getvalue()
    frame = decode_frame(raw, key=key, session=session, sequence=0, kind="ERROR", family=FAMILY)
    assert frame.payload == {"code": "DS03_UNAVAILABLE", "reason": reason}
    for value_text in secret_values:
        assert value_text.encode() not in raw


@pytest.mark.parametrize(
    "payload",
    [
        {"code": "DS03_UNAVAILABLE"},
        {"code": "DS03_UNAVAILABLE", "reason": "NOT_A_CODE"},
        {"code": "DS03_UNAVAILABLE", "reason": "123456789"},
        {"code": "DS03_UNAVAILABLE", "reason": ["ACCOUNT_NOT_DEMO"]},
        {"code": "OTHER", "reason": "ACCOUNT_NOT_DEMO"},
        {"code": "DS03_UNAVAILABLE", "reason": "ACCOUNT_NOT_DEMO", "detail": "x"},
    ],
)
def test_received_error_body_outside_the_closed_shape_is_a_protocol_fault(payload):
    with pytest.raises(Ds03ProtocolError):
        error_reason(Ds03Frame("ERROR", None, payload))
    with pytest.raises(Ds03ProtocolError):
        error_reason(Ds03Frame("REPLY", None, error_payload("ACCOUNT_NOT_DEMO")))
    assert error_reason(Ds03Frame("ERROR", None, error_payload("SPEC_DRIFT"))) == "SPEC_DRIFT"


def test_outcome_decoder_accepts_only_the_expected_kind_or_an_authenticated_error():
    key, session = new_pipe_key(), uuid4()
    error = encode_frame(
        "ERROR",
        error_payload("DEADLINE"),
        key=key,
        session=session,
        sequence=3,
        request_id=None,
        family=FAMILY,
    )
    frame = decode_outcome(error, key=key, session=session, sequence=3, kind="REPLY", family=FAMILY)
    assert frame.kind == "ERROR" and error_reason(frame) == "DEADLINE"
    request_frame = encode_frame(
        "REQUEST", {}, key=key, session=session, sequence=3, request_id=None, family=FAMILY
    )
    with pytest.raises(Ds03ProtocolError):
        decode_outcome(
            request_frame, key=key, session=session, sequence=3, kind="REPLY", family=FAMILY
        )
    with pytest.raises(Ds03ProtocolError):
        decode_outcome(
            error, key=new_pipe_key(), session=session, sequence=3, kind="REPLY", family=FAMILY
        )


class _Harness:
    """Parent process with a fake child that answers the bootstrap with a chosen frame."""

    def __init__(self, monkeypatch, f, answer):
        self.f, self.state = f, {"closed": False}
        state = self.state

        class Job:
            name = "Local" + chr(92) + "AuvexoAlphaDS03Readonly-" + "a" * 32

            def assign(self, process):
                state["assigned"] = True

            def close(self):
                state["closed"] = True

        class Process:
            def __init__(self, args, **kwargs):
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
            lines = raw.splitlines(keepends=True)
            if len(lines) == 2:
                key, session = read_bootstrap(
                    lines[0], f.admission.binding.connector_source_hash, family=FAMILY
                )
                state["key"], state["session"] = key, session
                return answer(key, session, 0, None)
            incoming = decode_frame(
                raw,
                key=state["key"],
                session=state["session"],
                sequence=state.setdefault("sequence", 1),
                kind="REQUEST",
                family=FAMILY,
            )
            state["sequence"] += 1
            return answer(
                state["key"], state["session"], state["sequence"] - 1, incoming.request_id
            )

        monkeypatch.setattr(ds03_mt5_process, "_measurement", lambda authority: f.admission.binding)
        monkeypatch.setattr(
            ds03_mt5_process.measured,
            "source_binding",
            lambda: f.admission.binding.connector_source_hash,
        )
        monkeypatch.setattr(ds03_mt5_process.measured, "provider_job", Job)
        monkeypatch.setattr(
            ds03_mt5_process.measured, "probe_terminal_process", lambda bound: f.observer.evidence
        )
        monkeypatch.setattr(ds03_mt5_process.subprocess, "Popen", Process)
        monkeypatch.setattr(ds03_mt5_process, "_exchange", exchange)
        fixed = ds03_mt5_process.measured.runtime_root() / ".venv" / "Scripts" / "python.exe"
        monkeypatch.setattr(sys, "executable", str(fixed))


def error_answer(reason_payload):
    def answer(key, session, sequence, request_id):
        return encode_frame(
            "ERROR",
            reason_payload,
            key=key,
            session=session,
            sequence=sequence,
            request_id=request_id,
            family=FAMILY,
        )

    return answer


@pytest.mark.parametrize(
    "payload,reason",
    [
        (error_payload("ACCOUNT_NOT_DEMO"), "ACCOUNT_NOT_DEMO"),
        (error_payload("TERMINAL_NOT_CONTAINED"), "TERMINAL_NOT_CONTAINED"),
        ({"code": "DS03_UNAVAILABLE", "reason": "synthetic-server.invalid"}, "IPC_PROTOCOL"),
        ({"code": "DS03_UNAVAILABLE"}, "IPC_PROTOCOL"),
    ],
)
def test_parent_start_surfaces_the_childs_closed_reason_and_closes(monkeypatch, payload, reason):
    f = fixture()
    harness = _Harness(monkeypatch, f, error_answer(payload))
    with pytest.raises(Ds03Error) as captured:
        ActualDs03Process(f.static).start()
    assert str(captured.value) == "DS03_UNAVAILABLE:" + reason
    assert harness.state["closed"]
    for value in secrets_of(f):
        assert value not in str(captured.value) + repr(captured.value)
    f.port.disconnect()


def test_parent_read_surfaces_in_session_error_reason_and_closes(monkeypatch):
    f = fixture()
    hello = {
        "binding": f.admission.binding.connector_source_hash,
        "attestation": f.port.attest().model_dump(mode="json"),
        "rights": actual_rights(f.admission).model_dump(mode="json"),
    }

    def answer(key, session, sequence, request_id):
        if sequence == 0:
            return encode_frame(
                "HELLO",
                hello,
                key=key,
                session=session,
                sequence=0,
                request_id=None,
                family=FAMILY,
            )
        return encode_frame(
            "ERROR",
            error_payload("SPEC_DRIFT"),
            key=key,
            session=session,
            sequence=sequence,
            request_id=request_id,
            family=FAMILY,
        )

    harness = _Harness(monkeypatch, f, answer)
    process = ActualDs03Process(f.static).start()
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE:SPEC_DRIFT$"):
        process.read(request(f, "SYMBOLS"))
    assert harness.state["closed"]
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE:SESSION_CLOSED$"):
        process.read(request(f, "SYMBOLS"))
    f.port.disconnect()


def test_parent_error_frame_for_another_request_is_a_protocol_fault(monkeypatch):
    f = fixture()
    hello = {
        "binding": f.admission.binding.connector_source_hash,
        "attestation": f.port.attest().model_dump(mode="json"),
        "rights": actual_rights(f.admission).model_dump(mode="json"),
    }

    def answer(key, session, sequence, request_id):
        if sequence == 0:
            return encode_frame(
                "HELLO",
                hello,
                key=key,
                session=session,
                sequence=0,
                request_id=None,
                family=FAMILY,
            )
        return encode_frame(
            "ERROR",
            error_payload("SPEC_DRIFT"),
            key=key,
            session=session,
            sequence=sequence,
            request_id=uuid4(),
            family=FAMILY,
        )

    _Harness(monkeypatch, f, answer)
    process = ActualDs03Process(f.static).start()
    with pytest.raises(Ds03Error, match="^DS03_UNAVAILABLE:IPC_PROTOCOL$"):
        process.read(request(f, "SYMBOLS"))
    f.port.disconnect()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda f: f.sdk.account.update(trade_mode=1),
        lambda f: f.sdk.account.update(login=1),
        lambda f: f.sdk.terminal.update(connected=False),
        lambda f: f.sdk.terminal.update(path="C:\\synthetic\\elsewhere"),
        lambda f: f.sdk.account.pop("server"),
        lambda f: setattr(f.observer, "bad", True),
    ],
)
def test_no_refusal_text_or_frame_ever_contains_private_values(mutate):
    f = fixture()
    secret_values = secrets_of(f)
    mutate(f)
    with pytest.raises(Ds03Error) as captured:
        f.port.attest()
    shown = (
        str(captured.value)
        + repr(captured.value)
        + json.dumps(error_payload(captured.value.reason))
    )
    assert captured.value.reason in REASON_CODES and captured.value.reason != "UNCLASSIFIED"
    for value in secret_values:
        assert value not in shown
