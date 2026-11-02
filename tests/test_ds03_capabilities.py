"""Static and dynamic capability denial; an SDK is never imported or exposed."""

from __future__ import annotations

import ast
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from auvexo_alpha.domain.ds03 import SymbolsRequest
from auvexo_alpha.infrastructure import ds03_process as module
from auvexo_alpha.infrastructure.ds03_fake import SyntheticDs03Terminal, synthetic_identity
from auvexo_alpha.infrastructure.ds03_ipc import (
    bootstrap_frame,
    decode_frame,
    encode_frame,
    new_pipe_key,
)

_FORBIDDEN = ("order_send", "order_check", "modify", "cancel", "trade_request", "arbitrary_method")


@pytest.mark.parametrize("operation", _FORBIDDEN)
def test_arbitrary_or_trade_operation_never_invokes_backend(
    operation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Spy(SyntheticDs03Terminal):
        def execute(self, request: object) -> object:
            calls.append("read")
            return super().execute(request)

        def order_send(self) -> None:
            calls.append("TRADE")
            raise AssertionError("Forbidden operation invoked")

    monkeypatch.setattr(module, "SyntheticDs03Terminal", Spy)
    key, session, now = new_pipe_key(), uuid4(), datetime.now(UTC)
    identity = synthetic_identity()
    data = SymbolsRequest(
        request_id=uuid4(),
        created_at=now,
        expires_at=now + timedelta(seconds=10),
        release_hash=identity.release_hash,
        config_hash=identity.config_hash,
    ).model_dump(mode="json")
    data["operation"] = operation
    raw = bootstrap_frame(key, session, module.source_binding())
    raw += encode_frame("REQUEST", data, key=key, session=session, sequence=1, request_id=uuid4())
    output = io.BytesIO()
    assert module.serve_synthetic(io.BytesIO(raw), output) == 2
    assert calls == []
    lines = output.getvalue().splitlines(keepends=True)
    assert len(lines) == 2
    assert decode_frame(lines[-1], key=key, session=session, sequence=1, kind="ERROR").payload == {
        "code": "DS03_UNAVAILABLE"
    }


def test_connector_has_no_broker_network_reflection_or_execution_imports() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "src/auvexo_alpha/infrastructure" / (name + ".py")
        for name in ("ds03_fake", "ds03_ipc", "ds03_process")
    ]
    paths.append(root / "tools/ds03_connector.py")
    forbidden_imports = {"MetaTrader5", "socket", "requests", "httpx", "urllib"}
    forbidden_calls = {*_FORBIDDEN, "getattr", "eval", "exec", "compile", "__import__", "system"}
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(
                    alias.name.split(".")[0] in forbidden_imports for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom):
                assert node.module is not None
                assert node.module.split(".")[0] not in forbidden_imports
                assert not any(word in node.module for word in ("gateway", "paper", "execution"))
            elif isinstance(node, ast.Call):
                name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else (node.func.attr if isinstance(node.func, ast.Attribute) else "")
                )
                assert name not in forbidden_calls
    assert all(not hasattr(SyntheticDs03Terminal(), name) for name in _FORBIDDEN)
