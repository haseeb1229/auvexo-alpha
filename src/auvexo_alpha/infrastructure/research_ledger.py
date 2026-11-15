"""Serialized append-only research metadata and bounded immutable local artifacts.

The database enforces the holdout gate: selection freezing, holdout opening, read
receipts and completion run only through reviewed SECURITY DEFINER functions, and the
research role cannot write a HOLDOUT_OPEN event itself.
"""

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import Connection, Engine, text

from auvexo_alpha.application.research_simulator import artifact_bytes
from auvexo_alpha.domain.market_data import Candle
from auvexo_alpha.domain.research import (
    DataUseClass,
    StrategyConfig,
    StudyManifest,
    TrialIdentity,
    bars_digest,
    classify_manifest,
)
from auvexo_alpha.infrastructure.data_store import file_hash, pressure, tree_bytes

SELECTION_TRIAL = "selection.pre_holdout"
PACKAGE = Path(__file__).resolve().parents[1]
LOCK_FILE = PACKAGE.parents[1] / "uv.lock"
# Every project module the research path executes (the worker's import closure).
# A test proves this list equals that closure, so a study cannot run unhashed code.
RESEARCH_MODULES = (
    "__init__.py",
    "application/__init__.py",
    "application/data_quality.py",
    "application/data_schedule.py",
    "application/research_metrics.py",
    "application/research_simulator.py",
    "application/research_study.py",
    "domain/__init__.py",
    "domain/contracts.py",
    "domain/market_data.py",
    "domain/research.py",
    "domain/research_gaps.py",
    "domain/source_reviews.py",
    "infrastructure/__init__.py",
    "infrastructure/data_store.py",
    "infrastructure/research_data.py",
    "infrastructure/research_ledger.py",
    "infrastructure/research_worker.py",
    "infrastructure/spot_parser.py",
)
HoldoutState = Literal["SEALED", "OPEN", "COMPLETE"]


@cache
def research_code_hash() -> str:
    """Hash of the research code actually importable now, path-bound and order-fixed."""
    digest = hashlib.sha256()
    for relative in RESEARCH_MODULES:
        digest.update(relative.encode("ascii") + b":" + (PACKAGE / relative).read_bytes() + b"\n")
    return digest.hexdigest()


def dependency_lock_hash() -> str:
    """Hash of the exact dependency lock the running checkout was installed from."""
    if not LOCK_FILE.is_file():
        raise ValueError("DEPENDENCY_LOCK_UNAVAILABLE")
    return file_hash(LOCK_FILE)


def frozen_selection(configs: tuple[StrategyConfig, ...], artifact: bytes) -> tuple[str, ...]:
    """The recorded pre-holdout choice: exactly one registered config per preregistered family."""
    recorded = json.loads(artifact)
    chosen = recorded.get("selected") if isinstance(recorded, dict) else None
    families = {c.content_hash(): c.family for c in configs}
    if (
        not isinstance(chosen, list)
        or not chosen
        or any(not isinstance(item, str) or item not in families for item in chosen)
    ):
        raise ValueError("UNREGISTERED_SELECTION")
    if sorted(families[item] for item in chosen) != sorted(set(families.values())):
        raise ValueError("SELECTION_NOT_ONE_CONFIG_PER_FAMILY")
    return tuple(chosen)


@dataclass(frozen=True)
class AuthorizedRead:
    """A read the database authorized and logged before any bar was served."""

    study: StudyManifest
    receipt_id: str
    phase: str
    start: datetime
    end: datetime


