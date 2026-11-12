"""Synthetic read API and static bootstrap security; no runtime integration."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import get_args

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import URL, create_engine

from auvexo_alpha.api.app import CONTENT_SECURITY_POLICY, PERMISSIONS_POLICY, create_app
from auvexo_alpha.application.terminal_models import (
    REVIEWED_AS_OF,
    Freshness,
    JournalEvent,
    JournalReason,
    PaperView,
    TerminalSnapshot,
)
from auvexo_alpha.application.terminal_reads import UnconnectedTerminalReads
from auvexo_alpha.infrastructure.terminal_paper import PostgresTerminalReads, journal_reason


class Probe:
    def ready(self) -> bool:
        return False


PATHS = ["system", "qualification", "reviewed", "paper", "research", "journal", "snapshot"]

# Every kind literal passed to PaperStore._append in infrastructure/paper_store.py,
# collected by reading that file. A new stored kind must be added here and reviewed.
STORED_JOURNAL_KINDS = {
    "INITIALIZED": "INITIALIZED",
    "WRITER_ACQUIRED_PAUSE_NEW": "WRITER_ACQUIRED",
    "KILL_STATE": "KILL_STATE",
    "OWNER_PAPER_RESUME": "OWNER_RESUME",
    "LOSS_BREACH_LATCH": "LOSS_LATCH",
    "UTC_DAY_ROLLOVER": "DAY_ROLLOVER",
    "DENIED": "DENIED",
    "AUTHORIZED": "AUTHORIZED",
    "DISPATCH_ATTEMPT": "DISPATCH_ATTEMPT",
    "UNKNOWN_RECONCILE_ONLY": "UNKNOWN_ORDER",
    "EDGE_STATE": "EDGE_STATE",
    "OWNER_RELEASE_PIN": "OWNER_PIN",
    "OWNER_POLICY_PIN": "OWNER_PIN",
    "RECONCILED_ORDER": "RECONCILIATION",
    "MARK_HEALTH": "MARK_HEALTH",
    "RECONCILIATION": "RECONCILIATION",
}


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
        assert value.qualification.phase2_days is None and value.system.source == "UNKNOWN"
        assert value.paper.balance is None and value.paper.active_reservations is None
        assert (
            value.paper.freshness.state == "UNKNOWN" and value.journal.freshness.state == "UNKNOWN"
        )
        assert (
            value.research.outcomes == ("INCONCLUSIVE",) * 4 and value.research.champion == "NONE"
        )
        assert set(response.json()["qualification"]) == {
            "phase2_days",
            "phase4_days",
            "task",
            "freshness",
        }
        assert "gateway" not in response.json()["system"]
        with pytest.raises(ValidationError):
            TerminalSnapshot.model_validate_json(json.dumps(response.json() | {"dsn": "secret"}))
        with pytest.raises(ValidationError):
            PaperView.model_validate_json(json.dumps(response.json()["paper"] | {"balance": "NaN"}))


def test_terminal_reviewed_statements_are_labelled_static_never_operational(settings):
    with client(settings) as api:
        snapshot = api.get("/api/v1/terminal/snapshot", headers=auth(settings)).json()
        reviewed = api.get("/api/v1/terminal/reviewed", headers=auth(settings)).json()
    assert reviewed == snapshot["reviewed"]
    assert reviewed.pop("scope") == "STATIC_REVIEWED_ENGINEERING_SUMMARY_NOT_MEASURED"
    assert {name: item["status"] for name, item in reviewed.items()} == {
        "phase2": "OPERATIONAL_ACCEPTANCE_OPEN",
        "phase4_observation": "ENGINEERING_ACCEPTED_OPERATIONAL_ACCEPTANCE_OPEN",
        "phase5": "OFFLINE_ACCEPTED_COMMISSIONING_NOT_STARTED",
        "ds03": "ENGINEERING_ONLY_NO_ACCOUNT",
        "gateway": "SYNTHETIC_OFFLINE_ONLY",
        "broker_transport": "NONE",
        "permit_issuer": "NONE",
        "binance_live_derivatives": "BLOCKED_BY_POLICY",
    }
    for item in reviewed.values():
        assert item["operational"] == "UNKNOWN"
        assert item["provenance"] == "REVIEWED_ENGINEERING"
        assert item["reason"] == "REVIEWED_SUMMARY"
        assert item["as_of"] == REVIEWED_AS_OF
    # No static statement may assert that anything is active, running or ready.
    text = json.dumps(snapshot)
    assert not any(word in text for word in ("ACTIVE", "RUNNING", "OBSERVATION_", 'BLOCKED"'))
    assert '"READY"' not in json.dumps(reviewed)


@pytest.mark.parametrize("field", ["operational", "provenance", "reason", "as_of", "status"])
def test_terminal_reviewed_statement_cannot_claim_measurement(field):
    value = TerminalSnapshot.model_validate_json(
        (
            Path(__file__).resolve().parents[1]
            / "web/operator-terminal/tests/synthetic-snapshot.json"
        ).read_bytes()
    ).model_dump(mode="json")
    value["reviewed"]["phase4_observation"][field] = {
        "operational": "ACTIVE",
        "provenance": "LOCAL_DIAGNOSTICS",
        "reason": "CURRENT",
        "as_of": "today",
        "status": "OBSERVATION_ACTIVE_OPERATIONAL_OPEN",
    }[field]
    with pytest.raises(ValidationError):
        TerminalSnapshot.model_validate_json(json.dumps(value))


def test_terminal_journal_maps_every_stored_kind_to_reviewed_enum():
    reasons = set(get_args(JournalReason))
    for kind, expected in STORED_JOURNAL_KINDS.items():
        assert journal_reason(kind) == expected, kind
        assert expected in reasons and expected != "OTHER", kind
    # The safety-relevant kinds an operator must recognise are never the catch-all.
    assert journal_reason("KILL_STATE") == "KILL_STATE"
    assert journal_reason("LOSS_BREACH_LATCH") == "LOSS_LATCH"
    assert journal_reason("UNKNOWN_RECONCILE_ONLY") == "UNKNOWN_ORDER"
    # Every reviewed value except the catch-all is reachable from a stored kind.
    assert set(STORED_JOURNAL_KINDS.values()) == reasons - {"OTHER"}
    for unknown in ("KILL_CHANGED", "RECONCILED", "kill_state", "", "<script>", "DROP TABLE"):
        assert journal_reason(unknown) == "OTHER"
    assert "decision_hash" not in JournalEvent.model_fields


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class _Connection:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, statement, parameters):
        assert str(statement).lstrip().startswith("SELECT sequence,recorded_at,kind")
        return _Rows(self.rows)


def _offline_projection(monkeypatch, rows):
    # No connection is opened: the engine is never used and the read is substituted.
    engine = create_engine(
        URL.create(
            "postgresql+psycopg",
            username="auvexo_read_" + "a" * 20,
            password="synthetic-only-" + "0" * 32,
            host="127.0.0.1",
            port=55432,
            database="auvexo_test_" + "a" * 20,
        )
    )
    projection = PostgresTerminalReads(engine, "paper.synthetic")

    @contextmanager
    def connection():
        yield _Connection(rows)

    monkeypatch.setattr(projection, "_connection", connection)
    return projection


def test_terminal_journal_empty_is_connected_no_events_not_unknown(monkeypatch):
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    journal = _offline_projection(monkeypatch, []).journal(now=now)
    assert journal.events == ()
    assert journal.freshness == Freshness(
        state="AVAILABLE",
        observed_at=now,
        provenance="ISOLATED_SYNTHETIC_PAPER",
        reason="NO_EVENTS",
    )


def test_terminal_journal_quiet_is_current_as_of_read_not_stale(monkeypatch):
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    rows = [
        {
            "sequence": 2,
            "recorded_at": now - timedelta(hours=6),
            "kind": "KILL_STATE",
            "intent_hash": None,
            "content_hash": "b" * 64,
        },
        {
            "sequence": 1,
            "recorded_at": now - timedelta(days=2),
            "kind": "SOME_FUTURE_KIND",
            "intent_hash": "c" * 64,
            "content_hash": "a" * 64,
        },
    ]
    journal = _offline_projection(monkeypatch, rows).journal(now=now)
    assert journal.freshness.state == "AVAILABLE" and journal.freshness.reason == "CURRENT"
    assert journal.freshness.observed_at == now
    assert [e.reason for e in journal.events] == ["KILL_STATE", "OTHER"]
    assert journal.events[0].observed_at == now - timedelta(hours=6)
    assert "SOME_FUTURE_KIND" not in journal.model_dump_json()


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
            assert r.headers["Content-Security-Policy"] == CONTENT_SECURITY_POLICY
            assert r.headers["Cross-Origin-Resource-Policy"] == "same-origin"
            assert r.headers["Cross-Origin-Opener-Policy"] == "same-origin"
            assert r.headers["Permissions-Policy"] == PERMISSIONS_POLICY
            assert r.headers["X-Content-Type-Options"] == "nosniff"
            assert r.headers["X-Frame-Options"] == "DENY"
            assert settings.api_token.get_secret_value() not in r.text
        for path in ["/private.json", "/assets/../private.json", "/api/v1/terminal/snapshot"]:
            assert api.get(path).status_code != 200
        for path in [
            "/assets/%2e%2e/private.json",
            "/assets/%2E%2E%2Fprivate.json",
            "/assets/..%2fprivate.json",
            "/assets/..%5cprivate.json",
            "/assets/%2e%2e/index.html",
            "/assets/index-123.js%2f..%2f..%2fprivate.json",
            "/%2e%2e/private.json",
        ]:
            for headers in ({}, auth(settings)):
                r = api.get(path, headers=headers)
                assert r.status_code in (401, 404), path
                assert "NEVER_EXPOSED" not in r.text and "Data-free" not in r.text
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


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1:9999",
        "127.0.0.1:80",
        "localhost",
        "localhost:8765",
        "LOCALHOST:8765",
        "[::1]:8765",
        "127.0.0.1.evil.example:8765",
        "0.0.0.0:8765",
        "",
    ],
)
@pytest.mark.parametrize("path", ["/", "/index.html", "/assets/index-123.js"])
def test_terminal_static_routes_refuse_wrong_port_and_localhost_host(
    settings, tmp_path, host, path
):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>Data-free sign in</html>")
    (tmp_path / "assets" / "index-123.js").write_text("export {}")
    with client(settings, static_root=tmp_path) as api:
        assert api.get(path).status_code == 200
        for headers in ({"Host": host}, {"Host": host} | auth(settings)):
            r = api.get(path, headers=headers)
            assert r.status_code == 403 and r.json() == {"code": "UNAUTHORIZED"}
            assert r.headers["Cache-Control"] == "no-store"
        assert (
            api.get(
                "/api/v1/terminal/snapshot", headers={"Host": host} | auth(settings)
            ).status_code
            == 403
        )


@pytest.mark.parametrize(
    "authorization",
    [None, "Bearer synthetic-invalid-guess", "Basic synthetic", "Bearer {token}x", "{token}"],
)
def test_terminal_unauthorized_path_never_logs_any_token(settings, caplog, authorization):
    token = settings.api_token.get_secret_value()
    supplied = None if authorization is None else authorization.format(token=token)
    with client(settings) as api, caplog.at_level("DEBUG"):
        r = api.get(
            "/api/v1/terminal/snapshot",
            headers={} if supplied is None else {"Authorization": supplied},
        )
    assert r.status_code == 401 and r.json() == {"code": "UNAUTHORIZED"}
    assert token not in caplog.text and token not in r.text
    assert "synthetic-invalid-guess" not in caplog.text
    assert "Bearer" not in caplog.text and "Authorization" not in caplog.text


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
    assert json.loads(fixture.read_bytes()) == value.model_dump(mode="json")
    populated = root / "web/operator-terminal/tests/synthetic-populated-snapshot.json"
    full = TerminalSnapshot.model_validate_json(populated.read_bytes())
    assert json.loads(populated.read_bytes()) == full.model_dump(mode="json")
    assert full.paper.kill == "K4" and full.paper.reconciled is False
    assert full.paper.unknown_orders is True and full.paper.positions and full.paper.pending
    assert full.paper.freshness.provenance == "ISOLATED_SYNTHETIC_PAPER"
    assert {e.reason for e in full.journal.events} == set(get_args(JournalReason))


class FailedReads(UnconnectedTerminalReads):
    def __init__(self, *failing: str) -> None:
        self.failing = failing

    def qualification(self, *, now):
        if "qualification" in self.failing:
            raise KeyError("synthetic-private-driver-detail")
        return super().qualification(now=now)

    def paper(self, *, now):
        if "paper" in self.failing:
            raise RuntimeError("synthetic-private-driver-detail")
        return super().paper(now=now)

    def journal(self, *, now):
        if "journal" in self.failing:
            raise OSError("synthetic-private-driver-detail")
        return super().journal(now=now)


def test_terminal_one_failed_view_is_unavailable_while_others_render(settings, caplog):
    # The former all-or-nothing 503 blanked system health for one failing read.
    with client(settings, terminal_reads=FailedReads("paper")) as api:
        response = api.get("/api/v1/terminal/snapshot", headers=auth(settings))
        single = api.get("/api/v1/terminal/paper", headers=auth(settings))
    assert response.status_code == 200 and single.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    value = TerminalSnapshot.model_validate_json(response.content)
    assert value.paper == PaperView.model_validate_json(single.content)
    assert value.paper.freshness == Freshness(
        state="UNAVAILABLE", provenance="LOCAL_DIAGNOSTICS", reason="READ_UNAVAILABLE"
    )
    assert value.paper.balance is None and value.paper.positions == ()
    assert value.system.api == "ALIVE" and value.system.freshness.state == "AVAILABLE"
    assert value.qualification.freshness.reason == "NOT_CONNECTED"
    assert value.journal.freshness.reason == "NOT_CONNECTED"
    assert value.research.outcomes == ("INCONCLUSIVE",) * 4
    assert "synthetic-private-driver-detail" not in response.text + caplog.text
    assert "PRESENTATION_VIEW_UNAVAILABLE view=paper error_class=RuntimeError" in caplog.text
    assert settings.api_token.get_secret_value() not in caplog.text


def test_terminal_system_health_always_renders(settings, caplog):
    class FailingProbe:
        def ready(self) -> bool:
            raise ConnectionError("synthetic-private-driver-detail")

    api = TestClient(
        create_app(
            settings,
            FailingProbe(),
            terminal_reads=FailedReads("qualification", "paper", "journal"),
        ),
        base_url="http://127.0.0.1:8765",
        client=("127.0.0.1", 1234),
    )
    with api:
        response = api.get("/api/v1/terminal/snapshot", headers=auth(settings))
    assert response.status_code == 200
    value = TerminalSnapshot.model_validate_json(response.content)
    assert value.system.api == "ALIVE" and value.system.database == "NOT_READY"
    assert value.system.execution_enabled is False and value.system.live_authority == "LOCKED"
    for view in (value.qualification, value.paper, value.journal):
        assert view.freshness.state == "UNAVAILABLE"
        assert view.freshness.reason == "READ_UNAVAILABLE"
    assert value.qualification.phase4_days is None and value.journal.events == ()
    assert value.reviewed.ds03.status == "ENGINEERING_ONLY_NO_ACCOUNT"
    assert "synthetic-private-driver-detail" not in response.text + caplog.text
    for line in (
        "view=database error_class=ConnectionError",
        "view=qualification error_class=KeyError",
        "view=paper error_class=RuntimeError",
        "view=journal error_class=OSError",
    ):
        assert "PRESENTATION_VIEW_UNAVAILABLE " + line in caplog.text
