"""Deterministic release metadata; labels confer no execution authority."""

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from auvexo_alpha.domain.contracts import Contract, Digest, Label, Mode, Product, UTCTime, Venue
from auvexo_alpha.domain.research import DataUseClass, inherited_use


class SourceEligibility(Contract):
    """Reviewed source-specific metadata, never evidence created by a model label."""

    source_id: Label
    venue: Venue
    product: Product
    instrument_id: Label
    range_start: UTCTime
    range_end: UTCTime
    dataset_hash: Digest
    rights_snapshot_hash: Digest
    rights_valid_until: UTCTime
    availability_version: Label
    availability_hash: Digest
    classification: DataUseClass
    intended_use: Literal["PROMOTION"]
    reviewer: Label
    reviewed_at: UTCTime
    acceptance_evidence_hash: Digest
    parents: tuple["SourceEligibility", ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def chronology_and_lineage(self) -> Self:
        if not self.range_start < self.range_end <= self.reviewed_at < self.rights_valid_until:
            raise ValueError("SOURCE_ELIGIBILITY_CHRONOLOGY")
        if self.classification == DataUseClass.PROMOTION_ELIGIBLE and (
            self.source_id in ("DS-01", "DS-02")
            or inherited_use(tuple(p.classification for p in self.parents))
            != DataUseClass.PROMOTION_ELIGIBLE
            and bool(self.parents)
        ):
            raise ValueError("RESTRICTED_SOURCE_CANNOT_UPGRADE")
        return self

    def require_current(self, now: datetime) -> None:
        if (
            self.classification != DataUseClass.PROMOTION_ELIGIBLE
            or not self.reviewed_at <= now < self.rights_valid_until
        ):
            raise ValueError("SOURCE_ELIGIBILITY_UNAVAILABLE_OR_EXPIRED")
        for parent in self.parents:
            parent.require_current(now)


class ReleaseDataEligibility(Contract):
    inputs: tuple[SourceEligibility, ...] = Field(min_length=1, max_length=32)


class ReleaseKind(StrEnum):
    TEST_ONLY = "TEST_ONLY"
    RESEARCH_EVIDENCED = "RESEARCH_EVIDENCED"


class ReleaseState(StrEnum):
    RESEARCH = "RESEARCH"
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    PAPER = "PAPER"
    SHADOW = "SHADOW"
    LIVE_LIMITED = "LIVE_LIMITED"
    LIVE = "LIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class EdgeState(StrEnum):
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    REDUCE = "REDUCE"
    SUSPEND = "SUSPEND"
    INVESTIGATE = "INVESTIGATE"


class KillLevel(StrEnum):
    K0 = "K0"
    K1 = "K1"
    K2 = "K2"
    K3 = "K3"
    K4 = "K4"


class Release(Contract):
    release_id: Label
    kind: ReleaseKind
    state: ReleaseState
    code_hash: Digest
    config_hash: Digest
    data_hash: Digest
    evidence_hash: Digest
    allowed_modes: tuple[Mode, ...]
    approved_by: tuple[Label, ...]
    created_at: UTCTime
    updated_at: UTCTime | None = None
    data_use: DataUseClass
    independent_evidence: bool
    fixture_namespace: Literal["PAPER_QUALIFICATION_FIXTURE"] | None = None
    data_eligibility: ReleaseDataEligibility | None = None

    @model_validator(mode="after")
    def fixture_isolation(self) -> Self:
        if self.updated_at is not None and self.updated_at < self.created_at:
            raise ValueError("RELEASE_TIME_REVERSED")
        if len(set(self.allowed_modes)) != len(self.allowed_modes):
            raise ValueError("DUPLICATE_RELEASE_MODE")
        if self.kind == ReleaseKind.TEST_ONLY:
            if (
                self.state not in (ReleaseState.PAPER, ReleaseState.SUSPENDED, ReleaseState.RETIRED)
                or self.allowed_modes != (Mode.PAPER,)
                or self.data_use != DataUseClass.ENGINEERING_ONLY
                or self.fixture_namespace != "PAPER_QUALIFICATION_FIXTURE"
                or self.independent_evidence
                or self.data_eligibility is not None
            ):
                raise ValueError("TEST_ONLY_ISOLATION")
        elif self.fixture_namespace is not None:
            raise ValueError("PRODUCTION_FIXTURE_NAMESPACE_FORBIDDEN")
        if (
            self.data_eligibility is not None
            and self.data_hash != self.data_eligibility.content_hash()
        ):
            raise ValueError("RELEASE_DATA_ELIGIBILITY_HASH_MISMATCH")
        if self.kind == ReleaseKind.RESEARCH_EVIDENCED and self.state not in (
            ReleaseState.RESEARCH,
            ReleaseState.SUSPENDED,
            ReleaseState.RETIRED,
        ):
            if (
                self.data_use != DataUseClass.PROMOTION_ELIGIBLE
                or not self.independent_evidence
                or len(set(self.approved_by)) < 2
                or self.data_eligibility is None
            ):
                raise ValueError("INDEPENDENT_ELIGIBLE_RESEARCH_REQUIRED")
            for source in self.data_eligibility.inputs:
                source.require_current(self.updated_at or self.created_at)
        return self


class ReleaseTransition(Contract):
    release_id: Label
    prior_hash: Digest
    next_hash: Digest
    from_state: ReleaseState
    to_state: ReleaseState
    actor: Label
    actor_role: Literal["OWNER", "INDEPENDENT_REVIEWER"]
    recorded_at: UTCTime
    evidence_hash: Digest


def validate_registry_release(
    release: Release, *, fixture_registry: bool, now: datetime | None = None
) -> None:
    """Production and qualification registries are physically separate at storage."""
    Release.model_validate_json(release.model_dump_json())
    if fixture_registry != (release.kind == ReleaseKind.TEST_ONLY):
        raise ValueError("WRONG_RELEASE_REGISTRY")
    require_release_eligibility(release, now or release.updated_at or release.created_at)


def validate_initial_release(release: Release, *, fixture_registry: bool) -> None:
    """Only production RESEARCH may start a durable release identity."""
    Release.model_validate_json(release.canonical_bytes())
    if fixture_registry != (release.kind == ReleaseKind.TEST_ONLY):
        raise ValueError("WRONG_RELEASE_REGISTRY")
    if not fixture_registry and (
        release.state != ReleaseState.RESEARCH or release.updated_at is not None
    ):
        raise ValueError("INITIAL_PRODUCTION_RESEARCH_REQUIRED")


def validate_release_transition(
    prior: Release, release: Release, transition: ReleaseTransition
) -> None:
    """Bind every field to the deterministic transition from an exact prior snapshot."""
    prior = Release.model_validate_json(prior.canonical_bytes())
    release = Release.model_validate_json(release.canonical_bytes())
    transition = ReleaseTransition.model_validate_json(transition.canonical_bytes())
    expected, event = transition_release(
        prior,
        transition.to_state,
        actor=transition.actor,
        actor_role=transition.actor_role,
        approved_at=transition.recorded_at,
        evidence_hash=transition.evidence_hash,
    )
    if expected != release or event != transition:
        raise ValueError("RELEASE_HISTORY_BINDING_DENIED")


def require_release_eligibility(release: Release, now: datetime) -> None:
    if release.kind == ReleaseKind.RESEARCH_EVIDENCED and release.state not in (
        ReleaseState.RESEARCH,
        ReleaseState.SUSPENDED,
        ReleaseState.RETIRED,
    ):
        if release.data_eligibility is None:
            raise ValueError("INDEPENDENT_ELIGIBLE_RESEARCH_REQUIRED")
        for source in release.data_eligibility.inputs:
            source.require_current(now)


def transition_release(
    release: Release,
    target: ReleaseState,
    *,
    actor: str,
    actor_role: Literal["OWNER", "INDEPENDENT_REVIEWER"],
    approved_at: UTCTime,
    evidence_hash: str,
) -> tuple[Release, ReleaseTransition]:
    """Return new immutable metadata plus appendable evidence; never mutate history."""
    Release.model_validate_json(release.model_dump_json())
    if actor_role not in ("OWNER", "INDEPENDENT_REVIEWER"):
        raise ValueError("AGENT_PROMOTION_FORBIDDEN")
    if approved_at < (release.updated_at or release.created_at):
        raise ValueError("RELEASE_TIME_REVERSED")
    if release.state == ReleaseState.RETIRED or target == release.state:
        raise ValueError("INVALID_RELEASE_TRANSITION")
    path = (
        ReleaseState.RESEARCH,
        ReleaseState.CANDIDATE,
        ReleaseState.VALIDATED,
        ReleaseState.PAPER,
        ReleaseState.SHADOW,
        ReleaseState.LIVE_LIMITED,
        ReleaseState.LIVE,
    )
    if target not in (ReleaseState.SUSPENDED, ReleaseState.RETIRED):
        if release.state == ReleaseState.SUSPENDED:
            if actor_role != "OWNER" or target != ReleaseState.PAPER:
                raise ValueError("EXPLICIT_PAPER_REQUALIFICATION_REQUIRED")
        elif release.kind == ReleaseKind.TEST_ONLY:
            raise ValueError("TEST_ONLY_PROMOTION_FORBIDDEN")
        elif release.state not in path or path.index(release.state) + 1 >= len(path):
            raise ValueError("INVALID_RELEASE_TRANSITION")
        elif path[path.index(release.state) + 1] != target:
            raise ValueError("RELEASE_TRANSITION_CANNOT_SKIP")
    payload = release.model_dump()
    payload.update(state=target, evidence_hash=evidence_hash, updated_at=approved_at)
    updated = Release.model_validate(payload)
    event = ReleaseTransition(
        release_id=release.release_id,
        prior_hash=release.content_hash(),
        next_hash=updated.content_hash(),
        from_state=release.state,
        to_state=target,
        actor=actor,
        actor_role=actor_role,
        recorded_at=approved_at,
        evidence_hash=evidence_hash,
    )
    return updated, event


class EdgeTransition(Contract):
    release_hash: Digest
    from_state: EdgeState
    to_state: EdgeState
    fixture_version: Label
    evidence_hash: Digest
    recorded_at: UTCTime
    actor: Label
    actor_role: Literal["OWNER", "SYSTEM", "AGENT"]


def fixture_edge_transition(release: Release, transition: EdgeTransition) -> EdgeState:
    """Exercise plumbing only; no alpha threshold is inferred from this function."""
    release = Release.model_validate_json(release.model_dump_json(warnings="error"))
    transition = EdgeTransition.model_validate_json(transition.model_dump_json(warnings="error"))
    if release.kind != ReleaseKind.TEST_ONLY or transition.release_hash != release.content_hash():
        raise ValueError("VERSIONED_TEST_EDGE_EVIDENCE_REQUIRED")
    if transition.recorded_at < release.created_at:
        raise ValueError("EDGE_TIME_REVERSED")
    if transition.from_state == transition.to_state:
        raise ValueError("EDGE_TRANSITION_NO_CHANGE")
    if transition.to_state == EdgeState.NORMAL and transition.actor_role != "OWNER":
        raise ValueError("EXPLICIT_OWNER_RESUME_REQUIRED")
    if transition.actor_role == "AGENT" and transition.to_state not in (
        EdgeState.INVESTIGATE,
        EdgeState.SUSPEND,
    ):
        raise ValueError("AGENT_CANNOT_RELAX_EDGE_STATE")
    if transition.from_state in (EdgeState.SUSPEND, EdgeState.INVESTIGATE) and (
        transition.to_state not in (EdgeState.SUSPEND, EdgeState.INVESTIGATE)
        and transition.actor_role != "OWNER"
    ):
        raise ValueError("EXPLICIT_OWNER_RESUME_REQUIRED")
    return transition.to_state
