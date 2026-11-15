"""Deterministic OI schedule and externally accepted START checks; no authority issuer."""

from datetime import datetime, timedelta
from typing import Annotated, Final, Literal, Self, cast, get_args

from pydantic import BeforeValidator, Field, model_validator

from auvexo_alpha.domain.contracts import Contract, Digest, Label, UTCTime, utc_time
from auvexo_alpha.domain.oi_rights_review import OIReviewAuthority, require_oi_rights
from auvexo_alpha.domain.open_interest import OIRights, OISourceIdentity, OISymbol


def windows_clock_source(value: object) -> str:
    """Preserve bounded Windows source text as data, without label normalization."""
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 128
        or not value.isprintable()
    ):
        raise ValueError("OI_CLOCK_SOURCE_INVALID")
    return value


WindowsClockSource = Annotated[
    str, BeforeValidator(windows_clock_source), Field(min_length=1, max_length=128)
]


def slot_allowed(slot: datetime) -> bool:
    slot = utc_time(slot)
    return slot == slot.replace(minute=0, second=0, microsecond=0) and slot.hour not in (16, 17, 18)


def current_slot(now: datetime) -> datetime:
    return utc_time(now).replace(minute=0, second=0, microsecond=0)


def symbol_due(slot: datetime, symbol: OISymbol) -> datetime:
    if not slot_allowed(slot) or symbol not in ("BTCUSDT", "ETHUSDT"):
        raise ValueError("OI_SCHEDULE_SCOPE")
    return slot + timedelta(seconds=0 if symbol == "BTCUSDT" else 2)


class OICollectionConfig(Contract):
    """Enabling a config alone is insufficient: external START digest is also required."""

    version: Literal["oi-collection.v1"] = "oi-collection.v1"
    enabled: bool = False
    git_revision: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    code_hash: Digest
    lock_hash: Digest
    preregistration_hash: Digest
    source: OISourceIdentity = Field(default_factory=OISourceIdentity)
    rights: OIRights = Field(default_factory=OIRights)
    study_id: Label
    clock_source: WindowsClockSource
    database_name: Literal["auvexo_dev_oiresearch"] = "auvexo_dev_oiresearch"
    database_port: Literal[55433] = 55433
    max_start_lateness_seconds: Literal[15] = 15
    max_slot_seconds: Literal[60] = 60
    max_workers: Literal[1] = 1
    spend_usd: Literal[0] = 0


class OIStartEnvelope(Contract):
    """The owner's START bindings. On its own it is never authority.

    Authority is an ``OIStartAcceptance`` entry committed in the pinned runtime checkout
    (see ``OIAcceptedStart``). A digest the caller computes over a document it also
    supplies proves nothing, so this check compares bindings only. No issuer exists here.
    """

    purpose: Literal["DS04_A1_OWNER_COLLECTION_START"] = "DS04_A1_OWNER_COLLECTION_START"
    owner_authorization_ref: Label
    independent_review_ref: Label
    implementation_revision: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    config_hash: Digest
    code_hash: Digest
    source_hash: Digest
    rights_hash: Digest
    preregistration_hash: Digest
    issued_at: UTCTime
    owner_start_at: UTCTime
    expires_at: UTCTime

    @model_validator(mode="after")
    def chronology(self) -> Self:
        if not self.issued_at <= self.owner_start_at < self.expires_at:
            raise ValueError("OI_START_CHRONOLOGY")
        return self

    def require_start(
        self,
        config: OICollectionConfig,
        now: datetime,
        review_authority: OIReviewAuthority | None = None,
    ) -> None:
        config = OICollectionConfig.model_validate(config.model_dump(mode="python"))
        envelope = OIStartEnvelope.model_validate(self.model_dump(mode="python"))
        require_oi_rights(config.rights, now, review_authority)
        if (
            not config.enabled
            or envelope.config_hash != config.content_hash()
            or envelope.code_hash != config.code_hash
            or envelope.implementation_revision != config.git_revision
            or envelope.source_hash != config.source.content_hash()
            or envelope.rights_hash != config.rights.content_hash()
            or envelope.preregistration_hash != config.preregistration_hash
            or not envelope.owner_start_at <= utc_time(now) < envelope.expires_at
            or envelope.expires_at
            > (
                envelope.owner_start_at.replace(hour=0, minute=0, second=0, microsecond=0)
                + timedelta(days=93)
            )
        ):
            raise ValueError("OI_START_AUTHORITY_INVALID")


