import secrets

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from auvexo_alpha import __version__
from auvexo_alpha.api.app import CONTENT_SECURITY_POLICY, PERMISSIONS_POLICY, create_app
from auvexo_alpha.config import Settings, load_settings
from auvexo_alpha.domain.contracts import Mode

AUTHORISED_MODES = [Mode.RESEARCH, Mode.BACKTEST, Mode.PAPER]
REFUSED_MODES = [Mode.DEMO, Mode.SHADOW, Mode.LIVE_LIMITED, Mode.LIVE]


class Probe:
    def __init__(self, healthy: bool = True) -> None:
        self.healthy = healthy

    def ready(self) -> bool:
        return self.healthy


class FailingProbe:
    def ready(self) -> bool:
        raise RuntimeError("synthetic-private-driver-detail")


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


def mode_environment(settings: Settings, mode: str) -> dict[str, str]:
    return {
        "AUVEXO_MODE": mode,
        "AUVEXO_API_TOKEN": settings.api_token.get_secret_value(),
        "AUVEXO_DB_PASSWORD": settings.database_password.get_secret_value(),
    }


def test_mode_policy_covers_every_mode() -> None:
    assert set(AUTHORISED_MODES) | set(REFUSED_MODES) == set(Mode)
    assert not set(AUTHORISED_MODES) & set(REFUSED_MODES)


@pytest.mark.parametrize("mode", AUTHORISED_MODES)
def test_authorised_modes_parse_without_capability(settings: Settings, mode: Mode) -> None:
    loaded = load_settings(mode_environment(settings, mode.value))
    assert loaded.mode == mode
    assert loaded.execution_enabled is False


@pytest.mark.parametrize("mode", REFUSED_MODES)
def test_r003_mode_label_never_trusted_from_environment(settings: Settings, mode: Mode) -> None:
    # A mode is an unverified label: later modes are refused at startup, never displayed.
    with pytest.raises(ValidationError) as refused:
        load_settings(mode_environment(settings, mode.value))
    assert "MODE_NOT_AUTHORISED" in str(refused.value)
    assert settings.api_token.get_secret_value() not in str(refused.value)
    with pytest.raises(ValidationError, match="MODE_NOT_AUTHORISED"):
        Settings.model_validate(settings.model_dump() | {"mode": mode})


@pytest.mark.parametrize("mode", ["live", "LIVE ", "PRODUCTION", ""])
def test_unknown_mode_label_refused(settings: Settings, mode: str) -> None:
    with pytest.raises(ValueError):
        load_settings(mode_environment(settings, mode))


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


def test_version_reports_build_without_a_phase_claim(settings: Settings) -> None:
    with client(settings) as api:
        result = api.get("/api/v1/version", headers=auth(settings))
        assert result.json() == {"version": __version__, "contract_version": "1.0"}


@pytest.mark.parametrize("authorized", [True, False])
def test_r023_p1_exact_security_headers_on_success_and_refusal(
    settings: Settings, authorized: bool
) -> None:
    assert CONTENT_SECURITY_POLICY == (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )
    assert PERMISSIONS_POLICY == (
        "accelerometer=(), autoplay=(), camera=(), display-capture=(), "
        "encrypted-media=(), fullscreen=(), geolocation=(), gyroscope=(), "
        "magnetometer=(), microphone=(), midi=(), payment=(), picture-in-picture=(), "
        "publickey-credentials-get=(), screen-wake-lock=(), usb=(), xr-spatial-tracking=()"
    )
    with client(settings) as api:
        result = api.get("/api/v1/live", headers=auth(settings) if authorized else {})
        assert result.status_code == (200 if authorized else 401)
        assert {
            name: result.headers[name]
            for name in (
                "Cache-Control",
                "X-Content-Type-Options",
                "Referrer-Policy",
                "X-Frame-Options",
                "Content-Security-Policy",
                "Cross-Origin-Resource-Policy",
                "Cross-Origin-Opener-Policy",
                "Permissions-Policy",
            )
        } == {
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": CONTENT_SECURITY_POLICY,
            "Cross-Origin-Resource-Policy": "same-origin",
            "Cross-Origin-Opener-Policy": "same-origin",
            "Permissions-Policy": PERMISSIONS_POLICY,
        }
        assert "Access-Control-Allow-Origin" not in result.headers


def test_unexpected_failure_logs_exception_class_never_message(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    api = TestClient(
        create_app(settings, FailingProbe()),
        base_url="http://127.0.0.1:8765",
        client=("127.0.0.1", 50000),
    )
    with api, caplog.at_level("DEBUG"):
        response = api.get("/api/v1/ready", headers=auth(settings))
    assert response.status_code == 503
    assert response.json() == {"code": "READ_UNAVAILABLE"}
    assert "PRESENTATION_READ_UNAVAILABLE error_class=RuntimeError" in caplog.text
    assert "synthetic-private-driver-detail" not in caplog.text + response.text
    assert settings.api_token.get_secret_value() not in caplog.text


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
