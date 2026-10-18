"""Serialized, append-only PostgreSQL publication of bounded verified Parquet batches."""

import hashlib
import os
import shutil
import stat
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Engine, text

from auvexo_alpha.application.data_quality import assess
from auvexo_alpha.domain.market_data import (
    Candle,
    Checkpoint,
    CoverageReport,
    DatasetManifest,
    IngestionEvent,
    SourceIdentity,
    SourceRights,
    SpecSnapshot,
)
from auvexo_alpha.infrastructure.spot_parser import ParserVersion

# Set before the first Polars import: no optional GPU, cloud or unbounded thread pool.
os.environ["POLARS_MAX_THREADS"] = "2"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_code_hash() -> str:
    root = Path(__file__).resolve().parents[1]
    return sha(
        b"\n".join(
            path.relative_to(root).as_posix().encode() + b":" + path.read_bytes()
            for path in sorted(root.rglob("*.py"))
        )
    )


def tree_bytes(root: Path, allow_internal_aliases: bool = False) -> int:
    total = 0
    resolved = root.resolve()
    pending = [root]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                metadata = entry.stat(follow_symlinks=False)
                is_link = stat.S_ISLNK(metadata.st_mode) or bool(
                    getattr(metadata, "st_file_attributes", 0)
                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                )
                if is_link:
                    if not allow_internal_aliases or not Path(entry.path).resolve().is_relative_to(
                        resolved
                    ):
                        raise ValueError("UNSAFE_STORAGE_LINK")
                    continue
                if stat.S_ISDIR(metadata.st_mode):
                    pending.append(Path(entry.path))
                elif stat.S_ISREG(metadata.st_mode):
                    total += metadata.st_size
    return total


def pressure(managed: int, free: int) -> str:
    if managed >= 150_000_000_000 or free < 20_000_000_000:
        return "HARD_STOP"
    if managed >= 135_000_000_000 or free < 40_000_000_000:
        return "PAUSE_OPTIONAL"
    if managed >= 120_000_000_000 or free < 60_000_000_000:
        return "PAUSE_BACKFILL"
    return "NORMAL"


def parquet_bytes(bars: list[Candle]) -> bytes:
    import io

    import polars as pl

    # Exact decimal strings, never Float64. Canonical record preserves full versioned shape;
    # scalar columns support column-pruned identity/time scans without a second representation.
    frame = pl.DataFrame(
        {
            "instrument_id": [bar.instrument_id for bar in bars],
            "open_at": [bar.open_at for bar in bars],
            "end_at": [bar.end_at for bar in bars],
            "open": [str(bar.open) for bar in bars],
            "high": [str(bar.high) for bar in bars],
            "low": [str(bar.low) for bar in bars],
            "close": [str(bar.close) for bar in bars],
            "volume": [str(bar.volume) for bar in bars],
            "record": [bar.canonical_bytes().decode("ascii") for bar in bars],
        }
    )
    buffer = io.BytesIO()
    frame.write_parquet(
        buffer, compression="zstd", compression_level=3, statistics=True, row_group_size=4096
    )
    return buffer.getvalue()


def read_bars(path: Path) -> list[Candle]:
    import polars as pl

    return [
        Candle.model_validate_json(record)
        for record in pl.read_parquet(path, columns=["record"]).get_column("record")
    ]


def market_hash(bar: Candle) -> str:
    return sha(
        str(
            (
                bar.open_at,
                bar.end_at,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                bar.quote_volume,
                bar.trades,
            )
        ).encode("ascii")
    )


