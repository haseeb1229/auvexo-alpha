"""Serialized, append-only PostgreSQL publication of bounded verified Parquet batches."""

import hashlib
import os
import shutil
import stat
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Connection, Engine, text

from auvexo_alpha.application.data_quality import (
    MAX_COMPARED_VERSIONS,
    CooldownState,
    Versioned,
    assess,
    compare_sources,
    cooldown_spans,
    cooldown_state,
    gap_evidence_refusal,
    market_hash,
)
from auvexo_alpha.application.data_schedule import qualification_window
from auvexo_alpha.domain.market_data import (
    Candle,
    Checkpoint,
    CooldownRelease,
    CooldownSpan,
    CoverageReport,
    DatasetManifest,
    GapReview,
    IngestionEvent,
    Interval,
    ProviderHost,
    SourceComparison,
    SourceConflict,
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


MANIFEST_RANGE = (
    "payload::jsonb #>> '{coverage,instrument_id}'=:instrument "
    "AND payload::jsonb #>> '{coverage,interval}'=:interval "
    "AND payload::jsonb #>> '{source,source_id}'=:source "
    "AND (payload::jsonb #>> '{coverage,requested_start}')::timestamptz < :end "
    "AND :start < (payload::jsonb #>> '{coverage,requested_end}')::timestamptz"
)
# Paged scans keep memory bounded however many rows the tables hold.
PAGE_ROWS = 1000
# A bounded report covers at most this span; larger audits run as several commands.
MAX_REPORT_SPAN = timedelta(days=31)
# Legitimate collection makes about two events a minute; this is far above any real window.
MAX_WINDOW_EVENTS = 20_000


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
                    "INSERT INTO data_event(event_id,feed_key,observed_at,blocked_until,"
                    "cooldown_host,payload) VALUES (:i,:k,:t,:b,:h,:p)"
                ),
                {
                    "i": event.event_id,
                    "k": event.feed_key,
                    "t": event.observed_at,
                    "b": event.blocked_until,
                    "h": event.cooldown_host,
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

    @staticmethod
    def _active_cooldowns(
        conn: Connection, now: datetime, host: ProviderHost
    ) -> list[IngestionEvent]:
        return [
            IngestionEvent.model_validate_json(payload)
            for payload in conn.scalars(
                text(
                    "SELECT payload FROM data_event WHERE blocked_until>:t AND observed_at<=:t "
                    "AND (cooldown_host IS NULL OR cooldown_host=:h) "
                    "ORDER BY observed_at,event_id LIMIT 4097"
                ),
                {"t": now, "h": host},
            )
        ]

    def cooldown_state(self, now: datetime, host: ProviderHost) -> tuple[CooldownState, str | None]:
        """Host-scoped durable cooldown, with the release whose single probe may be used."""
        with self.engine.connect() as conn:
            active = self._active_cooldowns(conn, now, host)
            if len(active) > 4096:
                raise ValueError("REPORT_BUDGET_EXCEEDED")
            row = conn.execute(
                text(
                    "SELECT r.release_id,r.payload,p.release_id IS NOT NULL,"
                    "COALESCE(o.outcome='PASSED',false) FROM data_cooldown_release r "
                    "LEFT JOIN data_cooldown_probe p USING(release_id) "
                    "LEFT JOIN data_cooldown_probe_result o USING(release_id) "
                    "WHERE r.host=:h AND r.released_at<=:t "
                    "ORDER BY r.released_at DESC,r.release_id LIMIT 1"
                ),
                {"h": host, "t": now},
            ).first()
        release = CooldownRelease.model_validate_json(row[1]) if row else None
        state = cooldown_state(
            now, host, active, release, bool(row and row[2]), bool(row and row[3])
        )
        return state, row[0] if row and state == "PROBE_AVAILABLE" else None

    def release_cooldown(
        self, host: ProviderHost, reviewer: str, reason: str, now: datetime
    ) -> tuple[str, CooldownRelease]:
        """Owner decision ending a host cooldown early; it permits exactly one probe."""
        with self.engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(20801407)"))
            active = self._active_cooldowns(conn, now, host)
            if not active:
                raise ValueError("NO_ACTIVE_COOLDOWN")
            if len(active) > 4096:
                raise ValueError("REPORT_BUDGET_EXCEEDED")
            release = CooldownRelease(
                host=host,
                released_at=now,
                reviewer=reviewer,
                reason=reason,
                released_until=max(e.blocked_until or now for e in active),
                released_events=tuple(e.event_id for e in active),
            )
            release_id = release.content_hash()
            conn.execute(
                text("INSERT INTO data_cooldown_release VALUES (:i,:h,:t,:r,:why,:until,:p)"),
                {
                    "i": release_id,
                    "h": host,
                    "t": now,
                    "r": reviewer,
                    "why": reason,
                    "until": release.released_until,
                    "p": release.canonical_bytes().decode(),
                },
            )
        return release_id, release

    def start_probe(self, release_id: str, url: str, now: datetime) -> None:
        """Consume the release's single probe before the request; a duplicate is refused."""
        with self.engine.begin() as conn:
            conn.execute(
                text("INSERT INTO data_cooldown_probe VALUES (:i,:t,:u)"),
                {
                    "i": release_id,
                    "t": now,
                    "u": url,
                },
            )

    def probe_result(self, release_id: str, passed: bool, reason: str, now: datetime) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text("INSERT INTO data_cooldown_probe_result VALUES (:i,:o,:r,:t)"),
                {"i": release_id, "o": "PASSED" if passed else "FAILED", "r": reason, "t": now},
            )

    def cooldowns_between(self, start: datetime, end: datetime) -> tuple[CooldownSpan, ...]:
        """Every cooldown overlapping [start, end), shortened only by a passed owner probe."""
        with self.engine.connect() as conn:
            events = [
                IngestionEvent.model_validate_json(payload)
                for payload in conn.scalars(
                    text(
                        "SELECT payload FROM data_event WHERE blocked_until IS NOT NULL "
                        "AND observed_at<:e AND blocked_until>:s "
                        "ORDER BY observed_at,event_id LIMIT 4097"
                    ),
                    {"s": start, "e": end},
                )
            ]
            if len(events) > 4096:
                raise ValueError("REPORT_BUDGET_EXCEEDED")
            passed = [
                (CooldownRelease.model_validate_json(payload), at.astimezone(UTC))
                for payload, at in conn.execute(
                    text(
                        "SELECT r.payload,o.recorded_at FROM data_cooldown_release r "
                        "JOIN data_cooldown_probe_result o USING(release_id) "
                        "WHERE o.outcome='PASSED' AND r.released_until>:s AND r.released_at<:e"
                    ),
                    {"s": start, "e": end},
                )
            ]
        return cooldown_spans(events, passed)

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

    @staticmethod
    def _checked(payload: str, digest: str) -> DatasetManifest:
        manifest = DatasetManifest.model_validate_json(payload)
        if manifest.content_hash() != digest:
            raise ValueError("MANIFEST_HASH_MISMATCH")
        return manifest

    def manifest_pages(self) -> Iterator[list[DatasetManifest]]:
        """Every manifest in keyset pages of PAGE_ROWS; memory never holds the whole table."""
        cursor: tuple[datetime, str] | None = None
        select = "SELECT payload,manifest_hash,recorded_at,dataset_version FROM data_manifest "
        order = " ORDER BY recorded_at,dataset_version LIMIT :n"
        while True:
            with self.engine.connect() as conn:
                if cursor is None:
                    rows = conn.execute(text(select + order), {"n": PAGE_ROWS}).all()
                else:
                    rows = conn.execute(
                        text(select + "WHERE (recorded_at,dataset_version)>(:t,:v)" + order),
                        {"t": cursor[0], "v": cursor[1], "n": PAGE_ROWS},
                    ).all()
            if not rows:
                return
            yield [self._checked(payload, digest) for payload, digest, _, _ in rows]
            cursor = (rows[-1][2], rows[-1][3])

    def manifests_by_version(self, versions: Sequence[str]) -> list[DatasetManifest]:
        if len(versions) > MAX_COMPARED_VERSIONS:
            raise ValueError("REPORT_BUDGET_EXCEEDED")
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT payload,manifest_hash FROM data_manifest "
                    "WHERE dataset_version = ANY(:v) ORDER BY dataset_version"
                ),
                {"v": list(versions)},
            ).all()
        return [self._checked(payload, digest) for payload, digest in rows]

    def manifests_in_range(
        self, source: str, instrument: str, interval: Interval, start: datetime, end: datetime
    ) -> list[DatasetManifest]:
        """Manifests of one source whose requested coverage overlaps [start, end); bounded."""
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT payload,manifest_hash FROM data_manifest WHERE "
                    + MANIFEST_RANGE
                    + " ORDER BY recorded_at,dataset_version LIMIT :n"
                ),
                {
                    "source": source,
                    "instrument": instrument,
                    "interval": interval,
                    "start": start,
                    "end": end,
                    "n": MAX_COMPARED_VERSIONS + 1,
                },
            ).all()
        if len(rows) > MAX_COMPARED_VERSIONS:
            raise ValueError("COMPARISON_BUDGET_EXCEEDED")
        return [self._checked(payload, digest) for payload, digest in rows]

    def verified_bars(self, manifest: DatasetManifest) -> list[Candle]:
        self.verify(manifest)
        return read_bars(self.path(manifest))

    def reconcile(self) -> dict[str, int]:
        """Verify every manifest and count unpublished files, page by page."""
        verified = 0
        for page in self.manifest_pages():
            for manifest in page:
                self.verify(manifest)
            verified += len(page)
        orphans = 0
        batch: list[tuple[str, Path]] = []

        def unpublished(candidates: list[tuple[str, Path]]) -> int:
            with self.engine.connect() as conn:
                known = {
                    (version, path)
                    for version, path in conn.execute(
                        text(
                            "SELECT dataset_version,payload::jsonb->>'relative_path' "
                            "FROM data_manifest WHERE dataset_version = ANY(:v)"
                        ),
                        {"v": [version for version, _ in candidates]},
                    )
                }
            return sum(
                (version, path.relative_to(self.root).as_posix()) not in known
                for version, path in candidates
            )

        for path in self.root.rglob("*.parquet"):
            batch.append((path.stem, path))
            if len(batch) == PAGE_ROWS:
                orphans += unpublished(batch)
                batch = []
        if batch:
            orphans += unpublished(batch)
        return {
            "verified_manifests": verified,
            "unpublished_orphans": orphans,
            "staging_files": sum(1 for _ in self.root.rglob("*.stage")),
        }

    def current_manifests(self, start: date, end: date) -> list[DatasetManifest]:
        """Current (unsuperseded) manifests whose requested coverage overlaps the days."""
        lower, upper = report_range(start, end)
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT m.payload,m.manifest_hash FROM data_manifest m "
                    "WHERE (m.payload::jsonb #>> '{coverage,requested_start}')::timestamptz<:e "
                    "AND :s<(m.payload::jsonb #>> '{coverage,requested_end}')::timestamptz "
                    "AND NOT EXISTS (SELECT 1 FROM data_manifest n "
                    "WHERE n.supersedes=m.dataset_version) "
                    "ORDER BY m.recorded_at,m.dataset_version LIMIT :n"
                ),
                {"s": lower, "e": upper, "n": MAX_REPORT_ROWS + 1},
            ).all()
        if len(rows) > MAX_REPORT_ROWS:
            raise ValueError("REPORT_BUDGET_EXCEEDED_NARROW_THE_RANGE")
        return [self._checked(payload, digest) for payload, digest in rows]

    def events_between(self, start: datetime, end: datetime) -> list[IngestionEvent]:
        with self.engine.connect() as conn:
            result = [
                IngestionEvent.model_validate_json(payload)
                for payload in conn.scalars(
                    text(
                        "SELECT payload FROM data_event WHERE observed_at>=:s AND observed_at<:e "
                        "ORDER BY observed_at,event_id LIMIT :n"
                    ),
                    {"s": start, "e": end, "n": MAX_WINDOW_EVENTS + 1},
                )
            ]
        if len(result) > MAX_WINDOW_EVENTS:
            raise ValueError("REPORT_BUDGET_EXCEEDED_NARROW_THE_RANGE")
        return result

    def qualification_inputs(
        self, start_day: date, days: int = 7
    ) -> tuple[
        list[IngestionEvent], list[DatasetManifest], tuple[CooldownSpan, ...], list[GapReview]
    ]:
        """Only what qualification reads: the days' window events, their verified manifests,
        cooldowns overlapping those calendar days and reviewed gaps inside them.

        Each query is bounded by the requested dates, never by the size of the tables.
        """
        events: list[IngestionEvent] = []
        for offset in range(days):
            window_start, window_end = qualification_window(start_day + timedelta(days=offset))
            events.extend(
                e
                for e in self.events_between(window_start, window_end)
                if e.feed_key.startswith("DS-02.")
            )
        versions = sorted({e.dataset_version for e in events if e.dataset_version})
        manifests = []
        for index in range(0, len(versions), PAGE_ROWS):
            for manifest in self.manifests_by_version(versions[index : index + PAGE_ROWS]):
                self.verify(manifest)
                manifests.append(manifest)
        first = datetime.combine(start_day, datetime.min.time(), UTC)
        last = first + timedelta(days=days)
        return events, manifests, self.cooldowns_between(first, last), self.gaps(first, last)

    def gaps(self, start: datetime, end: datetime, feed: str | None = None) -> list[GapReview]:
        """Reviewed gaps overlapping [start, end); every one stays visible forever."""
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT payload,payload_hash FROM data_gap_review "
                    "WHERE gap_start<:e AND :s<gap_end "
                    "AND (CAST(:f AS text) IS NULL OR feed_key=:f) "
                    "ORDER BY gap_start,feed_key LIMIT :n"
                ),
                {"s": start, "e": end, "f": feed, "n": MAX_REPORT_ROWS + 1},
            ).all()
        if len(rows) > MAX_REPORT_ROWS:
            raise ValueError("REPORT_BUDGET_EXCEEDED_NARROW_THE_RANGE")
        result = []
        for payload, digest in rows:
            review = GapReview.model_validate_json(payload)
            if review.content_hash() != digest:
                raise ValueError("GAP_REVIEW_HASH_MISMATCH")
            result.append(review)
        return result

    def record_gap(self, review: GapReview) -> str:
        """Durably accept an owner-reviewed provider gap only on proof from stored responses."""
        evidence: list[Versioned] = []
        for manifest in self.manifests_by_version(
            [item.dataset_version for item in review.evidence]
        ):
            evidence.append((manifest, self.verified_bars(manifest)))
        contradicting: list[Versioned] = [
            (manifest, self.verified_bars(manifest))
            for manifest in self.manifests_in_range(
                "DS-02", review.instrument_id, review.interval, review.gap_start, review.gap_end
            )
        ]
        with self.engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(20801402)"))
            checkpoint = self.checkpoint(review.feed_key)
            refusal = gap_evidence_refusal(
                review, evidence, contradicting, checkpoint.next_open if checkpoint else None
            )
            if refusal:
                raise ValueError(refusal)
            if any(
                g.feed_key == review.feed_key
                for g in self.gaps(review.gap_start, review.gap_end, review.feed_key)
            ):
                raise ValueError("OVERLAPPING_GAP_REVIEW")
            gap_id = review.content_hash()
            conn.execute(
                text(
                    "INSERT INTO data_gap_review VALUES "
                    "(:i,:f,'DS-02',:inst,:iv,:s,:e,:r,:rev,:at,:h,:p)"
                ),
                {
                    "i": gap_id,
                    "f": review.feed_key,
                    "inst": review.instrument_id,
                    "iv": review.interval,
                    "s": review.gap_start,
                    "e": review.gap_end,
                    "r": review.reason,
                    "rev": review.reviewer,
                    "at": review.reviewed_at,
                    "h": gap_id,
                    "p": review.canonical_bytes().decode(),
                },
            )
            for item in review.evidence:
                conn.execute(
                    text("INSERT INTO data_gap_evidence VALUES (:i,:v)"),
                    {"i": gap_id, "v": item.dataset_version},
                )
        return gap_id

    def compare_sources(
        self, instrument: str, interval: Interval, start: datetime, end: datetime, now: datetime
    ) -> tuple[SourceComparison, tuple[SourceConflict, ...]]:
        """Compare stored archive and REST bars in one bounded range; append conflicts.

        Stored bars, manifests and availability times are only read. Re-running the same
        comparison over the same stored versions appends nothing new.
        """
        if not timedelta(0) < end - start <= MAX_REPORT_SPAN:
            raise ValueError("COMPARISON_RANGE_INVALID")
        sides: dict[str, list[Versioned]] = {}
        for source in ("DS-01", "DS-02"):
            sides[source] = [
                (manifest, self.verified_bars(manifest))
                for manifest in self.manifests_in_range(source, instrument, interval, start, end)
            ]
        comparison, conflicts = compare_sources(
            sides["DS-01"], sides["DS-02"], instrument, interval, start, end
        )
        comparison_id = comparison.content_hash()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO data_source_comparison VALUES "
                    "(:i,:inst,:iv,:s,:e,:m,:c,:a,:r,:t,:p) ON CONFLICT DO NOTHING"
                ),
                {
                    "i": comparison_id,
                    "inst": instrument,
                    "iv": interval,
                    "s": start,
                    "e": end,
                    "m": comparison.matched,
                    "c": len(conflicts),
                    "a": comparison.archive_only,
                    "r": comparison.rest_only,
                    "t": now,
                    "p": comparison.canonical_bytes().decode(),
                },
            )
            for conflict in conflicts:
                conn.execute(
                    text(
                        "INSERT INTO data_source_conflict VALUES (:i,:c,:inst,:iv,:o,:av,:as,"
                        ":am,:rv,:rs,:rm,:k,:t,:p) ON CONFLICT DO NOTHING"
                    ),
                    {
                        "i": conflict.content_hash(),
                        "c": comparison_id,
                        "inst": instrument,
                        "iv": interval,
                        "o": conflict.open_at,
                        "av": conflict.archive_version,
                        "as": conflict.archive_source_hash,
                        "am": conflict.archive_market_hash,
                        "rv": conflict.rest_version,
                        "rs": conflict.rest_source_hash,
                        "rm": conflict.rest_market_hash,
                        "k": conflict.known_at,
                        "t": max(now, conflict.known_at),
                        "p": conflict.canonical_bytes().decode(),
                    },
                )
        return comparison, conflicts

    def conflicts(
        self, instrument: str, interval: Interval, start: datetime, end: datetime
    ) -> list[SourceConflict]:
        """Recorded archive/REST conflicts for bars opening in [start, end)."""
        with self.engine.connect() as conn:
            payloads = list(
                conn.scalars(
                    text(
                        "SELECT payload FROM data_source_conflict WHERE instrument_id=:inst "
                        "AND bar_interval=:iv AND open_at>=:s AND open_at<:e "
                        "ORDER BY open_at,conflict_id LIMIT :n"
                    ),
                    {
                        "inst": instrument,
                        "iv": interval,
                        "s": start,
                        "e": end,
                        "n": MAX_REPORT_ROWS + 1,
                    },
                )
            )
        if len(payloads) > MAX_REPORT_ROWS:
            raise ValueError("REPORT_BUDGET_EXCEEDED_NARROW_THE_RANGE")
        return [SourceConflict.model_validate_json(p) for p in payloads]


# One bounded report holds at most this many rows of any kind.
MAX_REPORT_ROWS = 50_000


def report_range(start: date, end: date) -> tuple[datetime, datetime]:
    """Inclusive UTC calendar days [start, end] as a half-open instant range, at most 31 days."""
    lower = datetime.combine(start, datetime.min.time(), UTC)
    upper = datetime.combine(end, datetime.min.time(), UTC) + timedelta(days=1)
    if not timedelta(0) < upper - lower <= MAX_REPORT_SPAN:
        raise ValueError("REPORT_RANGE_INVALID")
    return lower, upper