# Repository-relative path of the reviewed START acceptance file. It is read only from the
# committed tree of the pinned runtime checkout, never from the working tree or a CLI path.
OI_START_ACCEPTANCE_PATH: Final = "acceptance/oi-start-acceptance.json"


class OIRuntimeIdentity(Contract):
    """The pinned runtime a START was accepted for: checkout and exact interpreter bytes."""

    checkout_root: Annotated[str, Field(min_length=3, max_length=260)]
    python_executable: Annotated[str, Field(min_length=3, max_length=260)]
    python_executable_sha256: Digest
    base_interpreter_sha256: Digest

    @model_validator(mode="after")
    def printable(self) -> Self:
        if not all(v.isprintable() for v in (self.checkout_root, self.python_executable)):
            raise ValueError("OI_START_RUNTIME_INVALID")
        return self


class OIStartAcceptance(Contract):
    """One externally reviewed START, as committed in the acceptance file.

    It binds the owner's intent and envelope (release, config, code, source, rights review
    and preregistration hashes), the study, the exact runtime and the commissioning clock
    evidence. Its content hash is the START digest every manifest records. This contract
    is data: the collection runtime has no path that writes, commits or derives it.
    """

    version: Literal["oi-start-acceptance.v1"] = "oi-start-acceptance.v1"
    intent: Literal["OWNER_STARTS_DS04_A1_OI_FWD_V1_FIXED_STUDY"] = (
        "OWNER_STARTS_DS04_A1_OI_FWD_V1_FIXED_STUDY"
    )
    study_id: Label
    envelope: OIStartEnvelope
    runtime: OIRuntimeIdentity
    commissioning_clock_source: WindowsClockSource
    commissioning_clock_evidence_hash: Digest
    acceptance_review_ref: Label

    def require_start(
        self,
        config: OICollectionConfig,
        now: datetime,
        review_authority: OIReviewAuthority | None = None,
    ) -> None:
        checked = OIStartAcceptance.model_validate(self.model_dump(mode="python"))
        checked.envelope.require_start(config, now, review_authority)
        if (
            checked.study_id != config.study_id
            or checked.commissioning_clock_source != config.clock_source
        ):
            raise ValueError("OI_START_AUTHORITY_INVALID")

    def require_runtime(self, runtime: OIRuntimeIdentity) -> None:
        if OIRuntimeIdentity.model_validate(runtime.model_dump(mode="python")) != self.runtime:
            raise ValueError("OI_START_RUNTIME_MISMATCH")


