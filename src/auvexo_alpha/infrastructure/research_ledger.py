"""Serialized append-only research metadata and bounded immutable local artifacts."""

import hashlib
import json
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Connection, Engine, text

from auvexo_alpha.application.research_simulator import artifact_bytes
from auvexo_alpha.domain.research import DataUseClass, StudyManifest, classify_manifest
from auvexo_alpha.infrastructure.data_store import file_hash, pressure, tree_bytes


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

    def register(self, study: StudyManifest) -> None:
        study = StudyManifest.model_validate_json(study.canonical_bytes())
        if study.registered_at > datetime.now(UTC):
            raise ValueError("FUTURE_PREREGISTRATION")
        with self.engine.begin() as conn:
            self.lock(conn, study.study_id)
            conn.execute(text("SELECT pg_advisory_xact_lock(20801405)"))
            conn.execute(
                text("INSERT INTO research_study VALUES (:id,:hash,:payload,:at)"),
                {
                    "id": study.study_id,
                    "hash": study.content_hash(),
                    "payload": study.canonical_bytes().decode(),
                    "at": study.registered_at,
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

    def selected(self, conn: Connection, study_id: str) -> tuple[str, ...] | None:
        payload = conn.scalar(
            text("SELECT payload FROM research_event WHERE study_id=:id"), {"id": study_id}
        )
        return tuple(json.loads(payload)["selected"]) if payload is not None else None

    def open_holdout(self, study_id: str, selected: tuple[str, ...]) -> None:
        with self.engine.begin() as conn:
            self.lock(conn, study_id)
            conn.execute(text("SELECT pg_advisory_xact_lock(20801406)"))
            study = self.study(study_id, conn)
            permitted = {c.content_hash() for c in study.configs}
            if not selected or not set(selected) <= permitted:
                raise ValueError("UNREGISTERED_SELECTION")
            evaluated = set(
                conn.scalars(
                    text(
                        "SELECT config_hash FROM research_trial WHERE study_id=:id "
                        "AND phase='VALIDATION'"
                    ),
                    {"id": study_id},
                )
            )
            if evaluated != permitted:
                raise ValueError("VALIDATION_GRID_INCOMPLETE_HOLDOUT_SEALED")
            # An overlapping consumed calendar cannot become fresh by changing source versions.
            consumed = conn.scalar(
                text(
                    "SELECT count(*) FROM research_event e JOIN research_study s "
                    "ON e.study_id=s.study_id WHERE s.payload::jsonb->>'instrument'=:instrument "
                    "AND (s.payload::jsonb #>> '{split,oos_start}')::timestamptz < :end "
                    "AND :start < (s.payload::jsonb #>> '{split,oos_end}')::timestamptz"
                ),
                {
                    "instrument": study.instrument,
                    "start": study.split.oos_start,
                    "end": study.split.oos_end,
                },
            )
            if consumed:
                raise ValueError("OVERLAPPING_HOLDOUT_ALREADY_CONSUMED")
            scope = hashlib.sha256(
                artifact_bytes(
                    [
                        study.instrument,
                        study.split.oos_start,
                        study.split.oos_end,
                    ]
                )
            ).hexdigest()
            payload = artifact_bytes(
                {"selected": selected, "claim": "CONSUMED_BEFORE_READ"}
            ).decode()
            conn.execute(
                text(
                    "INSERT INTO research_event VALUES (:event,:study,'HOLDOUT_OPEN',"
                    ":scope,:payload,:at)"
                ),
                {
                    "event": str(uuid4()),
                    "study": study_id,
                    "scope": scope,
                    "payload": payload,
                    "at": datetime.now(UTC),
                },
            )

    def authorize_read(
        self, study_id: str, phase: str, start: datetime, end: datetime
    ) -> StudyManifest:
        with self.engine.begin() as conn:
            self.lock(conn, study_id)
            study = self.study(study_id, conn)
            self.check_phase(conn, study, phase)
            split = study.split
            lower, upper = {
                "TRAIN": (split.train_start, split.train_end),
                "VALIDATION": (split.validation_start, split.validation_end),
                "OOS": (split.oos_start, split.oos_end),
                "WALK_FORWARD": (split.train_start, split.validation_end),
            }[phase]
            if not lower <= start < end <= upper:
                raise ValueError("READ_OUTSIDE_REGISTERED_SPLIT")
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
            return study

    def check_phase(self, conn: Connection, study: StudyManifest, phase: str) -> None:
        if phase not in ("TRAIN", "VALIDATION", "OOS", "WALK_FORWARD"):
            raise ValueError("UNKNOWN_RESEARCH_PHASE")
        selected = self.selected(conn, study.study_id)
        if (phase == "OOS") != (selected is not None):
            raise ValueError("HOLDOUT_NOT_OPEN_OR_DEVELOPMENT_ALREADY_CONSUMED")

    def record(
        self, study_id: str, trial_id: str, phase: str, config_hash: str, result: bytes
    ) -> str:
        if (
            not re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", trial_id)
            or not 1 <= len(result) <= 64 * 1024 * 1024
        ):
            raise ValueError("TRIAL_OR_ARTIFACT_BUDGET")
        # Content is structured JSON, not arbitrary executable data/pickle.
        json.loads(result)
        digest = hashlib.sha256(result).hexdigest()
        with self.engine.begin() as conn:
            self.lock(conn, study_id)
            conn.execute(text("SELECT pg_advisory_xact_lock(20801405)"))
            study = self.study(study_id, conn)
            self.check_phase(conn, study, phase)
            permitted = (
                self.selected(conn, study_id)
                if phase == "OOS"
                else (tuple(c.content_hash() for c in study.configs))
            )
            if config_hash not in (permitted or ()):
                raise ValueError("UNREGISTERED_OR_POST_HOLDOUT_CONFIG")
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
        return digest

    def path(self, digest: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("INVALID_ARTIFACT_DIGEST")
        path = self.root / (digest + ".json")
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("RESEARCH_ARTIFACT_ESCAPE")
        return path

    def read_trial(self, study_id: str, trial_id: str) -> bytes:
        with self.engine.connect() as conn:
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
