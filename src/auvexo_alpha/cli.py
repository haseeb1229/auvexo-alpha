"""Small diagnostics CLI, with no arbitrary configuration or execution actions."""

import argparse
import json

from pydantic import ValidationError

from auvexo_alpha import __version__
from auvexo_alpha.config import load_settings


def main() -> int:
    parser = argparse.ArgumentParser(prog="auvexo")
    parser.add_argument(
        "command", choices=["doctor", "health", "validate-config", "serve", "version"]
    )
    args = parser.parse_args()
    if args.command == "version":
        print(__version__)
        return 0
    try:
        settings = load_settings()
    except (ValidationError, ValueError):
        print(json.dumps({"code": "INVALID_CONFIG", "execution_enabled": False}))
        return 2
    if args.command == "serve":
        import uvicorn

        from auvexo_alpha.api.app import create_app

        print(
            json.dumps(
                {
                    "event": "diagnostics_start",
                    "mode": settings.mode.value,
                    "execution_enabled": False,
                }
            ),
            flush=True,
        )
        uvicorn.run(
            create_app(settings),
            host=settings.bind_host,
            port=settings.port,
            proxy_headers=False,
            access_log=False,
            log_level="warning",
        )
        return 0
    if args.command == "validate-config":
        print(
            json.dumps({"status": "VALID", "mode": settings.mode.value, "execution_enabled": False})
        )
        return 0
    from auvexo_alpha.infrastructure.database import DatabaseProbe, make_engine

    engine = make_engine(settings)
    try:
        ready = DatabaseProbe(engine).ready()
    finally:
        engine.dispose()
    print(
        json.dumps(
            {
                "status": "READY" if ready else "NOT_READY",
                "execution_enabled": False,
                "scope": "foundation_only",
                "version": __version__,
            }
        )
    )
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
