"""Measure only the local Phase 1 API and owned PostgreSQL cluster; no trading load claim."""

import json
import os
import platform
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import psutil
from local_db import DATA, LOCAL, ROOT, app_env, credentials


def main() -> None:
    token = credentials()["token"]
    env = app_env()
    env["AUVEXO_PORT"] = "18765"
    log = LOCAL / "measurement-api.log"
    with socket.socket() as check:
        check.bind(("127.0.0.1", 18765))
    started = time.monotonic()
    with log.open("wb") as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "auvexo_alpha.cli", "serve"],
            env=env,
            cwd=ROOT,
            stdout=output,
            stderr=output,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            url = "http://127.0.0.1:18765/api/v1/ready"
            ready = False
            while time.monotonic() - started < 30:
                if process.poll() is not None:
                    raise RuntimeError("API exited before readiness; inspect local sanitized log")
                try:
                    with urlopen(
                        Request(url, headers={"Authorization": f"Bearer {token}"}), timeout=2
                    ) as response:
                        ready = json.load(response)["status"] == "READY"
                except (URLError, TimeoutError):
                    pass  # Startup polling is bounded to 30 seconds and fails below.
                if ready:
                    break
                time.sleep(0.1)
            assert ready, "Actual DB readiness failed"
            startup = time.monotonic() - started
            try:
                urlopen(url, timeout=2)
            except HTTPError as error:
                assert error.code == 401
            else:
                raise AssertionError("Unauthenticated real HTTP request accepted")
            pg_pid = int((DATA / "postmaster.pid").read_text().splitlines()[0])
            groups = {
                "api": [
                    psutil.Process(process.pid),
                    *psutil.Process(process.pid).children(recursive=True),
                ],
                "postgres": [
                    psutil.Process(pg_pid),
                    *psutil.Process(pg_pid).children(recursive=True),
                ],
            }
            for processes in groups.values():
                for item in processes:
                    item.cpu_percent()
            sample_start = time.monotonic()
            time.sleep(5)
            resources = {
                name: dict(
                    process_count=len(processes),
                    rss_mib=round(sum(p.memory_info().rss for p in processes) / 2**20, 2),
                    cpu_percent_one_core=round(sum(p.cpu_percent() for p in processes), 2),
                )
                for name, processes in groups.items()
            }
            sample_seconds = time.monotonic() - sample_start
            disks = {}
            for name in (
                ".venv",
                ".local/python",
                ".local/toolchains",
                ".local/uv-cache",
                ".local/postgres-data",
            ):
                disks[name] = round(
                    sum(p.stat().st_size for p in (ROOT / name).rglob("*") if p.is_file()) / 2**20,
                    2,
                )
            report = dict(
                status="PASS",
                platform=platform.platform(),
                python=platform.python_version(),
                logical_cpus=psutil.cpu_count(),
                machine_ram_gib=round(psutil.virtual_memory().total / 2**30, 2),
                free_disk_gib=round(psutil.disk_usage(str(ROOT)).free / 2**30, 2),
                api_start_to_db_ready_seconds=round(startup, 3),
                idle_sample_seconds=round(sample_seconds, 2),
                resources=resources,
                disk_mib=disks,
                real_http_missing_auth=401,
                scope="idle foundation only; RSS may double-count shared pages",
            )
        finally:
            children = psutil.Process(process.pid).children(recursive=True)
            for child in children:
                child.terminate()
            psutil.wait_procs(children, timeout=10)
            process.terminate()
            process.wait(timeout=10)
    assert token not in log.read_text()
    (LOCAL / "resource-evidence.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