class ResearchLedger:
    def __init__(
        self, engine: Engine, root: Path, managed_root: Path, quota: int = 512 * 1024 * 1024
    ) -> None:
        self.engine = engine
        self.root, self.managed = root.resolve(), managed_root.resolve()
        if not self.root.is_relative_to(self.managed) or not 1 <= quota <= 2_000_000_000:
            raise ValueError("RESEARCH_STORAGE_BOUNDARY")
        self.quota = quota
        self.root.mkdir(exist_ok=True, parents=True)

    @staticmethod
    def lock(conn: Connection, study_id: str) -> None:
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:id,20801404))"), {"id": study_id}
        )

    @staticmethod
    def require_identity(conn: Connection, study: StudyManifest) -> None:
        """The running code, the lock and every stored input must be what was registered."""
        if study.code_hash != research_code_hash():
            raise ValueError("RESEARCH_CODE_HASH_MISMATCH")
        if study.dependency_hash != dependency_lock_hash():
            raise ValueError("DEPENDENCY_LOCK_HASH_MISMATCH")
        stored: dict[str, str] = {
            row[0]: row[1]
            for row in conn.execute(
                text(
                    "SELECT dataset_version,manifest_hash FROM data_manifest "
                    "WHERE dataset_version = ANY(:v)"
                ),
                {"v": [item.manifest.dataset_version for item in study.inputs]},
            ).all()
        }
        for item in study.inputs:
            if stored.get(item.manifest.dataset_version) != item.manifest_hash:
                raise ValueError("STUDY_INPUT_NOT_IN_STORE")

    def register(self, study: StudyManifest) -> None:
        study = StudyManifest.model_validate_json(study.canonical_bytes())
        if study.registered_at > datetime.now(UTC):
            raise ValueError("FUTURE_PREREGISTRATION")
        with self.engine.begin() as conn:
            self.lock(conn, study.study_id)
            conn.execute(text("SELECT pg_advisory_xact_lock(20801405)"))
            self.require_identity(conn, study)
            split = study.split
            # Development reads span train through validation, including the gap.
            if self.sealed_elsewhere(conn, study, split.train_start, split.validation_end):
                raise ValueError("DEVELOPMENT_OVERLAPS_SEALED_HOLDOUT_OF_ANOTHER_STUDY")
            # Bars any registered study may read as development can never be a fresh holdout.
            exposed = conn.scalar(
                text(
                    "SELECT count(*) FROM research_study s WHERE s.study_id<>:id "
                    "AND s.payload::jsonb->>'instrument'=:instrument "
                    "AND (s.payload::jsonb #>> '{split,train_start}')::timestamptz < :end "
                    "AND :start < (s.payload::jsonb #>> '{split,validation_end}')::timestamptz"
                ),
                {
                    "id": study.study_id,
                    "instrument": study.instrument,
                    "start": split.oos_start,
                    "end": split.oos_end,
                },
            )
            if exposed:
                raise ValueError("HOLDOUT_OVERLAPS_DEVELOPMENT_OF_ANOTHER_STUDY")
            conn.execute(
                text("INSERT INTO research_study VALUES (:id,:hash,:payload,:at)"),
                {
                    "id": study.study_id,
                    "hash": study.content_hash(),
                    "payload": study.canonical_bytes().decode(),
                    "at": study.registered_at,
                },
            )
            for index, config in enumerate(study.configs):
                conn.execute(
                    text("INSERT INTO research_study_config VALUES (:id,:i,:h,:f)"),
                    {
                        "id": study.study_id,
                        "i": index,
                        "h": config.content_hash(),
                        "f": config.family,
                    },
                )

    def study(self, study_id: str, conn: Connection | None = None) -> StudyManifest:
        if conn is None:
            with self.engine.connect() as own:
                return self.study(study_id, own)
        row = conn.execute(
            text("SELECT manifest_hash,payload FROM research_study WHERE study_id=:id"),
            {"id": study_id},
        ).one()
        result = StudyManifest.model_validate_json(row[1])
        if result.content_hash() != row[0]:
            raise ValueError("CORRUPT_STUDY")
        return result

    def sealed_elsewhere(
        self, conn: Connection, study: StudyManifest, start: datetime, end: datetime
    ) -> bool:
        """Whether [start,end) touches another study's still-unopened holdout calendar."""
        return bool(
            conn.scalar(
                text(
                    "SELECT count(*) FROM research_study s WHERE s.study_id<>:id "
                    "AND s.payload::jsonb->>'instrument'=:instrument "
                    "AND (s.payload::jsonb #>> '{split,oos_start}')::timestamptz < :end "
                    "AND :start < (s.payload::jsonb #>> '{split,oos_end}')::timestamptz "
                    "AND NOT EXISTS (SELECT 1 FROM research_event e "
                    "WHERE e.study_id=s.study_id AND e.kind='HOLDOUT_OPEN')"
                ),
                {
                    "id": study.study_id,
                    "instrument": study.instrument,
                    "start": start,
                    "end": end,
                },
            )
        )

    def selected(self, conn: Connection, study_id: str) -> tuple[str, ...] | None:
        payload = conn.scalar(
            text("SELECT payload FROM research_event WHERE study_id=:id"), {"id": study_id}
        )
        return tuple(json.loads(payload)["selected"]) if payload is not None else None

    def holdout_state(self, study_id: str) -> HoldoutState:
        with self.engine.connect() as conn:
            state = conn.scalar(text("SELECT research_holdout_state(:id)"), {"id": study_id})
        states: dict[object, HoldoutState] = {
            "SEALED": "SEALED",
            "OPEN": "OPEN",
            "COMPLETE": "COMPLETE",
        }
        if state not in states:
            raise ValueError("UNKNOWN_HOLDOUT_STATE")
        return states[state]

    @staticmethod
    def gate(conn: Connection, statement: str, values: dict[str, object], passed: str) -> None:
        """Run one database gate function; any other outcome is a refusal with its code."""
        outcome = conn.scalar(text(statement), values)
        if outcome != passed:
            raise ValueError(outcome if isinstance(outcome, str) else "RESEARCH_GATE_FAILED")

    def open_holdout(self, study_id: str, selected: tuple[str, ...]) -> None:
        """Consume the holdout atomically in the database, for the frozen selection only."""
        if not selected:
            raise ValueError("UNREGISTERED_SELECTION")
        with self.engine.begin() as conn:
            self.lock(conn, study_id)
            frozen = conn.scalar(
                text("SELECT selected FROM research_selection WHERE study_id=:id"),
                {"id": study_id},
            )
            if frozen is not None:
                # The frozen database row and its retained artifact must still agree.
                study = self.study(study_id, conn)
                recorded = frozen_selection(
                    study.configs, self.read_trial(study_id, SELECTION_TRIAL, conn)
                )
                if list(recorded) != frozen:
                    raise ValueError("CORRUPT_RESEARCH_ARTIFACT")
            self.gate(
                conn,
                "SELECT research_open_holdout(:id,CAST(:selected AS jsonb),:event)",
                {"id": study_id, "selected": json.dumps(list(selected)), "event": str(uuid4())},
                "OPENED",
            )

    def complete_holdout(self, study_id: str, trials: tuple[str, ...]) -> None:
        with self.engine.begin() as conn:
            self.gate(
                conn,
                "SELECT research_complete_holdout(:id,CAST(:trials AS jsonb))",
                {"id": study_id, "trials": json.dumps(list(trials))},
                "COMPLETED",
            )

    def authorize_read(
        self, study_id: str, phase: str, start: datetime, end: datetime
    ) -> AuthorizedRead:
        """The database checks and logs the read (including any post-consumption OOS read)."""
        receipt = uuid4().hex + uuid4().hex
        with self.engine.begin() as conn:
            self.lock(conn, study_id)
            self.gate(
                conn,
                "SELECT research_authorize_read(:id,:phase,:start,:end,:receipt)",
                {"id": study_id, "phase": phase, "start": start, "end": end, "receipt": receipt},
                "AUTHORIZED",
            )
            study = self.study(study_id, conn)
            self.require_identity(conn, study)
            for item in study.inputs:
                current = classify_manifest(
                    item.manifest,
                    datetime.now(UTC),
                    item.availability,
                    item.intended_use,
                    study.instrument,
                    outages=item.outages,
                )
                if current.classification != DataUseClass.PERSONAL_RESEARCH:
                    raise ValueError("CURRENT_RESEARCH_RIGHTS_BLOCKED")
            return AuthorizedRead(study, receipt, phase, start, end)

    def bind_read(self, read: AuthorizedRead, bars: list[Candle]) -> str:
        """Record the digest of the bars actually served under one read receipt."""
        if not bars or any(not read.start <= b.open_at and b.end_at <= read.end for b in bars):
            raise ValueError("READ_DIGEST_OUTSIDE_RECEIPT")
        digest = bars_digest(bars)
        with self.engine.begin() as conn:
            conn.execute(
                text("INSERT INTO research_read_digest VALUES (:r,:d,:n,:t)"),
                {"r": read.receipt_id, "d": digest, "n": len(bars), "t": datetime.now(UTC)},
            )
        return digest

    def check_phase(self, conn: Connection, study: StudyManifest, phase: str) -> None:
        if phase not in ("TRAIN", "VALIDATION", "OOS", "WALK_FORWARD"):
            raise ValueError("UNKNOWN_RESEARCH_PHASE")
        selected = self.selected(conn, study.study_id)
        if (phase == "OOS") != (selected is not None):
            raise ValueError("HOLDOUT_NOT_OPEN_OR_DEVELOPMENT_ALREADY_CONSUMED")

    @staticmethod
    def check_trial_identity(
        conn: Connection,
        study: StudyManifest,
        phase: str,
        config_hash: str,
        artifact: dict[str, object],
    ) -> None:
        """A trial is accepted only if its artifact proves what ran: config, costs, policy,
        code, lock and the digests of reads the database authorized for this study.
        """
        recorded = artifact.get("identity")
        if not isinstance(recorded, dict):
            raise ValueError("TRIAL_IDENTITY_MISMATCH")
        try:
            identity = TrialIdentity.model_validate_json(json.dumps(recorded))
        except ValidationError as error:
            raise ValueError("TRIAL_IDENTITY_MISMATCH") from error
        result = artifact.get("result")
        stressed = {
            study.costs.model_copy(update={"multiplier": m}) for m in study.stress_multipliers
        }
        if (
            identity.config_hash != config_hash
            or identity.config not in study.configs
            or identity.study_hash != study.content_hash()
            or identity.code_hash != study.code_hash
            or identity.code_hash != research_code_hash()
            or identity.dependency_hash != study.dependency_hash
            or identity.availability != study.availability
            or identity.cost_model not in stressed
            or (isinstance(result, dict) and result.get("config_hash") != config_hash)
        ):
            raise ValueError("TRIAL_IDENTITY_MISMATCH")
        reads: dict[str, str] = {
            row[0]: row[1]
            for row in conn.execute(
                text(
                    "SELECT d.bars_digest,r.phase FROM research_read_digest d "
                    "JOIN research_read_receipt r USING(receipt_id) "
                    "WHERE r.study_id=:id AND d.bars_digest = ANY(:digests)"
                ),
                {"id": study.study_id, "digests": list(identity.reads)},
            ).all()
        }
        if set(reads) != set(identity.reads) or phase not in reads.values():
            raise ValueError("TRIAL_READ_NOT_AUTHORIZED")

    def record(
        self,
        study_id: str,
        trial_id: str,
        phase: str,
        config_hash: str,
        result: bytes,
        resume: bool = False,
    ) -> str:
        """Append one verified trial. With resume, an identical existing trial is accepted
        as already done; any difference refuses. Nothing is ever rewritten.
        """
        if (
            not re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", trial_id)
            or not 1 <= len(result) <= 64 * 1024 * 1024
        ):
            raise ValueError("TRIAL_OR_ARTIFACT_BUDGET")
        # Content is structured JSON, not arbitrary executable data/pickle.
        artifact = json.loads(result)
        if not isinstance(artifact, dict):
            raise ValueError("TRIAL_IDENTITY_MISMATCH")
        digest = hashlib.sha256(result).hexdigest()
        with self.engine.begin() as conn:
            self.lock(conn, study_id)
            conn.execute(text("SELECT pg_advisory_xact_lock(20801405)"))
            study = self.study(study_id, conn)
            if resume:
                existing = conn.execute(
                    text(
                        "SELECT phase,config_hash,artifact_hash FROM research_trial "
                        "WHERE study_id=:id AND trial_id=:trial"
                    ),
                    {"id": study_id, "trial": trial_id},
                ).first()
                if existing is not None:
                    if tuple(existing) != (phase, config_hash, digest):
                        raise ValueError("HOLDOUT_RESUME_MISMATCH")
                    self.read_trial(study_id, trial_id, conn)
                    return digest
            self.check_phase(conn, study, phase)
            permitted = (
                self.selected(conn, study_id)
                if phase == "OOS"
                else (tuple(c.content_hash() for c in study.configs))
            )
            if config_hash not in (permitted or ()):
                raise ValueError("UNREGISTERED_OR_POST_HOLDOUT_CONFIG")
            self.check_trial_identity(conn, study, phase, config_hash, artifact)
            selection = (
                frozen_selection(study.configs, result)
                if trial_id == SELECTION_TRIAL and phase == "VALIDATION"
                else None
            )
            count = conn.scalar(
                text("SELECT count(*) FROM research_trial WHERE study_id=:id"), {"id": study_id}
            )
            if count >= study.trial_budget:
                raise ValueError("TRIAL_BUDGET_EXHAUSTED")
            if (
                tree_bytes(self.root) + len(result) > self.quota
                or pressure(
                    tree_bytes(self.managed, True),
                    shutil.disk_usage(self.managed).free - len(result),
                )
                != "NORMAL"
            ):
                raise ValueError("RESEARCH_STORAGE_PRESSURE")
            target = self.path(digest)
            if target.exists():
                if file_hash(target) != digest:
                    raise ValueError("CORRUPT_RESEARCH_ARTIFACT")
            else:
                stage = self.root / (str(uuid4()) + ".stage")
                with stage.open("xb") as stream:
                    stream.write(result)
                    stream.flush()
                    os.fsync(stream.fileno())
                stage.replace(target)
            conn.execute(
                text(
                    "INSERT INTO research_trial VALUES (:study,:trial,:phase,:config,"
                    ":artifact,:bytes,:at)"
                ),
                {
                    "study": study_id,
                    "trial": trial_id,
                    "phase": phase,
                    "config": config_hash,
                    "artifact": digest,
                    "bytes": len(result),
                    "at": datetime.now(UTC),
                },
            )
            if selection is not None:
                # Freezing is a database fact in the same transaction as the trial.
                self.gate(
                    conn,
                    "SELECT research_freeze_selection(:id,CAST(:selected AS jsonb),:artifact)",
                    {"id": study_id, "selected": json.dumps(list(selection)), "artifact": digest},
                    "FROZEN",
                )
        return digest

    def path(self, digest: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("INVALID_ARTIFACT_DIGEST")
        path = self.root / (digest + ".json")
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("RESEARCH_ARTIFACT_ESCAPE")
        return path

    def read_trial(self, study_id: str, trial_id: str, conn: Connection | None = None) -> bytes:
        if conn is None:
            with self.engine.connect() as own:
                return self.read_trial(study_id, trial_id, own)
        digest, size = conn.execute(
            text(
                "SELECT artifact_hash,artifact_bytes FROM research_trial "
                "WHERE study_id=:study AND trial_id=:trial"
            ),
            {"study": study_id, "trial": trial_id},
        ).one()
        path = self.path(digest)
        payload = path.read_bytes()
        if len(payload) != size or hashlib.sha256(payload).hexdigest() != digest:
            raise ValueError("CORRUPT_RESEARCH_ARTIFACT")
        return payload

    def verify(self) -> dict[str, int]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("SELECT artifact_hash,artifact_bytes FROM research_trial")
            ).all()
            for row in rows:
                path = self.path(row[0])
                if not path.is_file() or path.stat().st_size != row[1] or file_hash(path) != row[0]:
                    raise ValueError("CORRUPT_RESEARCH_ARTIFACT")
            for study_id in conn.scalars(text("SELECT study_id FROM research_study")):
                self.study(study_id, conn)
        return {"trials": len(rows), "verified_artifacts": len({r[0] for r in rows})}


def trial_artifact(identity: TrialIdentity, /, **content: object) -> bytes:
    """Canonical trial artifact bytes: the verified identity plus the trial's own content."""
    if "identity" in content:
        raise ValueError("TRIAL_IDENTITY_MISMATCH")
    return artifact_bytes({"identity": identity.model_dump(mode="json"), **content})
