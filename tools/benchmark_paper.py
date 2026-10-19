"""One-shot three-instrument SYNTHETIC PAPER load; no observation day or alpha claim."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import queue
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psutil
from paper_local import LOCAL, ROOT, engine_for, isolated_database, require_migration, safe_window
from sqlalchemy import text

sys.path.insert(0, str(ROOT / "tests"))
from paper_fixtures import fixture_bundle  # noqa: E402

from auvexo_alpha.domain.paper_risk import assess_paper  # noqa: E402
from auvexo_alpha.infrastructure.paper_store import PaperStore  # noqa: E402

INSTRUMENTS = ("paper.spot.BTCUSD", "paper.spot.ETHUSD", "paper.spot.SYNTHUSD")


def percentiles(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    return {
        "samples": len(values),
        **{
            "p" + str(p) + "_ms": round(ordered[max(0, math.ceil(len(ordered) * p / 100) - 1)], 4)
            for p in (50, 95, 99)
        },
        "max_ms": round(max(ordered), 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kernel-samples", type=int, default=1000)
    parser.add_argument("--transaction-samples", type=int, default=120)
    args = parser.parse_args()
    if not 100 <= args.kernel_samples <= 100_000 or not 30 <= args.transaction_samples <= 3000:
        parser.error("Require 100..100000 kernel and 30..3000 bounded transaction samples")
    safe_window()
    began = time.monotonic()
    process = psutil.Process()
    cpu_start = process.cpu_times()
    io_start = process.io_counters()
    peak_rss = process.memory_info().rss
    cpu_samples: list[float] = []
    stop = threading.Event()
    throttled = threading.Event()
    research_iterations = [0, 0]
    pg_resources = dict(peak_rss_bytes=0, cpu_seconds_observed=0.0, inaccessible_processes=0)
    pg_cpu_first: dict[int, float] = {}
    pg_cpu_last: dict[int, float] = {}

    def monitor() -> None:
        nonlocal peak_rss
        while not stop.wait(0.05):
            peak_rss = max(peak_rss, process.memory_info().rss)
            rss = 0
            for candidate in psutil.process_iter(["name"]):
                if (candidate.info["name"] or "").lower() not in ("postgres", "postgres.exe"):
                    continue
                try:
                    rss += candidate.memory_info().rss
                    times = candidate.cpu_times()
                    cpu = times.user + times.system
                    pg_cpu_first.setdefault(candidate.pid, cpu)
                    pg_cpu_last[candidate.pid] = cpu
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pg_resources["inaccessible_processes"] += 1
            pg_resources["peak_rss_bytes"] = max(pg_resources["peak_rss_bytes"], rss)
            pg_resources["cpu_seconds_observed"] = round(
                sum(value - pg_cpu_first[pid] for pid, value in pg_cpu_last.items()), 4
            )

    def research_worker() -> None:
        # A bounded synthetic CPU worker. No archived/private/OOS inputs are read.
        payload = b"SYNTHETIC_RESEARCH_RESOURCE_COMPETITOR" * 4096
        while not stop.is_set():
            hashlib.sha256(payload).digest()
            index = int(throttled.is_set())
            research_iterations[index] += 1
            if index:
                stop.wait(0.003)

    competitor = threading.Thread(target=research_worker, daemon=True)
    observer = threading.Thread(target=monitor, daemon=True)
    competitor.start()
    observer.start()
    phases = {}
    try:
        with isolated_database() as database:
            require_migration(database)
            runtime = engine_for(database, "auvexo_paper")
            owner = engine_for(database, "auvexo_paper_owner")
            store = PaperStore(runtime, owner_engine=owner)
            with runtime.connect() as conn:
                postgres_version = conn.execute(text("SHOW server_version")).scalar_one()

            def transaction_job(index: int) -> tuple[float, str]:
                b = fixture_bundle(
                    instrument_id=INSTRUMENTS[index % 3],
                    account_ref="paper.benchmark." + uuid4().hex,
                )
                store.initialize(b.account, b.policy, b.release, now=b.now)
                store.acquire_writer(b.account.account_ref, now=b.now)
                assert store.reconcile(b.account.account_ref, now=b.now)
                store.resume(b.account.account_ref, actor="owner.fixture", now=b.now)
                b.account = store.account(b.account.account_ref)
                intent = b.rebind()
                start = time.perf_counter_ns()
                approved = store.authorize(intent, b.policy, b.market, b.spec, b.release, now=b.now)
                elapsed = (time.perf_counter_ns() - start) / 1_000_000
                assert approved.decision.status == "APPROVED"
                return elapsed, intent.content_hash()

            try:
                for phase in ("research_concurrent", "research_throttled"):
                    if phase == "research_throttled":
                        throttled.set()
                    fixtures = [fixture_bundle(instrument_id=i) for i in INSTRUMENTS]
                    kernel_times = []
                    for index in range(args.kernel_samples):
                        b = fixtures[index % 3]
                        start = time.perf_counter_ns()
                        result = assess_paper(
                            b.intent, b.policy, b.market, b.spec, b.account, b.release, now=b.now
                        )
                        kernel_times.append((time.perf_counter_ns() - start) / 1_000_000)
                        assert result.status == "APPROVED"
                        peak_rss = max(peak_rss, process.memory_info().rss)
                        if index % 100 == 0:
                            cpu_samples.append(psutil.cpu_percent())
                    transaction_times = []
                    query_times = []
                    for index in range(args.transaction_samples):
                        # Independent virtual accounts bound accumulated exposure and rate.
                        elapsed, intent_hash = transaction_job(index)
                        transaction_times.append(elapsed)
                        for _ in range(3):
                            start = time.perf_counter_ns()
                            with runtime.connect() as conn:
                                assert (
                                    conn.execute(
                                        text(
                                            "SELECT state FROM paper_outbox WHERE intent_hash=:hash"
                                        ),
                                        {"hash": intent_hash},
                                    ).scalar_one()
                                    == "RESERVED"
                                )
                            query_times.append((time.perf_counter_ns() - start) / 1_000_000)
                    # Backpressure is measured at a fixed bounded admission queue. Submitted
                    # jobs cannot allocate an unbounded backlog, including a 5x producer burst.
                    admissions = {}
                    depth = min(32, fixtures[0].policy.max_queue_depth)
                    for label, offered in (("baseline", depth), ("5x_burst", depth * 5)):
                        jobs: queue.Queue[int] = queue.Queue(maxsize=depth)
                        rejected = 0
                        for index in range(offered):
                            try:
                                jobs.put_nowait(index)
                            except queue.Full:
                                rejected += 1
                        accepted = jobs.qsize()
                        assert accepted <= depth and accepted + rejected == offered

                        def admitted_job(_: int, admitted_queue: queue.Queue[int] = jobs) -> float:
                            index = admitted_queue.get_nowait()
                            elapsed, _ = transaction_job(index)
                            admitted_queue.task_done()
                            return elapsed

                        burst_start = time.monotonic()
                        with ThreadPoolExecutor(max_workers=2) as pool:
                            burst_times = list(pool.map(admitted_job, range(accepted)))
                        admissions[label] = dict(
                            offered=offered,
                            admitted=accepted,
                            backpressured=rejected,
                            queue_bound=depth,
                            peak_depth=accepted,
                            drained=jobs.empty(),
                            concurrent_workers=2,
                            actual_reservation_transactions=percentiles(burst_times),
                            wave_elapsed_seconds=round(time.monotonic() - burst_start, 4),
                        )
                    kernel = percentiles(kernel_times)
                    transactions = percentiles(transaction_times)
                    queries = percentiles(query_times)
                    phases[phase] = dict(
                        kernel=kernel,
                        reservation_transaction=transactions,
                        indexed_query=queries,
                        backpressure=admissions,
                        targets_met=dict(
                            kernel_p95=kernel["p95_ms"] <= 10,
                            kernel_p99=kernel["p99_ms"] <= 25,
                            transaction_max=transactions["max_ms"] <= 100,
                            query_p95=queries["p95_ms"] <= 50,
                            query_p99=queries["p99_ms"] <= 200,
                        ),
                        fixture_hashes=[
                            dict(
                                policy=b.policy.content_hash(),
                                policy_version=b.policy.version,
                                spec=b.spec.content_hash(),
                                market=b.market.content_hash(),
                                release=b.release.content_hash(),
                                instrument=b.spec.instrument_id,
                            )
                            for b in fixtures
                        ],
                    )
                with runtime.connect() as conn:
                    database_bytes = conn.execute(
                        text("SELECT pg_database_size(current_database())")
                    ).scalar_one()
            finally:
                runtime.dispose()
                owner.dispose()
    finally:
        stop.set()
        competitor.join(timeout=5)
        observer.join(timeout=5)
    cpu_end = process.cpu_times()
    io_end = process.io_counters()
    report = dict(
        evidence_kind="SYNTHETIC_ENGINEERING_ONLY",
        benchmark_version="paper.synthetic.three_instrument.v1",
        load_policy=dict(queue_depth=32, burst_multiple=5, database_workers=2),
        instruments=list(INSTRUMENTS),
        persistent_task=False,
        observation_days=0,
        phases=phases,
        resources=dict(
            peak_python_rss_bytes=peak_rss,
            python_cpu_seconds=round(
                cpu_end.user + cpu_end.system - cpu_start.user - cpu_start.system, 4
            ),
            sampled_host_cpu_percent=cpu_samples,
            process_read_bytes=io_end.read_bytes - io_start.read_bytes,
            process_write_bytes=io_end.write_bytes - io_start.write_bytes,
            free_disk_bytes=psutil.disk_usage(str(ROOT)).free,
            research_iterations_concurrent=research_iterations[0],
            research_iterations_throttled=research_iterations[1],
            throttle_wait_seconds=0.003,
            postgres_all_local_processes=pg_resources,
            isolated_database_bytes=database_bytes,
        ),
        environment=dict(
            os=platform.system(),
            os_release=platform.release(),
            python=platform.python_version(),
            postgres=postgres_version,
            logical_cpus=psutil.cpu_count(),
            physical_ram_bytes=psutil.virtual_memory().total,
        ),
        elapsed_seconds=round(time.monotonic() - began, 3),
        limitation="Isolated synthetic Windows engineering load; no feed/alpha/HFT evidence",
    )
    LOCAL.mkdir(exist_ok=True)
    (LOCAL / "paper-benchmark-evidence.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
