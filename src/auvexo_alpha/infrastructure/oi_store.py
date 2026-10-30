"""DS-04-A1 immutable artifacts and append-only metadata in a dedicated research DB.

The generic accepted data tables already provide append-only constraints. This adapter
never uses Candle, spot coverage or the operational database. Local administrator/file
compromise remains outside the immutability guarantee, and hash checks fail closed.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Annotated, Literal
from uuid import uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, text

from auvexo_alpha.domain.contracts import Contract, Digest, utc_time
from auvexo_alpha.domain.oi_rights_review import OIReviewAuthority, require_oi_rights
from auvexo_alpha.domain.open_interest import (
    OIManifest,
    OIObservation,
    OIRights,
    accepted_oi_rights,
    oi_dataset_version,
)
from auvexo_alpha.domain.research import DataUseClass
from auvexo_alpha.infrastructure.data_store import pressure, tree_bytes
from auvexo_alpha.infrastructure.oi_http import OIBudgetState
from auvexo_alpha.infrastructure.oi_parser import parse_oi

if TYPE_CHECKING:
    from auvexo_alpha.application.oi_research import (
        OIFeatureSnapshot,
        OIForecast,
        OIPairScore,
        OIStudyWindow,
    )

_LOCK = 20801406
_PREFIX = "ds04-a1:"
_BUDGET_FEED = "DS-04-A1:transport-budget"
_MAX_RECORDS = 10000


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _encoded(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _link(path: Path) -> bool:
    metadata = path.lstat()
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def attest_oi_database(conn: Connection, review_authority: OIReviewAuthority | None = None) -> None:
    """Read-only source isolation proof, repeated on every initialization/restart.

    Prefix resemblance is not a namespace. Existing rows are never removed or
    rewritten to obtain a pass, and continuation receipts are admitted only by
    the exact externally accepted authority supplied by the caller.
    """
    if (
        # OI snapshots never produce instrument/spec receipts. Any such row is
        # foreign source data, even when other generic tables are still empty.
        conn.scalar(text("SELECT EXISTS(SELECT 1 FROM data_spec)"))
        or conn.scalar(
            text("SELECT EXISTS(SELECT 1 FROM data_manifest WHERE logical_key !~ :pattern)"),
            {"pattern": "^ds04-a1:(BTCUSDT|ETHUSDT):[0-9]{13}:oi-snapshot[.]v1$"},
        )
        or conn.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM data_checkpoint "
                "WHERE feed_key NOT IN ('DS-04-A1:BTCUSDT','DS-04-A1:ETHUSDT'))"
            )
        )
        or conn.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM data_event WHERE NOT ("
                "(feed_key='DS-04-A1:transport-budget' "
                "AND event_id ~ '^oi-budget:[0-9a-f]{64}$') OR "
                "(feed_key='DS-04-A1:quarantine' "
                "AND event_id ~ '^oi-quarantine:[0-9a-f]{64}:"
                "(SCHEMA|PARSER_REJECTED|SOURCE_REJECTED|RIGHTS_REJECTED)$') OR "
                "(feed_key IN ('DS-04-A1:ledger:STUDY','DS-04-A1:ledger:FEATURE',"
                "'DS-04-A1:ledger:FORECAST','DS-04-A1:ledger:SCORE') "
                "AND event_id ~ '^oi-ledger:(STUDY|FEATURE|FORECAST|SCORE):[0-9a-f]{64}$' "
                "AND split_part(feed_key,':',3)=split_part(event_id,':',2))))"
            )
        )
    ):
        raise ValueError("OI_DEDICATED_DATABASE_REQUIRED")
    base = accepted_oi_rights()
    permitted_reviews = {base.content_hash(): base.canonical_bytes().decode("ascii")}
    if review_authority is not None:
        supplied = review_authority
        checked = OIReviewAuthority(
            supplied.base, supplied.chain, supplied.accepted_digests, supplied.now
        )
        permitted_reviews.update(
            (receipt.content_hash(), receipt.canonical_bytes().decode("ascii"))
            for receipt in checked.chain
        )
    reviews = conn.execute(
        text("SELECT review_hash,payload FROM data_source_review LIMIT 258")
    ).all()
    if len(reviews) > 257 or any(
        permitted_reviews.get(digest) != payload for digest, payload in reviews
    ):
        raise ValueError("OI_DEDICATED_DATABASE_REQUIRED")


class OIStore:
    """A source-specific store; requires a dedicated non-operational PostgreSQL DB.

    Runtime SQL uses the existing least-privilege data-writer LOGIN. Spot consumers
    intentionally retain their own contracts and must never be pointed at this DB.
    """

    def __init__(
        self,
        engine: Engine,
        root: Path,
        managed_root: Path,
        quota: int = 128_000_000,
        *,
        review_authority: OIReviewAuthority | None = None,
    ) -> None:
        if (
            engine.url.get_backend_name() != "postgresql"
            or engine.url.host != "127.0.0.1"
            or engine.url.port in (None, 55432)
            or not (engine.url.database or "").startswith(("auvexo_dev_oi", "auvexo_test_oi"))
            or engine.url.username != "auvexo_data_writer"
            or engine.url.query
        ):
            raise ValueError("OI_ISOLATED_DATABASE_REQUIRED")
        if not 1 <= quota <= 2_000_000_000:
            raise ValueError("OI_QUOTA_INVALID")
        absolute_root = root.absolute()
        absolute_managed = managed_root.absolute()
        if not absolute_root.is_relative_to(absolute_managed):
            raise ValueError("OI_UNSAFE_STORAGE_PATH")
        for candidate in (absolute_managed, absolute_root):
            for ancestor in (candidate, *candidate.parents):
                if ancestor.exists() and _link(ancestor):
                    raise ValueError("OI_UNSAFE_STORAGE_LINK")
        self.engine = engine
        self.review_authority = review_authority
        self.root = absolute_root
        self.managed_root = absolute_managed
        self.quota = quota
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT current_user,current_database(),inet_server_port(),"
                    "r.rolsuper,r.rolcreatedb,r.rolcreaterole "
                    "FROM pg_roles r WHERE rolname=current_user"
                )
            ).one()
            if (
                row[0] != "auvexo_data_writer"
                or row[1] != engine.url.database
                or row[2] != engine.url.port
                or any(row[3:])
            ):
                raise ValueError("OI_DATABASE_IDENTITY_MISMATCH")
            self._attest_dedicated_database(conn)
        self.root.mkdir(parents=True, exist_ok=True)
        self.check_quota(0)

    def _attest_dedicated_database(self, conn: Connection) -> None:
        """Share unchanged read-only namespace/review proof with owner restart tooling."""
        attest_oi_database(conn, self.review_authority)

    def _path(self, relative: str) -> Path:
        parsed = PurePosixPath(relative)
        if (
            parsed.is_absolute()
            or ".." in parsed.parts
            or "\\" in relative
            or ":" in relative
            or not relative.startswith("oi/")
        ):
            raise ValueError("OI_UNSAFE_STORAGE_PATH")
        candidate = self.root.joinpath(*parsed.parts)
        if not candidate.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("OI_UNSAFE_STORAGE_PATH")
        for ancestor in (self.root, *self.root.parents):
            if ancestor.exists() and _link(ancestor):
                raise ValueError("OI_UNSAFE_STORAGE_LINK")
        cursor = self.root
        for part in parsed.parts:
            cursor = cursor / part
            if cursor.exists() and _link(cursor):
                raise ValueError("OI_UNSAFE_STORAGE_LINK")
        return candidate

    def check_quota(self, extra: int, database_bytes: int | None = None) -> None:
        if extra < 0:
            raise ValueError("OI_QUOTA_INVALID")
        if database_bytes is None:
            with self.engine.connect() as conn:
                database_bytes = int(
                    conn.scalar(text("SELECT pg_database_size(current_database())")) or 0
                )
        free = shutil.disk_usage(self.managed_root).free
        if (
            tree_bytes(self.root) + extra > self.quota
            or pressure(
                tree_bytes(self.managed_root) + database_bytes + extra,
                free - extra,
            )
            != "NORMAL"
        ):
            raise ValueError("OI_QUOTA_PAUSE")

    def _publish_file(self, relative: str, content: bytes) -> None:
        target = self._path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._path(relative)
        if target.exists():
            if target.stat().st_size != len(content) or target.read_bytes() != content:
                raise ValueError("OI_ARTIFACT_HASH_MISMATCH")
            return
        stage = self._path(relative + "." + uuid4().hex + ".stage")
        try:
            with stage.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            self._path(relative)
            # Atomic create-if-absent; never replace an accepted immutable file.
            try:
                os.link(stage, target)
            except FileExistsError:
                if target.stat().st_size != len(content) or target.read_bytes() != content:
                    raise ValueError("OI_ARTIFACT_HASH_MISMATCH") from None
        finally:
            if stage.exists():
                self._path(stage.relative_to(self.root).as_posix()).unlink()

    @staticmethod
    def _manifest(payload: str, digest: str) -> OIManifest:
        manifest = OIManifest.model_validate_json(payload)
        if manifest.content_hash() != digest:
            raise ValueError("OI_MANIFEST_HASH_MISMATCH")
        return manifest

    def verify(self, manifest: OIManifest) -> None:
        manifest = OIManifest.model_validate_json(manifest.canonical_bytes())
        raw = self._path(manifest.raw_relative_path)
        normalized = self._path(manifest.normalized_relative_path)
        if (
            not raw.is_file()
            or raw.stat().st_size != manifest.raw_bytes
            or _sha(raw.read_bytes()) != manifest.observation.raw_hash
        ):
            raise ValueError("OI_RAW_SOURCE_MISMATCH")
        if (
            not normalized.is_file()
            or normalized.stat().st_size != manifest.normalized_bytes
            or _sha(normalized.read_bytes()) != manifest.normalized_hash
            or normalized.read_bytes() != manifest.observation.canonical_bytes()
        ):
            raise ValueError("OI_NORMALIZED_HASH_MISMATCH")
        observation = manifest.observation
        parsed = parse_oi(
            raw.read_bytes(),
            symbol=observation.symbol,
            slot_at=observation.slot_at,
            request_sent_at=observation.request_sent_at,
            first_seen_at=observation.first_seen_at,
            received_at=observation.received_at,
            processed_at=observation.processed_at,
            code_revision=observation.code_revision,
            code_hash=observation.code_hash,
            review_receipt_hash=observation.review_receipt_hash,
        )
        if (
            parsed.raw_open_interest != observation.raw_open_interest
            or parsed.value != observation.value
            or parsed.provider_time_ms != observation.provider_time_ms
            or parsed.raw_hash != observation.raw_hash
        ):
            raise ValueError("OI_RAW_NORMALIZED_MISMATCH")

    def manifests(self) -> list[OIManifest]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT payload,manifest_hash FROM data_manifest "
                    "WHERE logical_key LIKE :p ORDER BY recorded_at,dataset_version LIMIT 10001"
                ),
                {"p": _PREFIX + "%"},
            ).all()
        if len(rows) > _MAX_RECORDS:
            raise ValueError("OI_REPORT_BUDGET_EXCEEDED")
        return [self._manifest(payload, digest) for payload, digest in rows]

    def publish(
        self,
        observation: OIObservation,
        raw: bytes,
        rights: OIRights | None = None,
        classification: DataUseClass = DataUseClass.ENGINEERING_ONLY,
        *,
        now: datetime | None = None,
    ) -> OIManifest:
        observation = OIObservation.model_validate_json(observation.canonical_bytes())
        rights = rights or accepted_oi_rights()
        rights = OIRights.model_validate_json(rights.canonical_bytes())
        publication_at = utc_time(now or datetime.now(UTC))
        require_oi_rights(rights, publication_at, self.review_authority)
        require_oi_rights(rights, observation.received_at, self.review_authority)
        expected_review = (
            self.review_authority.receipt_hash_at(observation.received_at)
            if self.review_authority is not None
            else None
        )
        if observation.review_receipt_hash != expected_review:
            raise ValueError("OI_REVIEW_RECEIPT_BINDING")
        if observation.available_at > publication_at:
            raise ValueError("OI_FUTURE_PUBLICATION")
        if not 1 <= len(raw) <= 4096 or _sha(raw) != observation.raw_hash:
            raise ValueError("OI_RAW_SOURCE_MISMATCH")
        if classification not in (DataUseClass.ENGINEERING_ONLY, DataUseClass.PERSONAL_RESEARCH):
            raise ValueError("OI_DATA_USE_DENIED")
        version = oi_dataset_version(observation)
        key = (
            f"{_PREFIX}{observation.symbol}:{observation.provider_time_ms}:"
            f"{observation.parser_version}"
        )
        with self.engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(:n)"), {"n": _LOCK})
            self._attest_dedicated_database(conn)
            existing = conn.execute(
                text("SELECT payload,manifest_hash FROM data_manifest WHERE dataset_version=:v"),
                {"v": version},
            ).first()
            if existing:
                manifest = self._manifest(existing[0], existing[1])
                self.verify(manifest)
                if manifest.observation.slot_at != observation.slot_at:
                    raise ValueError("OI_RECYCLED_IDENTITY")
                return manifest
            previous_row = conn.execute(
                text(
                    "SELECT payload,manifest_hash FROM data_manifest WHERE logical_key=:k "
                    "ORDER BY recorded_at,dataset_version LIMIT 1"
                ),
                {"k": key},
            ).first()
            previous = self._manifest(*previous_row) if previous_row else None
            reason = "IDENTITY_CONFLICT" if previous else None
            if previous is None:
                latest_row = conn.execute(
                    text(
                        "SELECT payload,manifest_hash FROM data_manifest "
                        "WHERE logical_key LIKE :p AND payload::jsonb->'observation'->>'symbol'=:s "
                        "AND payload::jsonb->'observation'->>'quality'='VALID' "
                        "ORDER BY recorded_at DESC,dataset_version DESC LIMIT 1"
                    ),
                    {"p": _PREFIX + "%", "s": observation.symbol},
                ).first()
                latest = self._manifest(*latest_row) if latest_row else None
                if latest and (
                    observation.slot_at <= latest.observation.slot_at
                    or observation.provider_time_ms <= latest.observation.provider_time_ms
                ):
                    previous = latest
                    reason = "OUT_OF_ORDER_OR_SLOT_REUSE"
            if previous:
                self.verify(previous)
                observation = OIObservation.model_validate(
                    observation.model_dump()
                    | {
                        "quality": "QUARANTINED",
                        "reason": reason,
                        "prior_raw_hash": previous.observation.raw_hash,
                    }
                )
                classification = DataUseClass.BLOCKED
            normalized = observation.canonical_bytes()
            normalized_hash = _sha(normalized)
            manifest = OIManifest(
                dataset_version=version,
                logical_key=key,
                observation=observation,
                rights=rights,
                raw_relative_path=f"oi/raw/{observation.raw_hash}.raw",
                normalized_relative_path=f"oi/normalized/{normalized_hash}.json",
                raw_bytes=len(raw),
                normalized_bytes=len(normalized),
                normalized_hash=normalized_hash,
                created_at=observation.available_at,
                processed_at=observation.available_at,
                supersedes=previous.dataset_version if previous else None,
                conflict_raw_hash=previous.observation.raw_hash if previous else None,
                classification=classification,
            )
            self.check_quota(
                2 * (len(raw) + len(normalized)) + 32768,
                int(conn.scalar(text("SELECT pg_database_size(current_database())")) or 0),
            )
            self._publish_file(manifest.raw_relative_path, raw)
            self._publish_file(manifest.normalized_relative_path, normalized)
            self.verify(manifest)
            conn.execute(
                text("INSERT INTO data_source_review VALUES (:h,:p) ON CONFLICT DO NOTHING"),
                {"h": rights.content_hash(), "p": rights.canonical_bytes().decode("ascii")},
            )
            if self.review_authority is not None:
                # Constructor-verified exact external acceptance digests, never a
                # generated renewal or START. Future-dated reviews are not adopted.
                for receipt in self.review_authority.chain:
                    if receipt.accepted_at <= publication_at:
                        conn.execute(
                            text(
                                "INSERT INTO data_source_review VALUES (:h,:p) "
                                "ON CONFLICT DO NOTHING"
                            ),
                            {
                                "h": receipt.content_hash(),
                                "p": receipt.canonical_bytes().decode("ascii"),
                            },
                        )
            conn.execute(
                text("INSERT INTO data_manifest VALUES (:v,:k,:s,:t,:prior,:h,:p)"),
                {
                    "v": version,
                    "k": key,
                    "s": observation.raw_hash,
                    "t": manifest.created_at,
                    "prior": manifest.supersedes,
                    "h": manifest.content_hash(),
                    "p": manifest.canonical_bytes().decode("ascii"),
                },
            )
            if observation.quality == "VALID":
                conn.execute(
                    text("INSERT INTO data_checkpoint VALUES (:k,:n,:v,:t) ON CONFLICT DO NOTHING"),
                    {
                        "k": f"DS-04-A1:{observation.symbol}",
                        "n": observation.slot_at + timedelta(hours=1),
                        "v": version,
                        "t": manifest.created_at,
                    },
                )
        return manifest

    @contextmanager
    def collection_lease(self) -> Iterator[bool]:
        """Source-global immediate lease; no queue, no persistent activation state."""
        with self.engine.connect() as conn:
            acquired = bool(conn.scalar(text("SELECT pg_try_advisory_lock(:n)"), {"n": _LOCK + 1}))
            try:
                yield acquired
            finally:
                if acquired:
                    conn.execute(text("SELECT pg_advisory_unlock(:n)"), {"n": _LOCK + 1})

    def checkpoint(self, symbol: str) -> OIManifest | None:
        if symbol not in ("BTCUSDT", "ETHUSDT"):
            raise ValueError("OI_SYMBOL")
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT c.next_open,m.payload,m.manifest_hash FROM data_checkpoint c "
                    "JOIN data_manifest m USING(dataset_version) WHERE c.feed_key=:k "
                    "ORDER BY c.next_open DESC LIMIT 1"
                ),
                {"k": f"DS-04-A1:{symbol}"},
            ).first()
        if row is None:
            return None
        manifest = self._manifest(row[1], row[2])
        if (
            manifest.observation.symbol != symbol
            or row[0] != manifest.observation.slot_at + timedelta(hours=1)
            or manifest.observation.quality != "VALID"
        ):
            raise ValueError("OI_CHECKPOINT_MISMATCH")
        self.verify(manifest)
        return manifest

    def read_as_of(self, manifest: OIManifest, as_of: datetime) -> OIObservation:
        from auvexo_alpha.domain.open_interest import oi_classify_manifest

        self.verify(manifest)
        if (
            oi_classify_manifest(manifest, as_of, review_authority=self.review_authority)
            == DataUseClass.BLOCKED
        ):
            raise ValueError("OI_RESEARCH_ADMISSION_BLOCKED")
        with self.engine.connect() as conn:
            registered = conn.scalar(
                text("SELECT manifest_hash FROM data_manifest WHERE dataset_version=:v"),
                {"v": manifest.dataset_version},
            )
            conflict = conn.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM data_manifest WHERE logical_key=:k "
                    "AND payload::jsonb->'observation'->>'quality'='QUARANTINED')"
                ),
                {"k": manifest.logical_key},
            )
        if registered != manifest.content_hash() or conflict:
            raise ValueError("OI_UNREGISTERED_OR_CONFLICTED_MANIFEST")
        return manifest.observation

    def quarantine(self, raw: bytes, now: datetime, reason: str) -> str:
        if not 1 <= len(raw) <= 4096 or reason not in (
            "SCHEMA",
            "PARSER_REJECTED",
            "SOURCE_REJECTED",
            "RIGHTS_REJECTED",
        ):
            raise ValueError("OI_QUARANTINE_INPUT")
        digest = _sha(raw)
        with self.engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(:n)"), {"n": _LOCK})
            self.check_quota(
                len(raw) * 2 + 16384,
                int(conn.scalar(text("SELECT pg_database_size(current_database())")) or 0),
            )
            self._publish_file(f"oi/quarantine/{digest}.raw", raw)
            identity = f"oi-quarantine:{digest}:{reason}"
            conn.execute(
                text(
                    "INSERT INTO data_event(event_id,feed_key,observed_at,payload) "
                    "VALUES (:i,:k,:t,:p) ON CONFLICT DO NOTHING"
                ),
                {
                    "i": identity,
                    "k": "DS-04-A1:quarantine",
                    "t": utc_time(now),
                    "p": _encoded({"source_id": "DS-04-A1", "raw_hash": digest, "reason": reason}),
                },
            )
        return digest

    def reconcile(self) -> dict[str, int]:
        manifests = self.manifests()
        accepted: set[Path] = set()
        for manifest in manifests:
            self.verify(manifest)
            accepted.add(self._path(manifest.raw_relative_path))
            accepted.add(self._path(manifest.normalized_relative_path))
        # Strict scan rejects all reparse points before traversal/read or classification.
        tree_bytes(self.root)
        files = [p for p in self.root.rglob("*") if p.is_file()]
        artifact_files = [
            p
            for p in files
            if p.relative_to(self.root).as_posix().startswith(("oi/raw/", "oi/normalized/"))
            and not p.name.endswith(".stage")
        ]
        return {
            "verified_manifests": len(manifests),
            "unpublished_orphans": sum(p not in accepted for p in artifact_files),
            "staging_files": sum(p.name.endswith(".stage") for p in files),
        }

    def cleanup_staging(self) -> int:
        count = 0
        with self.engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(:n)"), {"n": _LOCK})
            tree_bytes(self.root)
            for stage in self.root.rglob("*.stage"):
                self._path(stage.relative_to(self.root).as_posix()).unlink()
                count += 1
        return count

    def _budget_checkpoint(self) -> tuple[int, str | None, OIBudgetState | None]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT event_id,payload FROM data_event WHERE feed_key=:f "
                    "ORDER BY (payload::jsonb->>'revision')::bigint DESC LIMIT 1"
                ),
                {"f": _BUDGET_FEED},
            ).all()
        if not rows:
            return 0, None, None
        record = OITransportCheckpoint.model_validate_json(rows[0][1])
        if rows[0][0] != "oi-budget:" + record.content_hash():
            raise ValueError("OI_BUDGET_HASH_MISMATCH")
        return record.revision, record.content_hash(), record.state

    def load_transport_state(self, now: datetime) -> OIBudgetState:
        now = utc_time(now)
        _, _, state = self._budget_checkpoint()
        if state is not None:
            if state.pending_attempt:
                raise ValueError("OI_TRANSPORT_OUTCOME_REVIEW_REQUIRED")
            if state.last_attempt_at is not None and state.last_attempt_at > now:
                raise ValueError("OI_CLOCK_REWIND")
            return state
        return OIBudgetState(
            hour_started_at=now.replace(minute=0, second=0, microsecond=0),
            day_started_at=now.replace(hour=0, minute=0, second=0, microsecond=0),
            hour_attempts=0,
            day_attempts=0,
        )

    def save_transport_state(self, state: OIBudgetState) -> None:
        state = OIBudgetState.model_validate_json(state.canonical_bytes())
        if state.last_attempt_at is None:
            raise ValueError("OI_BUDGET_ATTEMPT_REQUIRED")
        with self.engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(:n)"), {"n": _LOCK})
            # Use this transaction's connection: a second cached HTTP instance must
            # not commit a count based on the same stale snapshot.
            row = conn.execute(
                text(
                    "SELECT event_id,payload FROM data_event WHERE feed_key=:f "
                    "ORDER BY (payload::jsonb->>'revision')::bigint DESC LIMIT 1"
                ),
                {"f": _BUDGET_FEED},
            ).first()
            previous = OITransportCheckpoint.model_validate_json(row[1]) if row else None
            if previous and row is not None and row[0] != "oi-budget:" + previous.content_hash():
                raise ValueError("OI_BUDGET_HASH_MISMATCH")
            prior = previous.state if previous else None
            completion = bool(
                prior is not None
                and prior.pending_attempt
                and not state.pending_attempt
                and state.last_attempt_at == prior.last_attempt_at
                and state.hour_started_at == prior.hour_started_at
                and state.day_started_at == prior.day_started_at
                and state.hour_attempts == prior.hour_attempts
                and state.day_attempts == prior.day_attempts
            )
            if not completion:
                if not state.pending_attempt or (prior is not None and prior.pending_attempt):
                    raise ValueError("OI_TRANSPORT_OUTCOME_REVIEW_REQUIRED")
                hour = state.last_attempt_at.replace(minute=0, second=0, microsecond=0)
                day = state.last_attempt_at.replace(hour=0, minute=0, second=0, microsecond=0)
                expected_hour = (
                    prior.hour_attempts + 1 if prior and hour == prior.hour_started_at else 1
                )
                expected_day = (
                    prior.day_attempts + 1 if prior and day == prior.day_started_at else 1
                )
                if (
                    state.hour_started_at != hour
                    or state.day_started_at != day
                    or state.hour_attempts != expected_hour
                    or state.day_attempts != expected_day
                    or (
                        prior is not None
                        and prior.last_attempt_at is not None
                        and state.last_attempt_at - prior.last_attempt_at < timedelta(seconds=2)
                    )
                    or (
                        prior is not None
                        and prior.blocked_until is not None
                        and state.last_attempt_at < prior.blocked_until
                    )
                ):
                    raise ValueError("OI_BUDGET_CONCURRENT_OR_INVALID_STATE")
            if (
                prior
                and prior.blocked_until is not None
                and (state.blocked_until is None or state.blocked_until < prior.blocked_until)
            ):
                raise ValueError("OI_COOLDOWN_REWIND")
            record = OITransportCheckpoint(
                revision=previous.revision + 1 if previous else 1,
                previous_hash=previous.content_hash() if previous else None,
                state=state,
            )
            self.check_quota(
                len(record.canonical_bytes()) + 16384,
                int(conn.scalar(text("SELECT pg_database_size(current_database())")) or 0),
            )
            conn.execute(
                text(
                    "INSERT INTO data_event(event_id,feed_key,observed_at,blocked_until,payload) "
                    "VALUES (:i,:f,:t,:b,:p)"
                ),
                {
                    "i": "oi-budget:" + record.content_hash(),
                    "f": _BUDGET_FEED,
                    "t": state.last_attempt_at,
                    "b": state.blocked_until,
                    "p": record.canonical_bytes().decode("ascii"),
                },
            )

    def _append_ledger(
        self,
        kind: Literal["STUDY", "FEATURE", "FORECAST", "SCORE"],
        identity: str,
        record: Contract,
        recorded_at: datetime,
        required_hashes: tuple[str, ...] = (),
        forecast_hash: str | None = None,
    ) -> str:
        content = record.canonical_bytes()
        if len(content) > 12000:
            raise ValueError("OI_LEDGER_BUDGET")
        digest = record.content_hash()
        envelope = OILedgerEntry(
            kind=kind,
            identity_hash=_sha(identity.encode("ascii")),
            record_hash=digest,
            record_json=content.decode("ascii"),
        )
        event_id = f"oi-ledger:{kind}:" + envelope.identity_hash
        with self.engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(:n)"), {"n": _LOCK})
            old = conn.scalar(
                text("SELECT payload FROM data_event WHERE event_id=:i"), {"i": event_id}
            )
            if old is not None:
                stored = OILedgerEntry.model_validate_json(old)
                if stored != envelope:
                    raise ValueError("OI_IMMUTABLE_LEDGER_CONFLICT")
                return digest
            if kind == "FORECAST":
                from auvexo_alpha.application.oi_research import OIForecast

                forecast = OIForecast.model_validate_json(content)
                if conn.scalar(
                    text(
                        "SELECT EXISTS(SELECT 1 FROM data_manifest WHERE logical_key LIKE :p "
                        "AND payload::jsonb->'observation'->>'symbol'=:s "
                        "AND (payload::jsonb->'observation'->>'slot_at')::timestamptz>:slot)"
                    ),
                    {"p": _PREFIX + "%", "s": forecast.symbol, "slot": forecast.slot_at},
                ):
                    # A backdated DTO is not proof that prediction existed before
                    # its target. Publication and this check share the same lock.
                    raise ValueError("OI_FORECAST_AFTER_FUTURE_FACT")
            for manifest_hash in required_hashes:
                row = conn.execute(
                    text("SELECT payload,manifest_hash FROM data_manifest WHERE manifest_hash=:h"),
                    {"h": manifest_hash},
                ).first()
                if row is None:
                    raise ValueError("OI_LEDGER_PARENT_MISSING")
                manifest = self._manifest(*row)
                self.read_as_of(manifest, recorded_at)
            if forecast_hash is not None:
                rows = conn.execute(
                    text(
                        "SELECT payload FROM data_event WHERE feed_key=:f "
                        "AND payload::jsonb->>'record_hash'=:h LIMIT 2"
                    ),
                    {"f": "DS-04-A1:ledger:FORECAST", "h": forecast_hash},
                ).all()
                if len(rows) != 1:
                    raise ValueError("OI_FORECAST_MISSING")
            self.check_quota(
                len(envelope.canonical_bytes()) + 16384,
                int(conn.scalar(text("SELECT pg_database_size(current_database())")) or 0),
            )
            conn.execute(
                text(
                    "INSERT INTO data_event(event_id,feed_key,observed_at,payload) "
                    "VALUES (:i,:f,:t,:p)"
                ),
                {
                    "i": event_id,
                    "f": "DS-04-A1:ledger:" + kind,
                    "t": utc_time(recorded_at),
                    "p": envelope.canonical_bytes().decode("ascii"),
                },
            )
        return digest

    def _record_by_hash(self, kind: str, digest: str) -> str:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT payload FROM data_event WHERE feed_key=:f "
                    "AND payload::jsonb->>'record_hash'=:h LIMIT 2"
                ),
                {"f": "DS-04-A1:ledger:" + kind, "h": digest},
            ).all()
        if len(rows) != 1:
            raise ValueError("OI_LEDGER_RECORD_MISSING")
        envelope = OILedgerEntry.model_validate_json(rows[0][0])
        if envelope.record_hash != digest or _sha(envelope.record_json.encode("ascii")) != digest:
            raise ValueError("OI_LEDGER_HASH_MISMATCH")
        return envelope.record_json

    def manifest_by_hash(self, digest: str) -> OIManifest:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT payload,manifest_hash FROM data_manifest WHERE manifest_hash=:h"),
                {"h": digest},
            ).first()
        if row is None:
            raise ValueError("OI_LEDGER_PARENT_MISSING")
        manifest = self._manifest(*row)
        self.verify(manifest)
        return manifest

    def append_study(self, study: OIStudyWindow) -> str:
        """Append pure research-window metadata; never an owner activation/START row."""
        from auvexo_alpha.application.oi_research import OIStudyWindow

        checked = OIStudyWindow.model_validate_json(study.canonical_bytes())
        return self._append_ledger(
            "STUDY",
            checked.study_id,
            checked,
            checked.owner_start_at,
        )

    def append_feature(self, feature: OIFeatureSnapshot) -> str:
        from auvexo_alpha.application.oi_research import OIFeatureSnapshot, compute_oi_features

        checked = OIFeatureSnapshot.model_validate_json(feature.canonical_bytes())
        parents = tuple(self.manifest_by_hash(h) for h in checked.input_manifest_hashes)
        expected = compute_oi_features(
            parents[-1],
            parents[0] if len(parents) == 2 else None,
            at=checked.computed_at,
            review_authority=self.review_authority,
        )
        if expected.canonical_bytes() != checked.canonical_bytes():
            raise ValueError("OI_LEDGER_FEATURE_BINDING")
        return self._append_ledger(
            "FEATURE",
            f"{checked.symbol}:{checked.slot_at.isoformat()}",
            checked,
            checked.computed_at,
            checked.input_manifest_hashes,
        )

    def append_prediction(self, forecast: OIForecast) -> str:
        from auvexo_alpha.application.oi_research import (
            OIFeatureSnapshot,
            OIForecast,
            OIStudyWindow,
            create_forecast,
        )

        checked = OIForecast.model_validate_json(forecast.canonical_bytes())
        study = OIStudyWindow.model_validate_json(self._record_by_hash("STUDY", checked.study_hash))
        feature = OIFeatureSnapshot.model_validate_json(
            self._record_by_hash("FEATURE", checked.feature_hash)
        )
        expected = create_forecast(study, feature, created_at=checked.created_at)
        if expected.canonical_bytes() != checked.canonical_bytes():
            raise ValueError("OI_LEDGER_FORECAST_BINDING")
        return self._append_ledger(
            "FORECAST",
            checked.logical_key,
            checked,
            checked.created_at,
            checked.input_manifest_hashes,
        )

    def append_score(self, score: OIPairScore) -> str:
        from auvexo_alpha.application.oi_research import (
            OIForecast,
            OIPairScore,
            OIStudyWindow,
            score_forecast,
        )

        checked = OIPairScore.model_validate_json(score.canonical_bytes())
        forecast = OIForecast.model_validate_json(
            self._record_by_hash("FORECAST", checked.forecast_hash)
        )
        study = OIStudyWindow.model_validate_json(self._record_by_hash("STUDY", checked.study_hash))
        current = self.manifest_by_hash(forecast.current_manifest_hash)
        target = (
            self.manifest_by_hash(checked.target_manifest_hash)
            if checked.target_manifest_hash
            else None
        )
        expected = score_forecast(
            study,
            forecast,
            current,
            target,
            scored_at=checked.scored_at,
            review_authority=self.review_authority,
        )
        if expected.canonical_bytes() != checked.canonical_bytes():
            raise ValueError("OI_LEDGER_SCORE_BINDING")
        parents = (checked.target_manifest_hash,) if checked.target_manifest_hash else ()
        return self._append_ledger(
            "SCORE",
            checked.forecast_hash,
            checked,
            checked.scored_at,
            parents,
            checked.forecast_hash,
        )

    def ledger(self, kind: Literal["STUDY", "FEATURE", "FORECAST", "SCORE"]) -> list[OILedgerEntry]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT payload FROM data_event WHERE feed_key=:f "
                    "ORDER BY observed_at,event_id LIMIT 10001"
                ),
                {"f": "DS-04-A1:ledger:" + kind},
            ).all()
        if len(rows) > _MAX_RECORDS:
            raise ValueError("OI_REPORT_BUDGET_EXCEEDED")
        result = [OILedgerEntry.model_validate_json(row[0]) for row in rows]
        for entry in result:
            if _sha(entry.record_json.encode("ascii")) != entry.record_hash:
                raise ValueError("OI_LEDGER_HASH_MISMATCH")
        return result

    def features(self) -> tuple[OIFeatureSnapshot, ...]:
        from auvexo_alpha.application.oi_research import OIFeatureSnapshot

        return tuple(
            OIFeatureSnapshot.model_validate_json(entry.record_json)
            for entry in self.ledger("FEATURE")
        )

    def forecasts(self, study_hash: str | None = None) -> tuple[OIForecast, ...]:
        from auvexo_alpha.application.oi_research import OIForecast

        records = tuple(
            OIForecast.model_validate_json(entry.record_json) for entry in self.ledger("FORECAST")
        )
        return tuple(
            record for record in records if study_hash is None or record.study_hash == study_hash
        )

    def scores(self, study_hash: str | None = None) -> tuple[OIPairScore, ...]:
        from auvexo_alpha.application.oi_research import OIPairScore

        records = tuple(
            OIPairScore.model_validate_json(entry.record_json) for entry in self.ledger("SCORE")
        )
        return tuple(
            record for record in records if study_hash is None or record.study_hash == study_hash
        )


class OITransportCheckpoint(Contract):
    revision: Annotated[int, Field(ge=1, le=1_000_000_000)]
    previous_hash: Digest | None
    state: OIBudgetState


class OILedgerEntry(Contract):
    kind: Literal["STUDY", "FEATURE", "FORECAST", "SCORE"]
    identity_hash: Digest
    record_hash: Digest
    record_json: Annotated[str, Field(min_length=1, max_length=12000)]
