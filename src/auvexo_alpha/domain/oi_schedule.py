"""Deterministic OI schedule and externally accepted START checks; no authority issuer."""

from datetime import datetime, timedelta
from typing import Annotated, Literal, Self

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
    """A caller-constructible document is not authority without its external accepted digest.

    No writer/issuer exists here. A separately reviewed owner START must provide the
    out-of-band accepted digest and bind the exact independently accepted implementation.
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
        accepted_digest: str,
        now: datetime,
        review_authority: OIReviewAuthority | None = None,
    ) -> None:
        config = OICollectionConfig.model_validate(config.model_dump(mode="python"))
        envelope = OIStartEnvelope.model_validate(self.model_dump(mode="python"))
        require_oi_rights(config.rights, now, review_authority)
        if (
            not config.enabled
            or accepted_digest != envelope.content_hash()
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
