"""No order endpoints. API authentication is development-only, not live activation."""

from __future__ import annotations

import hmac
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.responses import Response

from auvexo_alpha import __version__
from auvexo_alpha.api.terminal import terminal_router
from auvexo_alpha.application.ports import ReadinessProbe
from auvexo_alpha.application.safety import POLICY_VERSION
from auvexo_alpha.application.terminal_reads import TerminalReadPort, UnconnectedTerminalReads
from auvexo_alpha.config import Settings
from auvexo_alpha.infrastructure.database import DatabaseProbe, make_engine


class Health(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ALIVE", "READY", "NOT_READY"]
    execution_enabled: Literal[False] = False


def create_app(
    settings: Settings,
    probe: ReadinessProbe | None = None,
    *,
    terminal_reads: TerminalReadPort | None = None,
    static_root: Path | None = None,
    allow_dev_origin: bool = False,
) -> FastAPI:
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

    build_root = static_root or Path(__file__).resolve().parents[3] / "web/operator-terminal/dist"
    build_root = build_root.resolve()
    origin = f"http://127.0.0.1:{settings.port}"
    dev_origin = "http://127.0.0.1:5173"
    allowed_origins = {origin} | ({dev_origin} if allow_dev_origin else set())

    def is_static(path: str) -> bool:
        return (
            path in {"/", "/index.html"}
            or re.fullmatch(r"/assets/[A-Za-z0-9_-]+\.(js|css)", path) is not None
        )

    async def safe_read_response(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            return await call_next(request)
        except Exception:
            # Presentation-only boundary: stable unavailable response and redacted alert.
            # Never log request headers, tokens, raw driver errors or private payloads.
            logging.getLogger(__name__).error("PRESENTATION_READ_UNAVAILABLE")
            return JSONResponse({"code": "READ_UNAVAILABLE"}, status_code=503)

    @app.middleware("http")
    async def local_auth(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        host = request.headers.get("host", "")
        peer = request.client.host if request.client else ""
        supplied_origin = request.headers.get("origin")
        response: Response
        if peer != "127.0.0.1" or host not in {"127.0.0.1", f"127.0.0.1:{settings.port}"}:
            response = JSONResponse({"code": "UNAUTHORIZED"}, status_code=403)
        elif supplied_origin is not None and supplied_origin not in allowed_origins:
            response = JSONResponse({"code": "UNAUTHORIZED"}, status_code=403)
        elif request.url.query:
            response = JSONResponse({"code": "QUERY_NOT_ALLOWED"}, status_code=400)
        elif (
            request.method == "OPTIONS"
            and allow_dev_origin
            and supplied_origin == dev_origin
            and request.url.path.startswith("/api/v1/")
        ):
            if (
                request.headers.get("access-control-request-method") == "GET"
                and request.headers.get("access-control-request-headers", "").lower()
                == "authorization"
            ):
                response = Response(
                    status_code=204,
                    headers={
                        "Access-Control-Allow-Methods": "GET",
                        "Access-Control-Allow-Headers": "Authorization",
                    },
                )
            else:
                response = JSONResponse({"code": "UNAUTHORIZED"}, status_code=403)
        elif request.method in {"GET", "HEAD"} and is_static(request.url.path):
            response = await safe_read_response(request, call_next)
        else:
            provided = request.headers.get("authorization", "")
            expected = f"Bearer {settings.api_token.get_secret_value()}"
            if not hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
                response = JSONResponse({"code": "UNAUTHORIZED"}, status_code=401)
            else:
                response = await safe_read_response(request, call_next)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self'; base-uri 'none'; form-action "
            "'none'; frame-ancestors 'none'"
        )
        if allow_dev_origin and supplied_origin == dev_origin:
            response.headers["Access-Control-Allow-Origin"] = dev_origin
            response.headers["Vary"] = "Origin"
        return response

    @app.get("/", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    def shell() -> Response:
        path = build_root / "index.html"
        if not path.is_file() or path.is_symlink():
            return JSONResponse({"code": "TERMINAL_BUILD_UNAVAILABLE"}, status_code=503)
        return FileResponse(path, media_type="text/html")

    @app.get("/assets/{name}", include_in_schema=False)
    def asset(name: str) -> Response:
        path = build_root / "assets" / name
        if (
            not is_static("/assets/" + name)
            or path.is_symlink()
            or not path.is_file()
            or path.resolve().parent != (build_root / "assets").resolve()
        ):
            return JSONResponse({"code": "NOT_FOUND"}, status_code=404)
        return FileResponse(path)

    app.include_router(
        terminal_router(settings, actual_probe, terminal_reads or UnconnectedTerminalReads())
    )

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
