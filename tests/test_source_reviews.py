"""Owner-confirmed DS-01/DS-02 rights reviews: history kept exactly, renewal continues scope."""

from datetime import UTC, datetime, timedelta

import pytest

from auvexo_alpha.domain.market_data import SourceRights
from auvexo_alpha.domain.source_reviews import (
    RENEWED_AT,
    RENEWED_UNTIL,
    REVIEWS,
    continues_for_research,
    review_at,
)
from auvexo_alpha.infrastructure.source_registry import identity, rights

# Content hashes of the records the registry returned before the 2026-11-14 renewal
# (computed from the previous source_registry.py). Stored manifests embed these records,
# so they must never change.
PRIOR_RIGHTS = {
    "DS-01": "17eeafd65047796f0824374836c52ed1714b142f3be8f15a0084a9095beef117",
    "DS-02": "0ce629e1089e6cc7e4c7663d4efc20583d37bb3361eb32dea5e5939161a0a0f1",
}
PRIOR_IDENTITY = {
    "DS-01": "0054fdb519982648a9fc431f39381f8718f4a239ed4ceb415662388fc9e41b7d",
    "DS-02": "c74b92a8a9e8b87cc3d82d3ab8a520f806546c4614b25d53dd835fe679826913",
}
OLD_DUE = datetime(2026, 11, 16, tzinfo=UTC)


@pytest.mark.parametrize("source", ["DS-01", "DS-02"])
def test_prior_review_records_are_byte_identical(source: str) -> None:
    prior = REVIEWS[source][0]
    assert prior.content_hash() == PRIOR_RIGHTS[source]
    before_renewal = datetime(2026, 11, 1, tzinfo=UTC)
    assert rights(source, before_renewal) == prior
    assert identity(source, before_renewal).content_hash() == PRIOR_IDENTITY[source]


@pytest.mark.parametrize("source", ["DS-01", "DS-02"])
def test_renewal_keeps_scope_and_only_extends_time(source: str) -> None:
    prior, renewed = REVIEWS[source]
    assert renewed.reviewed_at == RENEWED_AT == datetime(2026, 11, 14, 18, 7, tzinfo=UTC)
    assert renewed.review_due == RENEWED_UNTIL == datetime(2027, 2, 16, tzinfo=UTC)
    assert renewed.permitted_use == prior.permitted_use == "PERSONAL_NONPRODUCTION_RESEARCH"
    assert renewed.redistribution == prior.redistribution
    assert renewed.retention == prior.retention
    assert renewed.version != prior.version
    assert rights(source) == renewed
    assert identity(source).rights_version == renewed.version


def test_renewal_evidence_is_the_retrieved_documents() -> None:
    ds01, ds02 = REVIEWS["DS-01"][-1], REVIEWS["DS-02"][-1]
    # DS-01 terms unchanged by hash; DS-02 now rests on the retrieved Terms of Use PDF.
    assert ds01.terms_hash == REVIEWS["DS-01"][0].terms_hash
    assert ds02.terms_hash == "f7c3c8a8fbda48eaa272ff503b8c2e54c6c98ad4f0f2a1e5da3667af5962c7de"
    assert any(ds02.terms_hash in url for url in ds02.evidence_urls)
    assert ds01.redistribution == "CC-BY-NC-SA-4.0" and ds02.redistribution == "NOT_AUTHORIZED"


def test_review_in_force_is_chosen_by_instant() -> None:
    before = RENEWED_AT - timedelta(microseconds=1)
    assert review_at("DS-02", before) == REVIEWS["DS-02"][0]
    assert review_at("DS-02", RENEWED_AT) == REVIEWS["DS-02"][1]
    # Before any review, the first record is returned and its own window refuses.
    early = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="SOURCE_RIGHTS_BLOCKED_OR_EXPIRED"):
        rights("DS-02", early).require_research(early)


def test_collection_refuses_after_the_renewal_expires() -> None:
    with pytest.raises(ValueError, match="SOURCE_RIGHTS_BLOCKED_OR_EXPIRED"):
        rights("DS-02", RENEWED_UNTIL).require_research(RENEWED_UNTIL)
    last = RENEWED_UNTIL - timedelta(microseconds=1)
    rights("DS-02", last).require_research(last)


@pytest.mark.parametrize("source", ["DS-01", "DS-02"])
def test_data_under_the_prior_review_continues_only_while_renewal_is_in_force(
    source: str,
) -> None:
    prior = REVIEWS[source][0]
    with pytest.raises(ValueError):
        prior.require_research(OLD_DUE)
    assert continues_for_research(prior, OLD_DUE)
    assert continues_for_research(prior, RENEWED_UNTIL - timedelta(microseconds=1))
    assert not continues_for_research(prior, RENEWED_UNTIL)


def test_unrecorded_or_widened_rights_never_continue() -> None:
    prior = REVIEWS["DS-02"][0]
    for change in (
        {"version": "review.forged.v1"},
        {"review_due": datetime(2030, 1, 1, tzinfo=UTC)},
        {"redistribution": "CC-BY-NC-SA-4.0"},
        {"terms_hash": "0" * 64},
    ):
        forged = SourceRights.model_validate(prior.model_dump() | change)
        assert not continues_for_research(forged, OLD_DUE), change
    ds03 = SourceRights.model_validate(prior.model_dump() | {"source_id": "DS-03"})
    assert not continues_for_research(ds03, OLD_DUE)
