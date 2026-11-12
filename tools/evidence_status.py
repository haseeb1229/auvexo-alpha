"""Read-only evidence-health report for a checkout. Never writes, never opens a database.

Reads only: scheduled public-data wrapper summaries, the PostgreSQL pid file and log
directory timestamps, and the Git head reference. It starts nothing and repairs nothing.
A summary proves what the wrapper did, not that a date qualified.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import psutil

from auvexo_alpha.application.data_schedule import (
    FIRST_SCHEDULED_DAY,
    SCHEDULE_DESCRIPTION,
    SCHEDULE_ID,
    qualification_window,
)
from auvexo_alpha.application.evidence_status import classify_nights, summarize

MAX_SUMMARIES = 4096
MAX_SUMMARY_BYTES = 65536


def read_summaries(directory: Path) -> tuple[list[dict[str, object]], int]:
    """Bounded, tolerant read. Unparseable files are counted, never fatal, never altered."""
    summaries: list[dict[str, object]] = []
    skipped = 0
    if not directory.is_dir() or directory.is_symlink() or directory.is_junction():
        return summaries, skipped
    names = sorted(p for p in directory.iterdir() if p.suffix == ".json")[:MAX_SUMMARIES]
    for path in names:
        try:
            if path.is_symlink() or path.stat().st_size > MAX_SUMMARY_BYTES:
                skipped += 1
                continue
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            skipped += 1
            continue
        if isinstance(value, dict):
            summaries.append(value)
        else:
            skipped += 1
    return summaries, skipped


def cluster_state(root: Path) -> dict[str, object]:
    """Process and file facts only; no connection is attempted."""
    data = root / ".local/postgres-data"
    state: dict[str, object] = {"data_directory_present": (data / "PG_VERSION").is_file()}
    running = False
    pid_file = data / "postmaster.pid"
    if pid_file.is_file():
        try:
            pid = int(pid_file.read_text(encoding="ascii", errors="replace").split("\n", 1)[0])
            running = psutil.pid_exists(pid) and psutil.Process(pid).name().lower().startswith(
                "postgres"
            )
        except (OSError, ValueError, psutil.Error):
            running = False
        state["pid_file"] = "LIVE" if running else "STALE"
    else:
        state["pid_file"] = "ABSENT"
    state["process"] = "RUNNING" if running else "NOT_RUNNING"
    latest: float | None = None
    logs = data / "log"
    if logs.is_dir():
        try:
            latest = max((p.stat().st_mtime for p in logs.iterdir() if p.is_file()), default=None)
        except OSError:
            latest = None
    state["last_log_write"] = (
        datetime.fromtimestamp(latest, UTC).isoformat(timespec="seconds") if latest else None
    )
    return state


def head_commit(root: Path) -> str | None:
    """Resolve HEAD from files; running Git could refresh the index of a pinned checkout."""
    git = root / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="ascii").strip()
        if head.startswith("ref: "):
            head = (git / head[5:]).read_text(encoding="ascii").strip()
    except OSError:
        return None
    return head if len(head) == 40 and all(c in "0123456789abcdef" for c in head) else None


def report(root: Path, now: datetime) -> dict[str, object]:
    # A night is reportable once its window has closed.
    today = now.date()
    _, closes = qualification_window(today)
    last_day = today if now >= closes else today - timedelta(days=1)
    summaries, skipped = read_summaries(root / ".local/scheduled-data")
    nights, unreadable = classify_nights(summaries, last_day=last_day)
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "read_only": True,
        "checkout_head": head_commit(root),
        "phase2_public_data": {
            "schedule_id": SCHEDULE_ID,
            "schedule": SCHEDULE_DESCRIPTION,
            "first_eligible_day": FIRST_SCHEDULED_DAY.isoformat(),
            "last_closed_day": last_day.isoformat(),
            "summary": summarize(nights),
            "unreadable_summaries": skipped + unreadable,
            "nights": [
                {
                    "day": night.day.isoformat(),
                    "state": night.state,
                    "started_at": night.started_at.isoformat(timespec="seconds")
                    if night.started_at
                    else None,
                    "reason": night.reason,
                }
                for night in nights
            ],
        },
        "phase4_paper_observation": {
            "qualified_dates": "UNKNOWN",
            "why": "receipts exist only in the database; this tool never opens one",
        },
        "postgresql_cluster": cluster_state(root),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="checkout to inspect")
    parser.add_argument("--as-of", type=date.fromisoformat, help="UTC day to report up to")
    args = parser.parse_args(argv)
    root: Path = args.root
    if not (root / ".git").exists() or not (root / "tools/run_daily_window.py").is_file():
        print(json.dumps({"code": "NOT_AN_AUVEXO_CHECKOUT", "read_only": True}))
        return 2
    now = datetime.now(UTC)
    if args.as_of is not None:
        now = datetime.combine(args.as_of, datetime.max.time(), UTC)
    print(json.dumps(report(root, now), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
