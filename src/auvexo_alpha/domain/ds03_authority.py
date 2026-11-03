"""Scoped future read-only onboarding bindings; no authority issuer or activation switch."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Annotated, Final, Literal, Self

from pydantic import Field, model_validator

from auvexo_alpha.domain.contracts import Contract, Digest, Identifier, Label, UTCTime, utc_time

PACKAGE_VERSION: Final = "5.0.6231"
WHEEL_HASH: Final = "3a8c8349ce691a4ef05e314afc034ad82f4dbb19415efc7442af5ea075d5e797"
CREDENTIAL_PURPOSE: Final = "auvexo-alpha:phase2:ds03:mt5-demo-readonly-password:v1"
GitSHA = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
PrivateText = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[\x21-\x7e]+$")]
CurrencyCode = Annotated[str, Field(pattern=r"^[A-Z]{3,8}$")]


class Ds03AuthorityError(ValueError):
    def __init__(self) -> None:
        super().__init__("DS03_AUTHORITY_UNAVAILABLE")


class Ds03LocalMetadata(Contract):
    login: int = Field(gt=0, le=9223372036854775807, repr=False)
    assigned_server: PrivateText = Field(repr=False)
    account_type: Label = Field(repr=False)
    account_type_source: Literal["OWNER_METADATA_ONLY_NOT_EXPOSED_BY_MT5"] = (
        "OWNER_METADATA_ONLY_NOT_EXPOSED_BY_MT5"
    )
    currency: CurrencyCode = Field(repr=False)
    leverage: int = Field(gt=0, le=100000, repr=False)
    owner_readonly_selection_ref: Label = Field(repr=False)
    terminal_path_hash: Digest = Field(repr=False)
    profile_path_hash: Digest = Field(repr=False)

    @model_validator(mode="after")
    def known_owner_metadata(self) -> Self:
        unknown = {"UNKNOWN", "UNAVAILABLE", "NONE", "NULL", "UNSPECIFIED", "NA"}
        if any(
            value.upper() in unknown
            for value in (self.assigned_server, self.account_type, self.currency)
        ):
            raise Ds03AuthorityError()
        return self

    @property
    def login_digest(self) -> str:
        return hashlib.sha256(str(self.login).encode("ascii")).hexdigest()

    @property
    def server_digest(self) -> str:
        return hashlib.sha256(self.assigned_server.encode("ascii")).hexdigest()

    @property
    def account_ref(self) -> str:
        return "ds03.account." + self.login_digest

    @property
    def server_ref(self) -> str:
        return "ds03.server." + self.server_digest


class Ds03RuntimeBinding(Contract):
    release_sha: GitSHA
    release_tree: GitSHA
    connector_source_hash: Digest
    interpreter_hash: Digest
    package_version: Literal["5.0.6231"] = PACKAGE_VERSION
    wheel_hash: Literal["3a8c8349ce691a4ef05e314afc034ad82f4dbb19415efc7442af5ea075d5e797"] = (
        WHEEL_HASH
    )
    package_manifest_hash: Digest
    terminal_binary_hash: Digest
    terminal_build: int = Field(ge=4755, le=1000000)
    terminal_version: Label
    fixed_runtime_path_hash: Digest
    fixed_terminal_path_hash: Digest
    fixed_profile_path_hash: Digest
    profile_identity_hash: Digest

    @model_validator(mode="after")
    def known_terminal_version(self) -> Self:
        if self.terminal_version.upper() in {
            "UNKNOWN",
            "UNAVAILABLE",
            "NONE",
            "NULL",
            "UNSPECIFIED",
            "NA",
        }:
            raise Ds03AuthorityError()
        return self


class Ds03OnboardingAuthority(Contract):
    authority_id: Identifier
    scope: Literal["DS03_DEMO_READONLY_ONBOARDING"] = "DS03_DEMO_READONLY_ONBOARDING"
    mode: Literal["DEMO"] = "DEMO"
    runtime: Ds03RuntimeBinding
    metadata_hash: Digest
    account_digest: Digest
    server_digest: Digest
    account_type: Label = Field(repr=False)
    account_type_source: Literal["OWNER_METADATA_ONLY_NOT_EXPOSED_BY_MT5"] = (
        "OWNER_METADATA_ONLY_NOT_EXPOSED_BY_MT5"
    )
    currency: CurrencyCode = Field(repr=False)
    leverage: int = Field(gt=0, le=100000, repr=False)
    rights_hash: Digest
    rights_valid_until: UTCTime
    credential_purpose: Literal["auvexo-alpha:phase2:ds03:mt5-demo-readonly-password:v1"] = (
        CREDENTIAL_PURPOSE
    )
    credential_version: Literal["1"] = "1"
    credential_kind: Literal["MT5_DEMO_READONLY_ACCESS_PASSWORD"] = (
        "MT5_DEMO_READONLY_ACCESS_PASSWORD"
    )
    owner_readonly_selection_ref: Label
    repository: Literal["haseeb1229/auvexo-alpha"] = "haseeb1229/auvexo-alpha"
    repository_visibility: Literal["PRIVATE"] = "PRIVATE"
    private_attested_at: UTCTime
    authorized_at: UTCTime
    expires_at: UTCTime
    owner_authorization_ref: Label

    @model_validator(mode="after")
    def bounded_authority(self) -> Self:
        if not (
            self.private_attested_at
            <= self.authorized_at
            < self.expires_at
            <= self.rights_valid_until
            and self.expires_at - self.authorized_at <= timedelta(hours=24)
            and self.authorized_at - self.private_attested_at <= timedelta(hours=24)
        ):
            raise Ds03AuthorityError()
        return self


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise Ds03AuthorityError()
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise Ds03AuthorityError()


def decode_metadata(raw: bytes) -> Ds03LocalMetadata:
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= 4096:
            raise Ds03AuthorityError()
        json.loads(raw, object_pairs_hook=_unique, parse_constant=_constant)
        return Ds03LocalMetadata.model_validate_json(raw)
    except Exception:
        raise Ds03AuthorityError() from None


def decode_authority(raw: bytes) -> Ds03OnboardingAuthority:
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= 16384:
            raise Ds03AuthorityError()
        json.loads(raw, object_pairs_hook=_unique, parse_constant=_constant)
        return Ds03OnboardingAuthority.model_validate_json(raw)
    except Exception:
        raise Ds03AuthorityError() from None


@dataclass(frozen=True, repr=False)
class Ds03AuthorityAdmission:
    """Static admission only; grants no observed account or source qualification.

    The accepted digest is an independently supplied trust input, never an issuer.
    Same-owner code/OS compromise remains outside this process boundary.
    """

    authority: Ds03OnboardingAuthority = field(repr=False)
    accepted_digest: str = field(repr=False)
    binding: Ds03RuntimeBinding = field(repr=False)

    def verify(self, now: datetime) -> None:
        try:
            if (
                type(self.authority) is not Ds03OnboardingAuthority
                or type(self.binding) is not Ds03RuntimeBinding
                or type(self.accepted_digest) is not str
                or not hmac.compare_digest(self.authority.content_hash(), self.accepted_digest)
                or self.authority.runtime != self.binding
            ):
                raise Ds03AuthorityError()
            Ds03OnboardingAuthority.model_validate_json(self.authority.canonical_bytes())
            Ds03RuntimeBinding.model_validate_json(self.binding.canonical_bytes())
            current = utc_time(now)
            if not (
                self.authority.private_attested_at
                <= self.authority.authorized_at
                <= current
                < self.authority.expires_at
                <= self.authority.rights_valid_until
                and current - self.authority.private_attested_at <= timedelta(hours=24)
            ):
                raise Ds03AuthorityError()
        except Exception:
            raise Ds03AuthorityError() from None

    def require_metadata(self, metadata: Ds03LocalMetadata) -> None:
        try:
            if type(metadata) is not Ds03LocalMetadata:
                raise Ds03AuthorityError()
            decode_metadata(metadata.canonical_bytes())
            expected = self.authority
            if (
                expected.metadata_hash != metadata.content_hash()
                or expected.account_digest != metadata.login_digest
                or expected.server_digest != metadata.server_digest
                or expected.account_type != metadata.account_type
                or expected.account_type_source != metadata.account_type_source
                or expected.currency != metadata.currency
                or expected.leverage != metadata.leverage
                or expected.owner_readonly_selection_ref != metadata.owner_readonly_selection_ref
                or self.binding.fixed_terminal_path_hash != metadata.terminal_path_hash
                or self.binding.fixed_profile_path_hash != metadata.profile_path_hash
            ):
                raise Ds03AuthorityError()
        except Exception:
            raise Ds03AuthorityError() from None

    def bind_metadata(
        self, metadata: Ds03LocalMetadata, *, now: datetime
    ) -> Ds03OnboardingAdmission:
        try:
            self.verify(now)
            self.require_metadata(metadata)
            result = Ds03OnboardingAdmission(
                self.authority, self.accepted_digest, self.binding, metadata
            )
            result.verify(now)
            return result
        except Exception:
            raise Ds03AuthorityError() from None


@dataclass(frozen=True, repr=False)
class Ds03OnboardingAdmission(Ds03AuthorityAdmission):
    metadata: Ds03LocalMetadata = field(repr=False)

    def verify(self, now: datetime) -> None:
        super().verify(now)
        self.require_metadata(self.metadata)


def admit_authority(
    authority: Ds03OnboardingAuthority,
    *,
    independently_accepted_digest: str,
    binding: Ds03RuntimeBinding,
    now: datetime,
) -> Ds03AuthorityAdmission:
    try:
        admission = Ds03AuthorityAdmission(authority, independently_accepted_digest, binding)
        admission.verify(now)
        return admission
    except Exception:
        raise Ds03AuthorityError() from None


def admit_onboarding(
    authority: Ds03OnboardingAuthority,
    *,
    independently_accepted_digest: str,
    metadata: Ds03LocalMetadata,
    binding: Ds03RuntimeBinding,
    now: datetime,
) -> Ds03OnboardingAdmission:
    return admit_authority(
        authority,
        independently_accepted_digest=independently_accepted_digest,
        binding=binding,
        now=now,
    ).bind_metadata(metadata, now=now)
