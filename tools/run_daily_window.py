"""Bounded owner-side wrapper; task registration is a separate explicit approval."""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psutil
from local_db import LOCAL, ROOT

from auvexo_alpha.application.data_schedule import (
    SCHEDULE_DESCRIPTION,
    SCHEDULE_ID,
    target_window,
)

LOG_LIMIT = 1024 * 1024
DIRECTORY_LIMIT = 20 * LOG_LIMIT
LOG_NAME = re.compile(r"\d{8}T\d{12}Z-[0-9a-f]{12}(?:-warmup)?\.log")


def storage_budget(directory: Path, now: datetime) -> int:
    """Remove only old wrapper logs. Summaries and accepted data are never candidates."""
    if directory.is_symlink() or directory.is_junction():
        raise ValueError("UNSAFE_LOG_DIRECTORY")
    total = 0
    for path in directory.iterdir():
        if path.is_symlink() or path.is_junction() or not path.is_file():
            raise ValueError("UNEXPECTED_LOG_ENTRY")
        if LOG_NAME.fullmatch(path.name) and path.stat().st_mtime < now.timestamp() - 14 * 86400:
            path.unlink()
        else:
            total += path.stat().st_size
    if total + LOG_LIMIT + 16384 > DIRECTORY_LIMIT:
        raise ValueError("SCHEDULED_LOG_QUOTA")
    return total


def protect(directory: Path) -> None:
    if directory.exists():
        storage_budget(directory, datetime.now(UTC))
    directory.mkdir(exist_ok=True)
    if os.name == "nt":
        owner = subprocess.check_output(["whoami"], text=True).strip()
        subprocess.run(
            [
                "icacls",
                str(directory),
                "/inheritance:r",
                "/grant:r",
                f"{owner}:(OI)(CI)F",
                "SYSTEM:(OI)(CI)F",
            ],
            check=True,
            capture_output=True,
        )
    else:
        directory.chmod(0o700)


def stop_tree(process: psutil.Popen) -> None:
    try:
        children = process.children(recursive=True)
    except psutil.NoSuchProcess:
        process.wait(timeout=10)
        return
    for child in [*reversed(children), process]:
        try:
            child.kill()
        except psutil.NoSuchProcess:
            # Expected exit race; wait below confirms the owned parent has stopped.
            continue
    process.wait(timeout=10)


def run_bounded(arguments: list[str], log: Path, timeout: int) -> dict[str, object]:
    started = time.monotonic()
    stop = threading.Event()
    errors: list[str] = []
    with log.open("xb") as stream:
        process = psutil.Popen(
            [sys.executable, str(ROOT / "tools/data_local.py"), *arguments],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        assert process.stdout is not None

        def copy_output() -> None:
            written = 0
            try:
                while chunk := process.stdout.read(65536):
                    remaining = max(0, LOG_LIMIT - written)
                    stream.write(chunk[:remaining])
                    written += min(len(chunk), remaining)
                    if len(chunk) > remaining:
                        errors.append("LOG_LIMIT")
                        stop.set()
            except (OSError, ValueError):
                errors.append("LOG_IO_FAILED")
                stop.set()

        reader = threading.Thread(target=copy_output, daemon=True)
        reader.start()
        while process.poll() is None:
            if stop.wait(0.25) or time.monotonic() - started > timeout:
                if not errors:
                    errors.append("CHILD_DEADLINE")
                stop_tree(process)
                break
        reader.join(timeout=5)
        if reader.is_alive():
            errors.append("OUTPUT_NOT_CLOSED")
        process.stdout.close()
    return {
        "returncode": process.returncode,
        "seconds": round(time.monotonic() - started, 3),
        "errors": errors,
        "log": log.name,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--scheduled", action="store_true")
    args = parser.parse_args()
    if not args.preflight and not args.scheduled:
        print(
            json.dumps(
                {
                    "status": "DRY_RUN",
                    "registration_action": "NONE; inspect Task Scheduler separately",
                    "schedule": SCHEDULE_DESCRIPTION,
                    "schedule_id": SCHEDULE_ID,
                    "executable": sys.executable,
                    "working_directory": str(ROOT),
                    "arguments": "tools/run_daily_window.py --scheduled",
                }
            )
        )
        return 0
    now = datetime.now(UTC)
    target = target_window(now) if args.scheduled else None
    directory = LOCAL / "scheduled-data"
    protect(directory)
    run_id = now.strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:12]
    report: dict[str, object] = {
        "started_at": now.isoformat(),
        "schedule_id": SCHEDULE_ID,
        "mode": "scheduled" if target else "preflight",
    }
    if target:
        report["warmup"] = run_bounded(
            ["collect", "--enable-public-data", "--cycles", "2"],
            directory / (run_id + "-warmup.log"),
            150,
        )
        while datetime.now(UTC) < target:
            time.sleep(0.5)
        if datetime.now(UTC) - target > timedelta(seconds=15):
            report["status"] = "MISSED_START"
        else:
            storage_budget(directory, datetime.now(UTC))
            report["collection"] = run_bounded(
                ["collect", "--enable-public-data", "--cycles", "12"],
                directory / (run_id + ".log"),
                780,
            )
    else:
        report["collection"] = run_bounded(["verify"], directory / (run_id + ".log"), 90)
    result = report.get("collection")
    report["status"] = (
        "COMMAND_COMPLETE"
        if isinstance(result, dict) and result["returncode"] == 0 and not result["errors"]
        else report.get("status", "FAILED")
    )
    report["finished_at"] = datetime.now(UTC).isoformat()
    report["qualification"] = "NOT_INFERRED; use verified calendar qualification command"
    with (directory / (run_id + ".json")).open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report))
    return 0 if report["status"] == "COMMAND_COMPLETE" else 1


if __name__ == "__main__":
    try:
        code = main()
    except (OSError, ValueError, subprocess.SubprocessError, psutil.Error) as error:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "code": "WINDOW_WRAPPER_FAILED",
                    "reason": type(error).__name__,
                }
            )
        )
        code = 1
    raise SystemExit(code)
