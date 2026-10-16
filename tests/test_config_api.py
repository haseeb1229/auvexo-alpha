import secrets

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from auvexo_alpha.api.app import create_app
from auvexo_alpha.config import Settings, load_settings
from auvexo_alpha.domain.contracts import Mode


class Probe:
    def __init__(self, healthy: bool = True) -> None:
        self.healthy = healthy

    def ready(self) -> bool:
        return self.healthy


def test_settings_load_and_redact() -> None:
    secret = secrets.token_urlsafe(32)
    env = {"AUVEXO_API_TOKEN": secret, "AUVEXO_DB_PASSWORD": secret}
    settings = load_settings(env)
    assert secret not in repr(settings)
    assert secret not in settings.model_dump_json()
    for key in (
        "AUVEXO_EXECUTION_ENABLED",
        "AUVEXO_ACCOUNT",
        "AUVEXO_PERMIT",
        "AUVEXO_BROKER_PASSWORD",
    ):
        with pytest.raises(ValueError):
            load_settings(env | {key: "synthetic-forbidden"})


@pytest.mark.parametrize(
    "change",
    [
        {"bind_host": "0.0.0.0"},
        {"bind_host": "::"},
        {"database_host": "example.com"},
        {"execution_enabled": True},
        {"database_name": "production"},
        {"database_user": "postgres"},
        {"port": 0},
        {"port": 65536},
        {"account_ref": "real"},
        {"policy_version": "allow-live"},
    ],
)
def test_r023_p1_config_elevation_refused(settings: Settings, change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(settings.model_dump() | change)


@pytest.mark.parametrize("mode", list(Mode))
def test_all_modes_parse_without_capability(settings: Settings, mode: Mode) -> None:
    loaded = load_settings(
        {
            "AUVEXO_MODE": mode.value,
            "AUVEXO_API_TOKEN": settings.api_token.get_secret_value(),
            "AUVEXO_DB_PASSWORD": settings.database_password.get_secret_value(),
        }
    )
    assert loaded.mode == mode
    assert loaded.execution_enabled is False


def client(settings: Settings, healthy: bool = True, peer: str = "127.0.0.1") -> TestClient:
    return TestClient(
        create_app(settings, Probe(healthy)), base_url="http://127.0.0.1:8765", client=(peer, 50000)
    )


def auth(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.api_token.get_secret_value()}"}


@pytest.mark.parametrize("path", ["live", "ready", "version", "policy", "metrics"])
def test_r023_p1_all_diagnostics_authenticated(settings: Settings, path: str) -> None:
    with client(settings) as api:
        assert api.get(f"/api/v1/{path}").status_code == 401
        assert (
            api.get(
                f"/api/v1/{path}", headers={"Authorization": "Bearer synthetic-invalid"}
            ).status_code
            == 401
        )
        result = api.get(f"/api/v1/{path}", headers=auth(settings))
        assert result.status_code == 200
        assert result.headers["Cache-Control"] == "no-store"
        assert settings.api_token.get_secret_value() not in result.text


def test_r027_p1_readiness_is_not_liveness(settings: Settings) -> None:
    with client(settings, healthy=False) as api:
        assert api.get("/api/v1/live", headers=auth(settings)).status_code == 200
        response = api.get("/api/v1/ready", headers=auth(settings))
        assert response.status_code == 503
        assert response.json()["status"] == "NOT_READY"


@pytest.mark.parametrize("headers", [{"Origin": "http://evil.example"}, {"Host": "evil.example"}])
def test_r023_p1_browser_and_dns_rebinding_denied(
    settings: Settings, headers: dict[str, str]
) -> None:
    with client(settings) as api:
        assert api.get("/api/v1/live", headers=auth(settings) | headers).status_code == 403


def test_r023_p1_nonloopback_peer_cannot_spoof_proxy(settings: Settings) -> None:
    with client(settings, peer="203.0.113.1") as api:
        assert (
            api.get(
                "/api/v1/live", headers=auth(settings) | {"X-Forwarded-For": "127.0.0.1"}
            ).status_code
            == 403
        )


@pytest.mark.parametrize(
    "path", ["/api/v1/orders", "/order_send", "/api/v1/activate", "/api/v1/withdraw"]
)
def test_r022_p1_no_arbitrary_order_endpoint(settings: Settings, path: str) -> None:
    with client(settings) as api:
        assert (
            api.post(
                path, headers=auth(settings), json={"side": "BUY", "permit": "fake"}
            ).status_code
            == 404
        )