class DataStore:
    def __init__(
        self, engine: Engine, root: Path, managed_root: Path, quota: int = 2_000_000_000
    ) -> None:
        if not 1 <= quota <= 35_000_000_000:
            raise ValueError("invalid data quota")
        self.engine, self.root, self.managed_root, self.quota = (
            engine,
            root.resolve(),
            managed_root.resolve(),
            quota,
        )
        if not self.root.is_relative_to(self.managed_root):
            raise ValueError("data must be inside managed root")
        self.root.mkdir(parents=True, exist_ok=True)
        self.check_quota(0)

    def check_quota(self, extra: int, database_bytes: int | None = None) -> None:
        free = shutil.disk_usage(self.managed_root).free
        if database_bytes is None:
            with self.engine.connect() as conn:
                database_bytes = int(
                    conn.scalar(text("SELECT pg_database_size(current_database())")) or 0
                )
        if (
            pressure(tree_bytes(self.managed_root, True) + database_bytes + extra, free - extra)
            != "NORMAL"
            or tree_bytes(self.root) + extra > self.quota
        ):
            raise ValueError("QUOTA")

    def path(self, manifest: DatasetManifest) -> Path:
        candidate = self.root / manifest.relative_path
        if not candidate.resolve().is_relative_to(self.root):
            raise ValueError("UNSAFE_STORAGE_PATH")
        return candidate

    def verify(self, manifest: DatasetManifest) -> None:
        path = self.path(manifest)
        raw_path = self.root / manifest.raw_relative_path
        if (
            not raw_path.is_file()
            or raw_path.stat().st_size != manifest.raw_bytes
            or file_hash(raw_path) != manifest.source_hash
        ):
            raise ValueError("RAW_SOURCE_MISMATCH")
        if (
            not path.is_file()
            or path.stat().st_size != manifest.parquet_bytes
            or file_hash(path) != manifest.parquet_hash
        ):
            raise ValueError("MANIFEST_FILE_MISMATCH")
        bars = read_bars(path)
        if (
            len(bars) != manifest.coverage.observed_rows
            or sha(b"\n".join(b.canonical_bytes() for b in bars)) != manifest.normalized_hash
        ):
            raise ValueError("NORMALIZED_HASH_MISMATCH")

    def manifests(self) -> list[DatasetManifest]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT payload,manifest_hash FROM data_manifest "
                    "ORDER BY recorded_at,dataset_version LIMIT 10001"
                )
            ).all()
        if len(rows) > 10000:
            raise ValueError("REPORT_BUDGET_EXCEEDED")
        result = []
        for payload, digest in rows:
            manifest = DatasetManifest.model_validate_json(payload)
            if manifest.content_hash() != digest:
                raise ValueError("MANIFEST_HASH_MISMATCH")
            result.append(manifest)
        return result

    def publish(
        self,
        bars: list[Candle],
        coverage: CoverageReport,
        source: SourceIdentity,
        rights: SourceRights,
        key: str,
        url: str,
        raw: bytes,
        received: datetime,
        code_revision: str,
        checkpoint: str | None = None,
        parser_version: ParserVersion = "spot.v2",
    ) -> DatasetManifest:
        rights.require_research(received)
        if not bars or source.source_id != rights.source_id:
            raise ValueError("EMPTY_OR_SOURCE_MISMATCH")
        digest = sha(raw)
        if any(
            b.source.source_hash != digest
            or b.source.source_id != source.source_id
            or b.source.source_url != url
            or b.source.received_at != received
            for b in bars
        ):
            raise ValueError("PROVENANCE_MISMATCH")
        checked, actual = assess(
            bars,
            coverage.instrument_id,
            coverage.interval,
            coverage.requested_start,
            coverage.requested_end,
            list(coverage.findings),
            coverage.rejected_rows,
        )
        if (
            checked != bars
            or len(bars) != coverage.observed_rows
            or actual.earliest != coverage.earliest
            or actual.latest_end != coverage.latest_end
            or actual.expected_rows != coverage.expected_rows
            or actual.status != coverage.status
        ):
            raise ValueError("COVERAGE_MISMATCH")
        version = sha((key + ":" + digest + ":" + parser_version).encode("ascii"))
        with self.engine.begin() as conn:
            # One bounded local publisher protects both quota and correction/checkpoint races.
            conn.execute(text("SELECT pg_advisory_xact_lock(20801402)"))
            existing = conn.scalar(
                text("SELECT payload FROM data_manifest WHERE dataset_version=:v"), {"v": version}
            )
            if existing is not None:
                manifest = DatasetManifest.model_validate_json(existing)
                self.verify(manifest)
                return manifest
            prior = conn.scalar(
                text(
                    "SELECT payload FROM data_manifest WHERE logical_key=:k "
                    "ORDER BY recorded_at DESC,dataset_version DESC LIMIT 1"
                ),
                {"k": key},
            )
            previous = DatasetManifest.model_validate_json(prior) if prior else None
            old = {}
            if previous:
                self.verify(previous)
                old = {b.open_at: market_hash(b) for b in read_bars(self.path(previous))}
            current = {b.open_at: market_hash(b) for b in bars}
            changed = (
                sum(old.get(k) != current.get(k) for k in old.keys() | current.keys())
                if previous
                else 0
            )
            content = parquet_bytes(bars)
            self.check_quota(
                len(content) * 2 + len(raw) * 2 + 1_048_576,
                int(conn.scalar(text("SELECT pg_database_size(current_database())")) or 0),
            )
            manifest = DatasetManifest(
                dataset_version=version,
                parser_version=parser_version,
                logical_key=key,
                source=source,
                rights=rights,
                source_url=url,
                source_hash=digest,
                checksum_verified=source.source_id == "DS-01",
                raw_bytes=len(raw),
                raw_relative_path=f"bronze/{digest}.raw",
                parquet_hash=sha(content),
                parquet_bytes=len(content),
                relative_path=f"partitions/{coverage.instrument_id}/{version}.parquet",
                normalized_hash=sha(b"\n".join(b.canonical_bytes() for b in bars)),
                code_revision=code_revision,
                code_hash=source_code_hash(),
                created_at=received,
                processed_at=bars[0].availability.processed_at,
                coverage=coverage,
                supersedes=previous.dataset_version if previous else None,
                changed_rows=changed,
            )
            destination = self.path(manifest)
            destination.parent.mkdir(parents=True, exist_ok=True)
            raw_path = self.root / manifest.raw_relative_path
            raw_path.parent.mkdir(exist_ok=True)
            if raw_path.exists():
                if file_hash(raw_path) != digest:
                    raise ValueError("RAW_SOURCE_MISMATCH")
            else:
                raw_stage = raw_path.with_suffix("." + uuid4().hex + ".stage")
                try:
                    with raw_stage.open("xb") as stream:
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(raw_stage, raw_path)
                finally:
                    raw_stage.unlink(missing_ok=True)
            stage = destination.with_suffix("." + uuid4().hex + ".stage")
            try:
                with stage.open("xb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                if file_hash(stage) != manifest.parquet_hash:
                    raise ValueError("STAGING_HASH_MISMATCH")
                os.replace(stage, destination)
                self.verify(manifest)
                conn.execute(
                    text("INSERT INTO data_source_review VALUES (:h,:p) ON CONFLICT DO NOTHING"),
                    {"h": rights.content_hash(), "p": rights.canonical_bytes().decode()},
                )
                conn.execute(
                    text("INSERT INTO data_manifest VALUES (:v,:k,:s,:t,:prior,:h,:p)"),
                    {
                        "v": version,
                        "k": key,
                        "s": digest,
                        "t": received,
                        "prior": manifest.supersedes,
                        "h": manifest.content_hash(),
                        "p": manifest.canonical_bytes().decode(),
                    },
                )
                if checkpoint and coverage.status == "PASS":
                    conn.execute(
                        text(
                            "INSERT INTO data_checkpoint VALUES (:k,:n,:v,:t) "
                            "ON CONFLICT DO NOTHING"
                        ),
                        {"k": checkpoint, "n": coverage.requested_end, "v": version, "t": received},
                    )
            finally:
                stage.unlink(missing_ok=True)
        return manifest

    def checkpoint(self, feed: str) -> Checkpoint | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT c.next_open,c.dataset_version,c.recorded_at,m.payload,m.manifest_hash "
                    "FROM data_checkpoint c JOIN data_manifest m USING(dataset_version) "
                    "WHERE c.feed_key=:k ORDER BY c.next_open DESC LIMIT 1"
                ),
                {"k": feed},
            ).first()
        if row:
            manifest = DatasetManifest.model_validate_json(row[3])
            manifest.coverage.require_complete()
            if manifest.content_hash() != row[4] or manifest.coverage.requested_end != row[0]:
                raise ValueError("CHECKPOINT_MANIFEST_MISMATCH")
            self.verify(manifest)
        return (
            Checkpoint(
                feed_key=feed,
                next_open=row[0].astimezone(UTC),
                dataset_version=row[1],
                recorded_at=row[2].astimezone(UTC),
            )
            if row
            else None
        )

    def event(self, event: IngestionEvent) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO data_event(event_id,feed_key,observed_at,blocked_until,payload) "
                    "VALUES (:i,:k,:t,:b,:p)"
                ),
                {
                    "i": event.event_id,
                    "k": event.feed_key,
                    "t": event.observed_at,
                    "b": event.blocked_until,
                    "p": event.canonical_bytes().decode(),
                },
            )

    def quarantine(self, raw: bytes) -> str:
        """Retain rejected public bytes outside accepted partitions under the same quota."""
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError("QUARANTINE_BUDGET")
        digest = sha(raw)
        with self.engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(20801402)"))
            size = int(conn.scalar(text("SELECT pg_database_size(current_database())")) or 0)
            self.check_quota(len(raw), size)
            directory = self.root / "quarantine"
            directory.mkdir(exist_ok=True)
            target = directory / (digest + ".raw")
            if target.exists():
                if file_hash(target) != digest:
                    raise ValueError("QUARANTINE_HASH_MISMATCH")
                return digest
            stage = directory / (uuid4().hex + ".stage")
            try:
                with stage.open("xb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                stage.replace(target)
            finally:
                stage.unlink(missing_ok=True)
        return digest

    def events(self) -> list[IngestionEvent]:
        with self.engine.connect() as conn:
            result = [
                IngestionEvent.model_validate_json(p)
                for p in conn.scalars(
                    text(
                        "SELECT payload FROM data_event ORDER BY observed_at DESC,event_id "
                        "LIMIT 10001"
                    )
                )
            ]
        if len(result) > 10000:
            raise ValueError("REPORT_BUDGET_EXCEEDED")
        return sorted(result, key=lambda e: e.observed_at)

    def cooldown(self, now: datetime) -> bool:
        with self.engine.connect() as conn:
            return bool(
                conn.scalar(
                    text("SELECT EXISTS(SELECT 1 FROM data_event WHERE blocked_until>:t)"),
                    {"t": now},
                )
            )

    def spec(self, snapshot: SpecSnapshot, raw: bytes) -> None:
        if sha(raw) != snapshot.spec_version:
            raise ValueError("SPEC_HASH_MISMATCH")
        self.check_quota(len(raw) * 2 + 16384)
        with self.engine.begin() as conn:
            conn.execute(
                text("INSERT INTO data_spec VALUES (:h,:s,:p) ON CONFLICT DO NOTHING"),
                {"h": snapshot.spec_version, "s": snapshot.canonical_bytes().decode(), "p": raw},
            )

    def read_as_of(self, manifest: DatasetManifest, as_of: datetime) -> list[Candle]:
        manifest.coverage.require_complete()
        self.verify(manifest)
        bars = read_bars(self.path(manifest))
        for bar in bars:
            bar.require_as_of(as_of)
        return bars

    def cleanup_staging(self) -> int:
        # Only regenerable stage files under this exact managed root, never accepted artifacts.
        count = 0
        with self.engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(20801402)"))
            for path in self.root.rglob("*.stage"):
                if path.is_symlink() or not path.resolve().is_relative_to(self.root):
                    raise ValueError("UNSAFE_STORAGE_PATH")
                path.unlink()
                count += 1
        return count

    def verified_manifests(self) -> list[DatasetManifest]:
        manifests = self.manifests()
        for manifest in manifests:
            self.verify(manifest)
        return manifests

    def reconcile(self) -> dict[str, int]:
        manifests = self.verified_manifests()
        accepted = {self.path(m).resolve() for m in manifests}
        return {
            "verified_manifests": len(manifests),
            "unpublished_orphans": sum(
                p.resolve() not in accepted for p in self.root.rglob("*.parquet")
            ),
            "staging_files": sum(1 for _ in self.root.rglob("*.stage")),
        }
