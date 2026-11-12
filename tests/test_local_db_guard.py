"""The local cluster tool must never take or share another checkout's fixed port."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import local_db  # noqa: E402


def _listening(port: int) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=port)),
        SimpleNamespace(status="ESTABLISHED", laddr=SimpleNamespace(port=local_db.PORT)),
        SimpleNamespace(status=psutil.CONN_LISTEN, laddr=()),
    ]


@pytest.fixture
def no_effects(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    """Any attempt to initialise, start or write secrets is recorded as a failure."""
    effects: list[str] = []
    monkeypatch.setattr(local_db, "DATA", tmp_path / "postgres-data")
    monkeypatch.setattr(local_db, "LOCAL", tmp_path)
    monkeypatch.setattr(local_db, "SECRET", tmp_path / "dev-secrets.json")
    monkeypatch.setattr(local_db, "run_pg", lambda *a, **k: effects.append("pg:" + a[0]))
    monkeypatch.setattr(local_db, "write_private", lambda *a, **k: effects.append("secret"))
    return effects


def test_refuses_to_create_a_cluster_without_explicit_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_effects: list[str]
) -> None:
    monkeypatch.setattr(psutil, "net_connections", lambda kind: [])
    with pytest.raises(RuntimeError, match="^NO_CLUSTER_IN_THIS_CHECKOUT"):
        local_db.start()
    assert no_effects == [] and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("create", [False, True])
def test_refuses_when_another_cluster_listens_on_the_fixed_port(
    create: bool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_effects: list[str]
) -> None:
    # No cluster of our own exists, yet something listens on 55432: it is not ours.
    monkeypatch.setattr(psutil, "net_connections", lambda kind: _listening(local_db.PORT))
    with pytest.raises(RuntimeError, match="^PORT_55432_OWNED_BY_ANOTHER_CLUSTER"):
        local_db.start(create=create)
    assert no_effects == [] and list(tmp_path.iterdir()) == []


def test_other_ports_and_non_listening_sockets_do_not_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(psutil, "net_connections", lambda kind: _listening(local_db.PORT + 1))
    assert local_db.port_listener() is False
    monkeypatch.setattr(psutil, "net_connections", lambda kind: _listening(local_db.PORT))
    assert local_db.port_listener() is True


def test_existing_stopped_cluster_is_refused_while_the_port_is_taken(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_effects: list[str]
) -> None:
    data = tmp_path / "postgres-data"
    data.mkdir()
    (data / "PG_VERSION").write_text("17\n", encoding="ascii")
    monkeypatch.setattr(
        local_db.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=3)
    )  # pg_ctl status: not running
    monkeypatch.setattr(psutil, "net_connections", lambda kind: _listening(local_db.PORT))
    with pytest.raises(RuntimeError, match="^PORT_55432_OWNED_BY_ANOTHER_CLUSTER"):
        local_db.start()
    assert no_effects == []
