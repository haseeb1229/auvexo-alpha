"""Reconstruct accepted normalized data and exact Parquet from retained source bytes."""

from pathlib import PurePosixPath
from urllib.parse import urlsplit

from auvexo_alpha.domain.market_data import Candle, DataAvailabilityWindow, DatasetManifest, Symbol
from auvexo_alpha.infrastructure.data_store import DataStore, parquet_bytes, sha
from auvexo_alpha.infrastructure.spot_parser import parse_archive, parse_rest


def replay(store: DataStore, manifest: DatasetManifest) -> None:
    store.verify(manifest)
    raw = (store.root / manifest.raw_relative_path).read_bytes()
    coverage = manifest.coverage
    symbol: Symbol
    if coverage.instrument_id == "binance.spot.BTCUSDT":
        symbol = "BTCUSDT"
    elif coverage.instrument_id == "binance.spot.ETHUSDT":
        symbol = "ETHUSDT"
    else:
        raise ValueError("REPLAY_SOURCE_UNSUPPORTED")
    if manifest.source.source_id == "DS-01":
        filename = PurePosixPath(urlsplit(manifest.source_url).path).name
        # The accepted manifest retains the provider-verified source digest, not a new
        # assertion about today's provider revision. Independent network recheck is separate.
        checksum = f"{manifest.source_hash}  {filename}".encode("ascii")
        bars, report = parse_archive(
            raw,
            checksum,
            filename,
            symbol,
            coverage.interval,
            coverage.requested_start,
            coverage.requested_end,
            manifest.created_at,
            manifest.source_url,
        )
    else:
        bars, report = parse_rest(
            raw,
            symbol,
            coverage.interval,
            coverage.requested_start,
            coverage.requested_end,
            manifest.created_at,
            manifest.source_url,
        )
    bars = [
        Candle.model_validate(
            bar.model_dump()
            | {
                "availability": DataAvailabilityWindow.model_validate(
                    bar.availability.model_dump()
                    | {"processed_at": manifest.processed_at, "available_at": manifest.processed_at}
                )
            }
        )
        for bar in bars
    ]
    if (
        report != coverage
        or sha(b"\n".join(b.canonical_bytes() for b in bars)) != manifest.normalized_hash
    ):
        raise ValueError("SOURCE_REPLAY_MISMATCH")
    if sha(parquet_bytes(bars)) != manifest.parquet_hash:
        raise ValueError("PARQUET_REPLAY_MISMATCH")
