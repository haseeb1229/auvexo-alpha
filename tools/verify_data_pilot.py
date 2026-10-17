"""Explicit real-source, bounded pilot and native process-tree resource receipt."""

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime

import psutil
from local_db import LOCAL, ROOT


def main():
    directory = LOCAL / ("data-pilot-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    directory.mkdir()
    # Two boundary days, plus ordinary/stress/calendar diversity at compact hourly resolution.
    jobs = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        jobs.append(
            [
                "history",
                "--enable-public-data",
                "--symbol",
                symbol,
                "--interval",
                "1h",
                "--period",
                "2024-12-31",
                "--period",
                "2025-01-01",
                "--period",
                "2020-03",
                "--period",
                "2022-11",
                "--period",
                "2024-06",
                "--period",
                "2026-09",
            ]
        )
    jobs += [
        ["specs", "--enable-public-data"],
        ["collect", "--enable-public-data", "--cycles", "2"],
        ["coverage"],
        ["verify"],
        ["evidence"],
        ["qualification", "--start-day", "2026-10-17"],
    ]
    receipts = []
    for index, arguments in enumerate(jobs):
        output = directory / f"{index:02d}-{arguments[0]}.json"
        log = directory / f"{index:02d}.log"
        started = time.monotonic()
        peak = cpu = races = 0
        tree = []
        with log.open("w") as stream:
            process = subprocess.Popen(
                [sys.executable, "tools/data_local.py", *arguments, "--output", str(output)],
                cwd=ROOT,
                stdout=stream,
                stderr=stream,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            while process.poll() is None:
                try:
                    parent = psutil.Process(process.pid)
                    tree = [parent, *parent.children(recursive=True)]
                    peak = max(peak, sum(p.memory_info().rss for p in tree))
                    cpu = max(cpu, sum(p.cpu_times().user + p.cpu_times().system for p in tree))
                except psutil.NoSuchProcess:
                    # A child may exit between enumeration and read; count sample races.
                    races += 1
                if time.monotonic() - started > 600:
                    for child in tree[::-1]:
                        if child.is_running():
                            child.terminate()
                    raise RuntimeError("pilot per-job deadline exceeded")
                time.sleep(0.25)
        receipts.append(
            dict(
                command=arguments,
                status="PASS" if process.returncode == 0 else "BLOCKED_OR_FAILED",
                exit_code=process.returncode,
                seconds=round(time.monotonic() - started, 3),
                peak_tree_rss_bytes=peak,
                cpu_seconds=cpu,
                sampling_races=races,
                evidence=str(output.relative_to(ROOT)) if output.exists() else None,
                log=str(log.relative_to(ROOT)),
            )
        )
        print(json.dumps(receipts[-1]), flush=True)
    report = dict(
        observed_at=datetime.now(UTC).isoformat(),
        receipts=receipts,
        mandatory_spend_usd=0,
        environment=dict(
            platform=sys.platform,
            python=sys.version.split()[0],
            total_ram=psutil.virtual_memory().total,
            free_disk=psutil.disk_usage(str(ROOT)).free,
        ),
    )
    (LOCAL / "data-pilot-evidence.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Pilot receipt: .local/data-pilot-evidence.json")


if __name__ == "__main__":
    main()
