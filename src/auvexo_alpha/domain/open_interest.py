"""DS-04-A1 source-specific nonproduction OI contracts; never trading authority."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Final, Literal, Self

from pydantic import Field, model_validator

from auvexo_alpha.domain.contracts import (
    Contract,
    Digest,
    Label,
    NonnegativeAmount,
    UTCTime,
    exact_decimal,
    utc_time,
)
from auvexo_alpha.domain.research import DataUseClass

if TYPE_CHECKING:
    from auvexo_alpha.domain.oi_rights_review import OIReviewAuthority

OISymbol = Literal["BTCUSDT", "ETHUSDT"]
OI_ENDPOINT: Final = "https://fapi.binance.com/fapi/v1/openInterest"
OI_RIGHTS_VERSION: Final = "ds04-a1-rights.20261027.v1"
OI_SOURCE_DOCUMENT_HASH: Final = "2156363f3b21401285c9b24c2ef09dafa52f743893721396468acd966d62f1fa"
OI_TERMS_HASH = "bf4879710c904b991848972ec4818ba2cf9e4ce314c09adae84fa2750d3477f7"
OI_PROCEDURES_HASH = "08457d5d2da5ed76cc52136079d93bf8ba404d697423819bcdb7b34dbd88d667"
OI_RULES_HASH = "c621ea666949fa36c44308e16e360841b8badd6b0db109c5f768317995a2aa7a"
OI_ACCEPTED_SOURCE: Final = "887b6ac38636e07ff922d2ba2d0ec7b2063edd4f"
OI_REVIEWED_AT = datetime(2026, 10, 27, 11, 12, tzinfo=UTC)
OI_REVIEW_DUE = datetime(2026, 11, 27, tzinfo=UTC)
OI_EVIDENCE_URLS = tuple(
    "https://bin.bnbstatic.com/static/cms/cg08ou2ak0tn7mcplvfg/file/" + h + ".pdf"
    for h in (OI_TERMS_HASH, OI_PROCEDURES_HASH, OI_RULES_HASH)
)
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class OISourceIdentity(Contract):
    source_id: Literal["DS-04-A1"] = "DS-04-A1"
    provider: Literal["BINANCE"] = "BINANCE"
    venue: Literal["BINANCE_RIE"] = "BINANCE_RIE"
    product: Literal["USD_M_FUTURES"] = "USD_M_FUTURES"
    family: Literal["OPEN_INTEREST_SNAPSHOT"] = "OPEN_INTEREST_SNAPSHOT"
    endpoint: Literal["https://fapi.binance.com/fapi/v1/openInterest"] = OI_ENDPOINT
    rights_version: Literal["ds04-a1-rights.20261027.v1"] = OI_RIGHTS_VERSION


class OIRights(Contract):
    source: OISourceIdentity = Field(default_factory=OISourceIdentity)
    version: Literal["ds04-a1-rights.20261027.v1"] = OI_RIGHTS_VERSION
    reviewed_at: UTCTime = OI_REVIEWED_AT
    review_due: UTCTime = OI_REVIEW_DUE
    terms_hash: Digest = OI_TERMS_HASH
    procedures_hash: Digest = OI_PROCEDURES_HASH
    rules_hash: Digest = OI_RULES_HASH
    evidence_urls: tuple[str, ...] = OI_EVIDENCE_URLS
    accepted_source_sha: Literal["887b6ac38636e07ff922d2ba2d0ec7b2063edd4f"] = OI_ACCEPTED_SOURCE
    permitted_use: Literal["PERSONAL_NONCOMMERCIAL_NONPRODUCTION_RESEARCH"] = (
        "PERSONAL_NONCOMMERCIAL_NONPRODUCTION_RESEARCH"
    )
    redistribution: Literal["NOT_AUTHORIZED"] = "NOT_AUTHORIZED"
    live_promotion: Literal["NOT_AUTHORIZED"] = "NOT_AUTHORIZED"
    retention: Literal["NECESSARY_PRIVATE_REPRODUCIBILITY_PROJECT_INTERPRETATION"] = (
        "NECESSARY_PRIVATE_REPRODUCIBILITY_PROJECT_INTERPRETATION"
    )
    revoked: bool = False

    @model_validator(mode="after")
    def accepted_snapshot(self) -> Self:
        if (
            self.reviewed_at != OI_REVIEWED_AT
            or self.review_due != OI_REVIEW_DUE
            or self.terms_hash != OI_TERMS_HASH
            or self.procedures_hash != OI_PROCEDURES_HASH
            or self.rules_hash != OI_RULES_HASH
            or self.evidence_urls != OI_EVIDENCE_URLS
        ):
            raise ValueError("OI_UNKNOWN_RIGHTS_SNAPSHOT")
        return self

    def require_research(self, now: datetime) -> None:
        if self.revoked or not self.reviewed_at <= utc_time(now) < self.review_due:
            raise ValueError("OI_RIGHTS_BLOCKED_OR_EXPIRED")


def accepted_oi_rights() -> OIRights:
    return OIRights()


class OIObservation(Contract):
    symbol: OISymbol
    slot_at: UTCTime
    raw_open_interest: Annotated[
        str, Field(min_length=1, max_length=38, pattern=r"^(0|[1-9][0-9]{0,17})(\.[0-9]{1,18})?$")
    ]
    value: NonnegativeAmount
    provider_time_ms: Annotated[int, Field(ge=1_577_836_800_000, le=9_999_999_999_999)]
    provider_at: UTCTime
    request_sent_at: UTCTime
    first_seen_at: UTCTime
    received_at: UTCTime
    processed_at: UTCTime
    available_at: UTCTime
    source: OISourceIdentity = Field(default_factory=OISourceIdentity)
    rights_version: Literal["ds04-a1-rights.20261027.v1"] = OI_RIGHTS_VERSION
    source_document_version: Literal["ds04-a1-source.20261027.v1"] = "ds04-a1-source.20261027.v1"
    source_document_hash: Literal[
        "2156363f3b21401285c9b24c2ef09dafa52f743893721396468acd966d62f1fa"
    ] = OI_SOURCE_DOCUMENT_HASH
    unit: Literal["PROVIDER_NATIVE_OI_UNSPECIFIED"] = "PROVIDER_NATIVE_OI_UNSPECIFIED"
    parser_version: Literal["oi-snapshot.v1"] = "oi-snapshot.v1"
    code_revision: Label
    code_hash: Digest
    raw_hash: Digest
    quality: Literal["VALID", "STALE", "QUARANTINED", "BLOCKED"] = "VALID"
    reason: Label = "VALID"
    prior_raw_hash: Digest | None = None
    review_receipt_hash: Digest | None = None

    @model_validator(mode="after")
    def chronology_and_identity(self) -> Self:
        if self.slot_at != self.slot_at.replace(minute=0, second=0, microsecond=0):
            raise ValueError("OI_SLOT_BOUNDARY")
        if exact_decimal(self.raw_open_interest) != self.value:
            raise ValueError("OI_RAW_VALUE_MISMATCH")
        if not (
            self.request_sent_at
            <= self.first_seen_at
            <= self.received_at
            <= self.processed_at
            <= self.available_at
        ):
            raise ValueError("OI_CHRONOLOGY")
        if EPOCH + timedelta(milliseconds=self.provider_time_ms) != self.provider_at:
            raise ValueError("OI_TIMESTAMP_UNIT")
        if self.provider_at > self.received_at:
            raise ValueError("OI_PROVIDER_FUTURE")
        if not self.slot_at <= self.request_sent_at < self.slot_at + timedelta(hours=1):
            raise ValueError("OI_SLOT_IDENTITY")
        if self.quality == "VALID" and self.received_at - self.provider_at > timedelta(seconds=120):
            raise ValueError("OI_PROVIDER_STALE")
        if self.quality == "QUARANTINED" and self.prior_raw_hash is None:
            raise ValueError("OI_CONFLICT_LINEAGE_REQUIRED")
        return self

    @property
    def identity_key(self) -> str:
        return f"DS-04-A1:USD_M_FUTURES:{self.symbol}:{self.provider_time_ms}:{self.parser_version}"

    @property
    def normalized_hash(self) -> str:
        return self.content_hash()


def oi_dataset_version(observation: OIObservation) -> str:
    return hashlib.sha256(
        (
            observation.identity_key + ":" + observation.raw_hash + ":" + observation.parser_version
        ).encode("ascii")
    ).hexdigest()


class OIManifest(Contract):
    parser_version: Literal["oi-snapshot.v1"] = "oi-snapshot.v1"
    dataset_version: Digest
    logical_key: Label
    observation: OIObservation
    rights: OIRights
    raw_relative_path: str = Field(pattern=r"^oi/raw/[0-9a-f]{64}\.raw$")
    normalized_relative_path: str = Field(pattern=r"^oi/normalized/[0-9a-f]{64}\.json$")
    raw_bytes: Annotated[int, Field(gt=0, le=4096)]
    normalized_bytes: Annotated[int, Field(gt=0, le=16384)]
    normalized_hash: Digest
    created_at: UTCTime
    processed_at: UTCTime
    supersedes: Digest | None = None
    conflict_raw_hash: Digest | None = None
    classification: DataUseClass = DataUseClass.ENGINEERING_ONLY
    retention_profile: Literal["REVIEW_BEFORE_REMOVAL_NO_AGE_CAP"] = (
        "REVIEW_BEFORE_REMOVAL_NO_AGE_CAP"
    )

    @model_validator(mode="after")
    def binding(self) -> Self:
        o = self.observation
        if (
            self.parser_version != o.parser_version
            or self.dataset_version != oi_dataset_version(o)
            or self.logical_key != f"ds04-a1:{o.symbol}:{o.provider_time_ms}:{o.parser_version}"
            or self.normalized_hash != o.content_hash()
            or self.normalized_bytes != len(o.canonical_bytes())
            or self.raw_relative_path != f"oi/raw/{o.raw_hash}.raw"
            or self.normalized_relative_path != f"oi/normalized/{self.normalized_hash}.json"
            or self.rights.source != o.source
            or self.rights.version != o.rights_version
        ):
            raise ValueError("OI_MANIFEST_BINDING")
        if not o.available_at <= self.processed_at <= self.created_at:
            raise ValueError("OI_MANIFEST_CHRONOLOGY")
        if self.classification == DataUseClass.PROMOTION_ELIGIBLE:
            raise ValueError("OI_PROMOTION_DENIED")
        if o.quality == "QUARANTINED":
            if (
                self.classification != DataUseClass.BLOCKED
                or self.conflict_raw_hash != o.prior_raw_hash
                or self.supersedes is None
            ):
                raise ValueError("OI_CONFLICT_LINEAGE_REQUIRED")
        elif self.conflict_raw_hash is not None:
            raise ValueError("OI_UNEXPLAINED_CONFLICT")
        return self

    @property
    def source(self) -> OISourceIdentity:
        return self.observation.source

    @property
    def raw_hash(self) -> str:
        return self.observation.raw_hash


def oi_classify_manifest(
    manifest: OIManifest,
    now: datetime,
    intended_use: Literal["ENGINEERING", "PERSONAL_NONPRODUCTION", "PROMOTION"] = (
        "PERSONAL_NONPRODUCTION"
    ),
    *,
    review_authority: OIReviewAuthority | None = None,
) -> DataUseClass:
    """Physical artifact verification is additionally mandatory at the read boundary."""
    from auvexo_alpha.domain.oi_rights_review import require_oi_rights

    if not isinstance(manifest, OIManifest) or intended_use not in (
        "ENGINEERING",
        "PERSONAL_NONPRODUCTION",
        "PROMOTION",
    ):
        return DataUseClass.BLOCKED
    try:
        # Revalidate even when a caller passed a model_construct/model_copy instance.
        checked = OIManifest.model_validate(manifest.model_dump(mode="python"))
        require_oi_rights(checked.rights, now, review_authority)
        require_oi_rights(checked.rights, checked.observation.received_at, review_authority)
        expected_receipt = (
            None
            if review_authority is None
            else review_authority.receipt_hash_at(checked.observation.received_at)
        )
        if checked.observation.review_receipt_hash != expected_receipt:
            return DataUseClass.BLOCKED
    except ValueError:
        return DataUseClass.BLOCKED
    if (
        intended_use == "PROMOTION"
        or checked.observation.quality != "VALID"
        or checked.observation.available_at > utc_time(now)
        or checked.classification == DataUseClass.BLOCKED
    ):
        return DataUseClass.BLOCKED
    if intended_use == "ENGINEERING" or checked.classification == DataUseClass.ENGINEERING_ONLY:
        return DataUseClass.ENGINEERING_ONLY
    return DataUseClass.PERSONAL_RESEARCH
