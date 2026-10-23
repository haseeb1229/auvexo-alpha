"""Synthetic read API and static bootstrap security; no runtime integration."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from auvexo_alpha.api.app import create_app
from auvexo_alpha.application.terminal_models import Freshness, PaperView, TerminalSnapshot
from auvexo_alpha.application.terminal_reads import UnconnectedTerminalReads


class Probe:
    def ready(self) -> bool:
        return False


PATHS = ["system", "qualification", "paper", "research", "journal", "snapshot"]


def client(settings, **kwargs):
    return TestClient(
        create_app(settings, Probe(), **kwargs),
        base_url="http://127.0.0.1:8765",
        client=("127.0.0.1", 1234),
    )


def auth(settings):
    return {"Authorization": "Bearer " + settings.api_token.get_secret_value()}


@pytest.mark.parametrize("name", PATHS)
@pytest.mark.parametrize(
    "authorization", [None, "", "Bearer", "Basic synthetic", "Bearer synthetic-invalid"]
)
def test_terminal_every_read_requires_auth(settings, name, authorization):
    with client(settings) as api:
        headers = {} if authorization is None else {"Authorization": authorization}
        r = api.get("/api/v1/terminal/" + name, headers=headers)
        assert r.status_code == 401
        assert r.headers["Cache-Control"] == "no-store"
        assert r.headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors" in r.headers["Content-Security-Policy"]
        assert settings.api_token.get_secret_value() not in r.text


@pytest.mark.parametrize("name", PATHS)
def test_terminal_only_get_no_hidden_mutation(settings, name):
    with client(settings) as api:
        for method in ["post", "put", "patch", "delete"]:
            assert (
                getattr(api, method)("/api/v1/terminal/" + name, headers=auth(settings)).status_code
                == 405
            )


@pytest.mark.parametrize(
    "name",
    ["orders", "activate", "kill", "resume", "dispatch", "sql", "files", "withdraw", "transfer"],
)
def test_terminal_has_no_commands(settings, name):
    with client(settings) as api:
        assert api.post("/api/v1/terminal/" + name, headers=auth(settings)).status_code == 404


def test_terminal_unconnected_truth_and_strict_schema(settings):
    with client(settings) as api:
        response = api.get("/api/v1/terminal/snapshot", headers=auth(settings))
        assert response.status_code == 200
        value = TerminalSnapshot.model_validate_json(response.content)
        assert value.system.execution_enabled is False and value.system.database == "NOT_READY"
        assert value.qualification.phase4_days is None and value.qualification.task == "UNKNOWN"
        assert value.paper.balance is None and value.paper.active_reservations is None
        assert (
            value.paper.freshness.state == "UNKNOWN" and value.journal.freshness.state == "UNKNOWN"
        )
        assert (
            value.research.outcomes == ("INCONCLUSIVE",) * 4 and value.research.champion == "NONE"
        )
        assert value.qualification.ds03 == "BLOCKED"
        with pytest.raises(ValidationError):
            TerminalSnapshot.model_validate_json(json.dumps(response.json() | {"dsn": "secret"}))
        with pytest.raises(ValidationError):
            PaperView.model_validate_json(json.dumps(response.json()["paper"] | {"balance": "NaN"}))


@pytest.mark.parametrize(
    "change",
    [
        {"state": "READY"},
        {"observed_at": datetime.now()},
        {"observed_at": datetime.now(UTC) + timedelta(hours=1), "provenance": "arbitrary"},
    ],
)
def test_terminal_freshness_strict(change):
    with pytest.raises(ValidationError):
        Freshness.model_validate(
            {"state": "UNKNOWN", "provenance": "UNCONNECTED", "reason": "NOT_CONNECTED"} | change
        )


def test_terminal_static_shell_only_allowlist_and_safe_headers(settings, tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>Data-free sign in</html>")
    (tmp_path / "assets" / "index-123.js").write_text("export {}")
    (tmp_path / "private.json").write_text("NEVER_EXPOSED")
    with client(settings, static_root=tmp_path) as api:
        for path in ["/", "/index.html", "/assets/index-123.js"]:
            r = api.get(path)
            assert r.status_code == 200
            assert (
                r.headers["Cache-Control"] == "no-store"
                and r.headers["Referrer-Policy"] == "no-referrer"
            )
            assert settings.api_token.get_secret_value() not in r.text
        for path in ["/private.json", "/assets/../private.json", "/api/v1/terminal/snapshot"]:
            assert api.get(path).status_code != 200
        assert api.get("/assets/private.json", headers=auth(settings)).status_code == 404
        assert api.get("/?token=synthetic", headers=auth(settings)).status_code == 400
        assert api.get("/openapi.json", headers=auth(settings)).status_code == 404
        assert api.get("/docs", headers=auth(settings)).status_code == 404


@pytest.mark.parametrize(
    "origin", ["http://evil.example", "null", "http://localhost:8765", "http://127.0.0.1:5173"]
)
def test_terminal_remote_origins_refused_by_default(settings, origin):
    with client(settings) as api:
        assert (
            api.get(
                "/api/v1/terminal/snapshot", headers=auth(settings) | {"Origin": origin}
            ).status_code
            == 403
        )
        assert api.get("/", headers={"Origin": origin}).status_code == 403


def test_terminal_exact_dev_origin_opt_in_and_no_auth_exception(settings):
    with client(settings, allow_dev_origin=True) as api:
        headers = {"Origin": "http://127.0.0.1:5173"}
        assert api.get("/api/v1/terminal/snapshot", headers=headers).status_code == 401
        r = api.get("/api/v1/terminal/snapshot", headers=headers | auth(settings))
        assert r.status_code == 200
        assert r.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5173"
        assert "Access-Control-Allow-Credentials" not in r.headers
        preflight = api.options(
            "/api/v1/terminal/snapshot",
            headers=headers
            | {
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert preflight.status_code == 204 and not preflight.content
        assert (
            api.options(
                "/api/v1/terminal/snapshot",
                headers=headers | {"Access-Control-Request-Method": "POST"},
            ).status_code
            == 403
        )


def test_terminal_nonloopback_peer_and_host_denied(settings):
    with TestClient(
        create_app(settings, Probe()),
        base_url="http://127.0.0.1:8765",
        client=("203.0.113.1", 1234),
    ) as api:
        assert api.get("/", headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 403
    with client(settings) as api:
        assert api.get("/", headers={"Host": "evil.example"}).status_code == 403


def test_terminal_presentation_adapter_has_no_commands():
    reads = UnconnectedTerminalReads()
    assert not any(
        hasattr(reads, name) for name in ["submit", "execute", "kill", "resume", "dispatch"]
    )


def test_terminal_committed_schema_and_fixture_match_contract():
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "web/operator-terminal/contract.schema.json").read_text())
    assert schema == TerminalSnapshot.model_json_schema()
    fixture = root / "web/operator-terminal/tests/synthetic-snapshot.json"
    value = TerminalSnapshot.model_validate_json(fixture.read_bytes())
    assert value.qualification.phase4_days is None
    assert value.paper.freshness.provenance == "UNCONNECTED"
    assert value.research.candidate == "NONE"


def test_terminal_unexpected_read_failure_is_redacted_and_unavailable(settings, caplog):
    class FailedReads(UnconnectedTerminalReads):
        def paper(self, *, now):
            raise RuntimeError("synthetic-private-driver-detail")

    with client(settings, terminal_reads=FailedReads()) as api:
        response = api.get("/api/v1/terminal/snapshot", headers=auth(settings))
        assert response.status_code == 503
        assert response.json() == {"code": "READ_UNAVAILABLE"}
        assert response.headers["Cache-Control"] == "no-store"
        assert "synthetic-private-driver-detail" not in response.text
        assert "synthetic-private-driver-detail" not in caplog.text
        assert "PRESENTATION_READ_UNAVAILABLE" in caplog.text
