"""Synthetic two-year 1m scale benchmark, outside ingestion and research registries."""

import json
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psutil

from auvexo_alpha.application.research_simulator import FittedFeatures, simulate
from auvexo_alpha.application.research_study import frozen_configs
from auvexo_alpha.domain.market_data import Candle
from auvexo_alpha.domain.research import CostModel, PriceAvailability
from auvexo_alpha.infrastructure.data_store import file_hash, parquet_bytes, pressure, read_bars


def main():
    import polars as pl

    root = Path(".local") / ("synthetic-research-scale-" + uuid4().hex[:12])
    root.mkdir()
    begin = datetime(2020, 1, 1, tzinfo=UTC)
    end = datetime(2022, 1, 1, tzinfo=UTC)
    count = int((end - begin).total_seconds() / 60)
    received = datetime(2026, 10, 17, tzinfo=UTC)
    base = Candle.model_validate(
        dict(
            instrument_id="binance.spot.BTCUSDT",
            symbol="BTCUSDT",
            interval="1m",
            base_currency="BTC",
            open_at=begin,
            end_at=begin + timedelta(minutes=1),
            open="100",
            high="101",
            low="99",
            close="100",
            volume="1",
            quote_volume="100",
            trades=1,
            source=dict(
                source_id="DS-02",
                source_url="https://synthetic.invalid/NOT_PROVIDER",
                source_hash="0" * 64,
                raw_open=int(begin.timestamp() * 1000),
                raw_close=int(begin.timestamp() * 1000) + 59999,
                timestamp_unit="MILLISECOND",
                received_at=received,
            ),
            availability=dict(
                received_at=received,
                processed_at=received,
                available_at=received,
                historical_close_bound=begin + timedelta(minutes=1),
                basis="OBSERVED_RECEIPT",
            ),
        )
    )
    process = psutil.Process()
    peak = [process.memory_info().rss]
    stop = threading.Event()

    def monitor():
        while not stop.wait(0.05):
            peak[0] = max(peak[0], process.memory_info().rss)

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    start = time.monotonic()
    cpu_start = process.cpu_times()
    try:
        files = []
        for offset in range(0, count, 25000):
            if process.memory_info().rss > 2_000_000_000:
                raise RuntimeError("BENCHMARK_RAM_LIMIT")
            bars = []
            for i in range(offset, min(offset + 25000, count)):
                opened = begin + timedelta(minutes=i)
                bars.append(
                    base.model_copy(
                        update={
                            "open_at": opened,
                            "end_at": opened + timedelta(minutes=1),
                            "source": base.source.model_copy(
                                update={
                                    "raw_open": int(opened.timestamp() * 1000),
                                    "raw_close": int(opened.timestamp() * 1000) + 59999,
                                }
                            ),
                            "availability": base.availability.model_copy(
                                update={"historical_close_bound": opened + timedelta(minutes=1)}
                            ),
                        }
                    )
                )
            path = root / f"{offset:08d}.parquet"
            path.write_bytes(parquet_bytes(bars))
            files.append(path)
            del bars
        generated = time.monotonic() - start
        scan = pl.scan_parquet(str(root / "*.parquet"))
        started = time.monotonic()
        rows = scan.select(pl.len()).collect().item()
        scan_seconds = time.monotonic() - started
        assert rows == count
        started = time.monotonic()
        filtered = (
            scan.filter(pl.col("open_at") < begin + timedelta(days=7)).select("record").collect()
        )
        subset = [Candle.model_validate_json(r) for r in filtered.get_column("record")]
        filtered_seconds = time.monotonic() - started
        assert len(subset) == 10080
        started = time.monotonic()
        loaded = 0
        for path in files:
            batch = read_bars(path)
            loaded += len(batch)
            del batch
        canonical_replay_seconds = time.monotonic() - started
        assert loaded == count
        started = time.monotonic()
        result = simulate(
            subset,
            frozen_configs()[1],
            PriceAvailability(lag_microseconds=1000000),
            CostModel(),
            FittedFeatures(begin - timedelta(days=365), begin, base.close / 100),
        )
        event_seconds = time.monotonic() - started
        assert result.label == "SIMULATED"
        cpu_end = process.cpu_times()
        report = dict(
            status="PASS",
            classification="SYNTHETIC_PERFORMANCE_ONLY_NEVER_PROVIDER_QUALIFICATION",
            calendar_start=begin.isoformat(),
            calendar_end=end.isoformat(),
            rows=count,
            files=len(files),
            schema={k: str(v) for k, v in scan.collect_schema().items()},
            generation_and_parquet_seconds=generated,
            pruned_count_scan_seconds=scan_seconds,
            one_week_filter_load_seconds=filtered_seconds,
            canonical_validation_seconds=canonical_replay_seconds,
            canonical_rows_per_second=count / canonical_replay_seconds,
            event_replay_sample_rows=len(subset),
            event_replay_seconds=event_seconds,
            event_rows_per_second=len(subset) / event_seconds,
            peak_rss_bytes=peak[0],
            cpu_seconds=(cpu_end.user + cpu_end.system - cpu_start.user - cpu_start.system),
            wall_seconds=time.monotonic() - start,
            cpu_threads=pl.thread_pool_size(),
            stored_bytes=sum(p.stat().st_size for p in files),
            sample_parquet_sha256=file_hash(files[0]),
            directory=root.name,
            optimization=(
                "Audit-first exact string/canonical schema retained. Batched validation "
                "and pruned lazy scans bound memory; no alternate numeric pipeline introduced."
            ),
            limitation=(
                "Synthetic constant prices measure storage/replay cost only; no market "
                "capacity or alpha claim. Full financial materialization uses bounded batches."
            ),
        )
        assert peak[0] < 2_000_000_000 and report["cpu_threads"] <= 2
        assert pressure(report["stored_bytes"], psutil.disk_usage(root).free) == "NORMAL"
        Path(".local/research-scale-evidence.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    finally:
        stop.set()
        thread.join(timeout=1)


if __name__ == "__main__":
    main()
