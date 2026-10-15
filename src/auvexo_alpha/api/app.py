"""No order endpoints. API authentication is development-only, not live activation."""

from __future__ import annotations

import hmac
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.responses import Response

from auvexo_alpha import __version__
from auvexo_alpha.application.ports import ReadinessProbe
from auvexo_alpha.application.safety import POLICY_VERSION
from auvexo_alpha.config import Settings
from auvexo_alpha.infrastructure.database import DatabaseProbe, make_engine


class Health(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ALIVE", "READY", "NOT_READY"]
    execution_enabled: Literal[False] = False


def create_app(settings: Settings, probe: ReadinessProbe | None = None) -> FastAPI:
    engine = make_engine(settings) if probe is None else None
    actual_probe: ReadinessProbe
    if probe is not None:
        actual_probe = probe
    else:
        assert engine is not None
        actual_probe = DatabaseProbe(engine)
    started = time.monotonic()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        if engine is not None:
            engine.dispose()

    app = FastAPI(
        title="Auvexo Alpha local diagnostics",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def local_auth(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        host = request.headers.get("host", "")
        peer = request.client.host if request.client else ""
        if peer != "127.0.0.1" or host not in {"127.0.0.1", f"127.0.0.1:{settings.port}"}:
            return JSONResponse({"code": "UNAUTHORIZED"}, status_code=403)
        if "origin" in request.headers:
            return JSONResponse({"code": "UNAUTHORIZED"}, status_code=403)
        provided = request.headers.get("authorization", "")
        expected = f"Bearer {settings.api_token.get_secret_value()}"
        if not hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
            return JSONResponse({"code": "UNAUTHORIZED"}, status_code=401)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/api/v1/live", response_model=Health)
    def live() -> Health:
        return Health(status="ALIVE")

    @app.get("/api/v1/ready", response_model=Health)
    def ready() -> Health | JSONResponse:
        if not actual_probe.ready():
            return JSONResponse(Health(status="NOT_READY").model_dump(), status_code=503)
        return Health(status="READY")

    @app.get("/api/v1/version")
    def version() -> dict[str, str]:
        return {"version": __version__, "contract_version": "1.0", "phase": "1"}

    @app.get("/api/v1/policy")
    def policy() -> dict[str, str | bool]:
        return {
            "mode": settings.mode.value,
            "policy_version": POLICY_VERSION,
            "execution_enabled": False,
            "binance_live_derivatives": "BLOCKED_BY_POLICY",
            "exness_real": "DISABLED",
        }

    @app.get("/api/v1/metrics")
    def metrics() -> dict[str, int]:
        return {"uptime_seconds": int(time.monotonic() - started), "execution_capabilities": 0}

    return app
