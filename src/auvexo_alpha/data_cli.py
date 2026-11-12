"""Local data-only operator commands. Network collection is always explicit opt-in."""

import argparse
import json
import os
import re
import signal
import subprocess
import time
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Event

from sqlalchemy import URL, Engine, create_engine, text
from sqlalchemy.exc import (
    DisconnectionError,
    InterfaceError,
    OperationalError,
    SQLAlchemyError,
)
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from auvexo_alpha.application.data_reporting import (
    ScheduledSummary,
    coverage_matrix,
    qualification,
    stable_code,
)
from auvexo_alpha.application.data_schedule import CATCHUP_BUDGET, catchup_permitted
from auvexo_alpha.infrastructure.data_collection import Collector
from auvexo_alpha.infrastructure.data_store import DataStore
from auvexo_alpha.infrastructure.public_http import PublicHTTP

READ_ONLY = ("coverage", "verify", "qualification", "evidence")
SUMMARY_DIRECTORY = Path(".local/scheduled-data")
# The wrapper names each receipt after its own start instant; anything else is unrelated.
SUMMARY_NAME = re.compile(r"(\d{8}T\d{12}Z)-[0-9a-f]{12}\.json")
MAX_SUMMARIES = 4096
MAX_SUMMARY_BYTES = 65536


def failure_reason(error: ValueError | OSError | SQLAlchemyError) -> str:
    """Stable non-secret classification; exception text, paths, SQL and DSNs stay private."""
    if isinstance(error, SQLAlchemyError):
        unavailable = (OperationalError, InterfaceError, DisconnectionError, PoolTimeoutError)
        return "DATABASE_UNAVAILABLE" if isinstance(error, unavailable) else "DATABASE_ERROR"
    if isinstance(error, OSError):
        return "OS_ERROR"
    return stable_code(str(error)) or "UNCLASSIFIED"


def read_summary(path: Path, stamp: str) -> ScheduledSummary | None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SUMMARY_BYTES:
        return None
    try:
        payload: object = json.loads(path.read_bytes())
    except (ValueError, RecursionError):
        # A damaged receipt is counted as rejected by the caller and can satisfy no day.
        return None
    if not isinstance(payload, dict):
        return None
    fields = [payload.get(key) for key in ("started_at", "schedule_id", "mode", "status")]
    texts = [value for value in fields if isinstance(value, str) and len(value) <= 64]
    if len(texts) != len(fields):
        return None
    started_at, schedule_id, mode, status = texts
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return None
    # The receipt must agree with the start instant in its own exclusive file name.
    if started.utcoffset() is None or started.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ") != stamp:
        return None
    return ScheduledSummary(started.astimezone(UTC), schedule_id, mode, status)


def scheduled_summaries(directory: Path) -> tuple[list[ScheduledSummary], int]:
    """Bounded read-only parse of wrapper receipts; unrelated files are left alone."""
    if not directory.exists():
        return [], 0
    if directory.is_symlink() or directory.is_junction() or not directory.is_dir():
        raise ValueError("UNSAFE_LOG_DIRECTORY")
    named = sorted(
        (path, name[1])
        for path in directory.iterdir()
        if (name := SUMMARY_NAME.fullmatch(path.name))
    )
    if len(named) > MAX_SUMMARIES:
        raise ValueError("REPORT_BUDGET_EXCEEDED")
    parsed = [read_summary(path, stamp) for path, stamp in named]
    accepted = [summary for summary in parsed if summary is not None]
    return accepted, len(parsed) - len(accepted)


def report(args: argparse.Namespace, store: DataStore) -> object:
    """Read-only commands never take the collector lease, so they cannot block a run."""
    if args.command == "coverage":
        return coverage_matrix(store.manifests())
    if args.command == "verify":
        return store.reconcile()
    if args.command == "evidence":
        return {
            "manifests": [m.model_dump(mode="json") for m in store.manifests()],
            "events": [e.model_dump(mode="json") for e in store.events()],
        }
    summaries, rejected = scheduled_summaries(SUMMARY_DIRECTORY)
    return qualification(
        store.events(), args.start_day, datetime.now(UTC), store.verified_manifests(), summaries
    ) | {"scheduled_summary_files": {"accepted": len(summaries), "rejected": rejected}}


def collect(collector: Collector, cancel: Event, cycles: int, catchup: bool) -> dict[str, object]:
    started = time.monotonic()
    result: dict[str, object] = {"status": "STOPPED"}
    if catchup:

        def stop() -> str | None:
            if cancel.is_set():
                return "CANCELLED"
            if time.monotonic() - started >= CATCHUP_BUDGET.total_seconds():
                return "DEADLINE"
            return None if catchup_permitted(datetime.now(UTC)) else "WINDOW_GUARD"

        result["catchup"] = {
            symbol: collector.catch_up(symbol, stop) for symbol in ("BTCUSDT", "ETHUSDT")
        }
    for cycle in range(cycles):
        for symbol in ("BTCUSDT", "ETHUSDT"):
            if cancel.is_set():
                break
            collector.poll(symbol)
        delay = max(0.0, started + (cycle + 1) * 60 - time.monotonic())
        if cycle < cycles - 1 and cancel.wait(delay):
            break
    collector.record(
        "public.collector",
        "STOPPED",
        "CANCELLED" if cancel.is_set() else "BUDGET_COMPLETE",
        datetime.now(UTC),
    )
    return result | {"requests": collector.http.requests, "bytes": collector.http.bytes}


def write(args: argparse.Namespace, store: DataStore, engine: Engine, cancel: Event) -> object:
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
        try:
            if args.command == "history":
                return [
                    collector.history(args.symbol, args.interval, p).model_dump(mode="json")
                    for p in args.period
                ]
            if args.command == "specs":
                return [
                    collector.spec(symbol).model_dump(mode="json")
                    for symbol in ("BTCUSDT", "ETHUSDT")
                ]
            return collect(collector, cancel, args.cycles, args.catchup)
        finally:
            lease.execute(text("SELECT pg_advisory_unlock(20801403)"))


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
    parser.add_argument("--catchup", action="store_true")
    parser.add_argument("--start-day", type=date.fromisoformat)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.cycles <= 60 or len(args.period) > 12:
        parser.error("bounded invocation requires cycles 1..60 and at most 12 periods")
    if args.catchup and args.command != "collect":
        parser.error("--catchup is the warm-up backlog mode of collect only")
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
        result = (
            report(args, store) if args.command in READ_ONLY else write(args, store, engine, cancel)
        )
        rendered = json.dumps(result, indent=2) + "\n"
        if args.output:
            # Never overwrite a receipt; each invocation must choose its own evidence name.
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(rendered)
        print(rendered)
        return 0
    except (ValueError, OSError, SQLAlchemyError) as error:
        print(
            json.dumps(
                dict(
                    code="DATA_OPERATION_FAILED",
                    execution_enabled=False,
                    reason=failure_reason(error),
                    detail="inspect durable data events; no success inferred",
                )
            )
        )
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