class OIStartAcceptanceFile(Contract):
    """The committed file: a short list of reviewed STARTs with distinct digests."""

    version: Literal["oi-start-acceptance-file.v1"] = "oi-start-acceptance-file.v1"
    accepted: tuple[OIStartAcceptance, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def distinct(self) -> Self:
        if len({entry.content_hash() for entry in self.accepted}) != len(self.accepted):
            raise ValueError("OI_START_ACCEPTANCE_DUPLICATE")
        return self

    def select(self, digest: str) -> OIStartAcceptance:
        found = [entry for entry in self.accepted if entry.content_hash() == digest]
        if len(found) != 1:
            raise ValueError("OI_START_NOT_ACCEPTED")
        return found[0]


class OIAcceptedStart(Contract):
    """A START entry together with the exact commit whose tree holds the acceptance file.

    This is plain data: any code can construct one, and a constructed value proves
    nothing. It is evidence only as returned by ``load_accepted_start`` for the commit
    ``require_build`` proved. The collector CLI and ``evaluate_recorded_study`` obtain it
    only that way and accept no caller-built value; no public evaluation takes one.
    """

    acceptance_commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    acceptance: OIStartAcceptance

    @property
    def digest(self) -> str:
        return self.acceptance.content_hash()

    @property
    def envelope(self) -> OIStartEnvelope:
        return self.acceptance.envelope

    def require_start(
        self,
        config: OICollectionConfig,
        now: datetime,
        review_authority: OIReviewAuthority | None = None,
    ) -> None:
        self.acceptance.require_start(config, now, review_authority)


# Closed set of slot-gap reasons. Anything else a refusal carries is recorded as the
# explicit catch-all OI_REFUSED_UNCLASSIFIED, never as free text.
type OIGapReason = Literal[
    "OI_NO_RUN_RECORDED",
    "OI_REFUSED_UNCLASSIFIED",
    # Launch refusals under a valid START.
    "OI_CONFIG_INVALID",
    "OI_CLOCK_UNTRUSTED",
    "OI_RESOURCE_YIELD",
    "OI_LATE_NO_CATCHUP",
    "OI_STOPPED",
    "OI_RIGHTS_BLOCKED_OR_EXPIRED",
    "OI_RIGHTS_REVOKED",
    "OI_REVIEW_GAP_BLOCKED",
    # Collection refusals inside the slot.
    "OI_RUNTIME_AUTHORITY_OR_CLOCK_INVALID",
    "OI_SLOT_DEADLINE",
    "OI_CLOCK_REGRESSION",
    "OI_RECEIPT_ADMISSION_EXPIRED",
    "OI_SCHEMA_OR_QUALITY",
    "OI_CONFLICT_REVIEW_REQUIRED",
    "OI_SLOT_GAP_RECORDED",
    # Source and transport refusals.
    "OI_SOURCE_UNAVAILABLE",
    "OI_SOURCE_CONFIG",
    "OI_NETWORK",
    "OI_NETWORK_BUDGET",
    "OI_RATE_LIMIT",
    "OI_PROVIDER_ACCESS_BLOCKED",
    "OI_COOLDOWN",
    "OI_CLOCK_SPACING",
    "OI_ADMISSION_BLOCKED",
    "OI_CONTENT_TYPE",
    "OI_CONTENT_ENCODING",
    "OI_RESPONSE_BUDGET",
    "OI_BUDGET_STATE",
    "OI_ATTEMPT_DEADLINE",
    "OI_JOB_DEADLINE",
    "OI_WORKER_FAILED",
    "OI_WORKER_CLEANUP_FAILED",
    "OI_ATTEMPT_OUTCOME_UNKNOWN",
    "OI_TRANSPORT_OUTCOME_REVIEW_REQUIRED",
    "OI_SINGLE_INSTANCE",
]
OI_GAP_REASONS: Final[frozenset[str]] = frozenset(get_args(OIGapReason.__value__))


def closed_gap_reason(value: object) -> OIGapReason:
    """A reason in the closed set, or the explicit catch-all for anything else."""
    if type(value) is str and value in OI_GAP_REASONS:
        return cast(OIGapReason, value)
    return "OI_REFUSED_UNCLASSIFIED"


def slot_gap_identity(symbol: str, slot_at: datetime) -> str:
    """The one (symbol, slot) key a gap record and a manifest slot are compared by."""
    return f"{symbol}:{utc_time(slot_at).isoformat()}"


class OISlotGap(Contract):
    """Durable record that one scheduled symbol slot produced no admitted snapshot.

    A gap is never filled later: no catch-up, no replacement and no calendar credit.
    """

    symbol: OISymbol
    slot_at: UTCTime
    reason: OIGapReason
    recorded_at: UTCTime

    @model_validator(mode="after")
    def scheduled(self) -> Self:
        if not slot_allowed(self.slot_at) or self.recorded_at < self.slot_at:
            raise ValueError("OI_GAP_SLOT_INVALID")
        return self

    @property
    def identity(self) -> str:
        return slot_gap_identity(self.symbol, self.slot_at)


class OIClockProof(Contract):
    """Bounded local Windows Time Service inspection, never a new provider endpoint."""

    source: WindowsClockSource
    inspected_at: UTCTime
    time_since_sync_seconds: Annotated[int, Field(ge=0, le=3600)]
    offset_bound_ms: Annotated[int, Field(ge=0, le=1000)]
    evidence_hash: Digest

    def require_trusted(self, config: OICollectionConfig, now: datetime) -> None:
        proof = OIClockProof.model_validate(self.model_dump(mode="python"))
        if proof.source != config.clock_source or not (
            proof.inspected_at <= utc_time(now) <= proof.inspected_at + timedelta(seconds=120)
        ):
            raise ValueError("OI_CLOCK_UNTRUSTED")


def scheduled_slot(config: OICollectionConfig, now: datetime) -> datetime:
    now = utc_time(now)
    slot = current_slot(now)
    if not config.enabled:
        raise ValueError("OI_COLLECTOR_DISABLED")
    if not slot_allowed(slot):
        raise ValueError("OI_PROTECTED_WINDOW")
    if now > slot + timedelta(seconds=config.max_start_lateness_seconds):
        raise ValueError("OI_LATE_NO_CATCHUP")
    return slot


def require_scheduled_start(
    config: OICollectionConfig,
    now: datetime,
    review_authority: OIReviewAuthority | None = None,
) -> datetime:
    slot = scheduled_slot(config, now)
    require_oi_rights(config.rights, now, review_authority)
    return slot
