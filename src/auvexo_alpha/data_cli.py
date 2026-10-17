"""Local data-only operator commands. Network collection is always explicit opt-in."""

import argparse
import json
import os
import signal
import subprocess
import time
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Event

from sqlalchemy import URL, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from auvexo_alpha.application.data_reporting import coverage_matrix, qualification
from auvexo_alpha.infrastructure.data_collection import Collector
from auvexo_alpha.infrastructure.data_store import DataStore
from auvexo_alpha.infrastructure.public_http import PublicHTTP


def main() -> int:
    parser = argparse.ArgumentParser(prog="auvexo-data")
    parser.add_argument(
        "command",
        choices=["history", "collect", "specs", "coverage", "verify", "qualification", "evidence"],
    )
    parser.add_argument("--enable-public-data", action="store_true")
    parser.add_argument("--symbol", choices=["BTCUSDT", "ETHUSDT"], default="BTCUSDT")
    parser.add_argument("--interval", choices=["1m", "1h"], default="1h")
    parser.add_argument("--period", action="append", default=[])
    parser.add_argument("--cycles", type=int, default=12)
    parser.add_argument("--start-day", type=date.fromisoformat)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.cycles <= 60 or len(args.period) > 12:
        parser.error("bounded invocation requires cycles 1..60 and at most 12 periods")
    if args.command in ("history", "collect", "specs") and not args.enable_public_data:
        print('{"code":"COLLECTOR_DISABLED","execution_enabled":false}')
        return 2
    if args.command == "history" and not args.period:
        parser.error("history requires explicit periods")
    if args.command == "qualification" and args.start_day is None:
        parser.error("qualification requires --start-day")
    password = os.environ.get("DATA_DB_PASSWORD", "")
    if len(password) < 32:
        print('{"code":"DATA_DATABASE_CONFIG_REQUIRED","execution_enabled":false}')
        return 2
    engine = create_engine(
        URL.create(
            "postgresql+psycopg",
            username="auvexo_data_writer",
            password=password,
            host="127.0.0.1",
            port=55432,
            database="auvexo_dev",
        ),
        pool_size=2,
        max_overflow=0,
        pool_timeout=3,
        hide_parameters=True,
        connect_args={
            "connect_timeout": 3,
            "options": "-c statement_timeout=60000 -c lock_timeout=3000",
        },
    )
    cancel = Event()
    signal.signal(signal.SIGINT, lambda signum, frame: cancel.set())
    try:
        store = DataStore(engine, Path(".local/market"), Path.cwd())
        revision = subprocess.check_output(
            ["git", "-c", f"safe.directory={Path.cwd().as_posix()}", "rev-parse", "HEAD"], text=True
        ).strip()
        if subprocess.check_output(
            ["git", "-c", f"safe.directory={Path.cwd().as_posix()}", "status", "--porcelain"],
            text=True,
        ).strip():
            revision += "-dirty"
        collector = Collector(store, PublicHTTP(cancel), revision, args.enable_public_data)
        with engine.connect() as lease:
            if not lease.scalar(text("SELECT pg_try_advisory_lock(20801403)")):
                raise ValueError("COLLECTOR_ALREADY_RUNNING")
            result: object
            try:
                if args.command == "history":
                    result = [
                        collector.history(args.symbol, args.interval, p).model_dump(mode="json")
                        for p in args.period
                    ]
                elif args.command == "collect":
                    started = time.monotonic()
                    for cycle in range(args.cycles):
                        for symbol in ("BTCUSDT", "ETHUSDT"):
                            if cancel.is_set():
                                break
                            collector.poll(symbol)
                        delay = max(0.0, started + (cycle + 1) * 60 - time.monotonic())
                        if cycle < args.cycles - 1 and cancel.wait(delay):
                            break
                    collector.record(
                        "public.collector",
                        "STOPPED",
                        "CANCELLED" if cancel.is_set() else "BUDGET_COMPLETE",
                        datetime.now(UTC),
                    )
                    result = {
                        "status": "STOPPED",
                        "requests": collector.http.requests,
                        "bytes": collector.http.bytes,
                    }
                elif args.command == "specs":
                    result = [
                        collector.spec(symbol).model_dump(mode="json")
                        for symbol in ("BTCUSDT", "ETHUSDT")
                    ]
                elif args.command == "coverage":
                    result = coverage_matrix(store.manifests())
                elif args.command == "verify":
                    result = store.reconcile()
                elif args.command == "evidence":
                    result = {
                        "manifests": [m.model_dump(mode="json") for m in store.manifests()],
                        "events": [e.model_dump(mode="json") for e in store.events()],
                    }
                else:
                    result = qualification(store.events(), args.start_day, datetime.now(UTC))
            finally:
                lease.execute(text("SELECT pg_advisory_unlock(20801403)"))
        rendered = json.dumps(result, indent=2) + "\n"
        if args.output:
            # Never overwrite a receipt; each invocation must choose its own evidence name.
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(rendered)
        print(rendered)
        return 0
    except (ValueError, OSError, SQLAlchemyError):
        print(
            json.dumps(
                dict(
                    code="DATA_OPERATION_FAILED",
                    execution_enabled=False,
                    detail="inspect durable data events; no success inferred",
                )
            )
        )
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
