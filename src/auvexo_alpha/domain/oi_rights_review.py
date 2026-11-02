"""Externally accepted same-evidence OI review continuity; no receipt or rights issuer.

The immutable accepted base rights snapshot is never changed or extended. A supplied
receipt chain can authorize only its exact existing scope, after independent external
acceptance. Late reviews leave permanent gaps; new evidence requires a separate scope.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Self

from pydantic import model_validator

from auvexo_alpha.domain.contracts import Contract, Digest, Label, UTCTime, utc_time
from auvexo_alpha.domain.open_interest import (
    OI_EVIDENCE_URLS,
    OI_PROCEDURES_HASH,
    OI_RULES_HASH,
    OI_TERMS_HASH,
    OIRights,
)


class OIReviewContinuation(Contract):
    kind: Literal["DS04_A1_SAME_EVIDENCE_CONTINUATION"] = "DS04_A1_SAME_EVIDENCE_CONTINUATION"
    base_rights_hash: Digest
    previous_review_hash: Digest
    source_hash: Digest
    terms_hash: Digest = OI_TERMS_HASH
    procedures_hash: Digest = OI_PROCEDURES_HASH
    rules_hash: Digest = OI_RULES_HASH
    evidence_urls: tuple[str, ...] = OI_EVIDENCE_URLS
    symbols: tuple[Literal["BTCUSDT"], Literal["ETHUSDT"]] = ("BTCUSDT", "ETHUSDT")
    permitted_use: Literal["PERSONAL_NONCOMMERCIAL_NONPRODUCTION_RESEARCH"] = (
        "PERSONAL_NONCOMMERCIAL_NONPRODUCTION_RESEARCH"
    )
    redistribution: Literal["NOT_AUTHORIZED"] = "NOT_AUTHORIZED"
    live_promotion: Literal["NOT_AUTHORIZED"] = "NOT_AUTHORIZED"
    same_scope: Literal[True] = True
    same_evidence: Literal[True] = True
    reviewed_at: UTCTime
    accepted_at: UTCTime
    next_review_due: UTCTime
    review_ref: Label
    independent_acceptance_ref: Label

    @model_validator(mode="after")
    def same_accepted_evidence(self) -> Self:
        if (
            self.terms_hash != OI_TERMS_HASH
            or self.procedures_hash != OI_PROCEDURES_HASH
            or self.rules_hash != OI_RULES_HASH
            or self.evidence_urls != OI_EVIDENCE_URLS
            or type(self.same_scope) is not bool
            or not self.same_scope
            or type(self.same_evidence) is not bool
            or not self.same_evidence
            or self.reviewed_at > self.accepted_at
            or self.next_review_due <= self.accepted_at
        ):
            raise ValueError("OI_REVIEW_SCOPE_OR_CHRONOLOGY")
        return self


@dataclass(frozen=True)
class OIReviewAuthority:
    """An externally admitted chain, not an issuer or a claimed cryptographic signature.

    accepted_digests must come from the separately accepted owner/reviewer authority
    channel. Computing them from unreviewed files does not create independent acceptance.
    The local-owner compromise limit is identical to other existing START contracts.
    """

    base: OIRights
    chain: tuple[OIReviewContinuation, ...]
    accepted_digests: tuple[str, ...]
    now: datetime

    def __post_init__(self) -> None:
        base = OIRights.model_validate(self.base.model_dump(mode="python"))
        if base.revoked:
            raise ValueError("OI_RIGHTS_REVOKED")
        if not isinstance(self.chain, tuple) or not 1 <= len(self.chain) <= 256:
            raise ValueError("OI_REVIEW_CHAIN_REQUIRED_OR_BUDGET")
        chain = tuple(
            OIReviewContinuation.model_validate(receipt.model_dump(mode="python"))
            for receipt in self.chain
        )
        hashes = tuple(receipt.content_hash() for receipt in chain)
        if (
            not isinstance(self.accepted_digests, tuple)
            or len(set(hashes)) != len(hashes)
            or len(set(self.accepted_digests)) != len(self.accepted_digests)
            or hashes != self.accepted_digests
        ):
            raise ValueError("OI_REVIEW_EXTERNAL_ACCEPTANCE_REQUIRED")
        at = utc_time(self.now)
        previous_hash = base.content_hash()
        previous_due = base.review_due
        previous_reviewed = base.reviewed_at
        previous_accepted = base.reviewed_at
        for receipt in chain:
            effective_at = max(previous_due, receipt.accepted_at)
            if (
                receipt.base_rights_hash != base.content_hash()
                or receipt.previous_review_hash != previous_hash
                or receipt.source_hash != base.source.content_hash()
                or receipt.reviewed_at < previous_reviewed
                or receipt.accepted_at < previous_accepted
                or receipt.accepted_at > at
                or receipt.next_review_due <= effective_at
            ):
                raise ValueError("OI_REVIEW_CHAIN_INVALID")
            previous_hash = receipt.content_hash()
            previous_due = receipt.next_review_due
            previous_reviewed = receipt.reviewed_at
            previous_accepted = receipt.accepted_at
        object.__setattr__(self, "base", base)
        object.__setattr__(self, "chain", chain)
        object.__setattr__(self, "now", at)

    def receipt_hash_at(self, at: datetime) -> str | None:
        at = utc_time(at)
        if self.base.revoked:
            raise ValueError("OI_RIGHTS_REVOKED")
        if self.base.reviewed_at <= at < self.base.review_due:
            return None
        previous_due = self.base.review_due
        for receipt in self.chain:
            effective_at = max(previous_due, receipt.accepted_at)
            if previous_due <= at < effective_at:
                raise ValueError("OI_REVIEW_GAP_BLOCKED")
            if effective_at <= at < receipt.next_review_due:
                return receipt.content_hash()
            previous_due = receipt.next_review_due
        raise ValueError("OI_RIGHTS_BLOCKED_OR_EXPIRED")

    def require(self, at: datetime) -> None:
        self.receipt_hash_at(at)

    def chain_hash(self) -> str:
        payload = {
            "kind": "oi-review-chain.v1",
            "base_rights_hash": self.base.content_hash(),
            "accepted_receipt_hashes": self.accepted_digests,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
        ).hexdigest()


def require_oi_rights(
    rights: OIRights,
    at: datetime,
    authority: OIReviewAuthority | None = None,
) -> None:
    checked = OIRights.model_validate(rights.model_dump(mode="python"))
    if checked.revoked:
        raise ValueError("OI_RIGHTS_REVOKED")
    if authority is None:
        checked.require_research(at)
        return
    if (
        not isinstance(authority, OIReviewAuthority)
        or authority.base.content_hash() != checked.content_hash()
    ):
        raise ValueError("OI_REVIEW_BASE_MISMATCH")
    authority.require(at)
