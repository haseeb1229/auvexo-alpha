"""Owner-confirmed rights reviews for the public Binance spot sources, oldest first.

A review is in force from its review instant until its due date. Every past review stays
here byte-identical, because stored manifests embed the review they were received under.
A later review continues an earlier one only if it keeps exactly the same permitted use,
redistribution and retention: data received under the earlier review may then be used
for research while the later review is in force. Nothing here confers trading,
commercial, live-execution or redistribution rights beyond what each record states.
"""

from datetime import UTC, datetime
from typing import Final, Literal

from auvexo_alpha.domain.market_data import SourceRights

PublicSource = Literal["DS-01", "DS-02"]

VISION_TERMS = (
    "https://raw.githubusercontent.com/binance/binance-public-data/master/TERMS_AND_CONDITIONS.md"
)
MARKET_DATA_FAQ = "https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/faqs/market_data_only.md"
LEGACY_TERMS_PAGE = "https://www.binance.com/en/about-legal/terms"
# The Terms of Use (effective 2026-10-27) as the official PDF the terms page embeds; the
# file name is its own SHA-256.
TERMS_OF_USE = (
    "https://bin.bnbstatic.com/static/cms/cg08ou2ak0tn7mcplvfg/file/"
    "f7c3c8a8fbda48eaa272ff503b8c2e54c6c98ad4f0f2a1e5da3667af5962c7de.pdf"
)
PROHIBITED_USE = "https://www.binance.com/en/about-legal/prohibited-use-policy"
RETENTION = (
    "Private nonproduction research only; review before removal; no commercial/live-use entitlement"
)
PERSONAL_RESEARCH: Final = "PERSONAL_NONPRODUCTION_RESEARCH"

# Owner confirmation of option R1 in the 2026-11-13 Binance owner packet, given on
# 2026-11-14 at 23:07 Asia/Karachi.
RENEWED_AT = datetime(2026, 11, 14, 18, 7, tzinfo=UTC)
RENEWED_UNTIL = datetime(2027, 2, 16, tzinfo=UTC)

REVIEWS: dict[PublicSource, tuple[SourceRights, ...]] = {
    "DS-01": (
        SourceRights(
            source_id="DS-01",
            version="review.2026-10-17.v2",
            reviewed_at=datetime(2026, 10, 17, tzinfo=UTC),
            review_due=datetime(2026, 11, 16, tzinfo=UTC),
            evidence_urls=(VISION_TERMS, LEGACY_TERMS_PAGE, MARKET_DATA_FAQ),
            terms_hash="99c4921dbe023cd68c1a447775707d621453cc78aec6ac0bfe2e6c06a5114ee0",
            permitted_use=PERSONAL_RESEARCH,
            redistribution="CC-BY-NC-SA-4.0",
            retention=RETENTION,
        ),
        SourceRights(
            source_id="DS-01",
            version="review.2026-11-14.v1",
            reviewed_at=RENEWED_AT,
            review_due=RENEWED_UNTIL,
            evidence_urls=(VISION_TERMS, TERMS_OF_USE, PROHIBITED_USE),
            terms_hash="99c4921dbe023cd68c1a447775707d621453cc78aec6ac0bfe2e6c06a5114ee0",
            permitted_use=PERSONAL_RESEARCH,
            redistribution="CC-BY-NC-SA-4.0",
            retention=RETENTION,
        ),
    ),
    "DS-02": (
        SourceRights(
            source_id="DS-02",
            version="review.2026-10-16.v1",
            reviewed_at=datetime(2026, 10, 16, tzinfo=UTC),
            review_due=datetime(2026, 11, 16, tzinfo=UTC),
            evidence_urls=(VISION_TERMS, LEGACY_TERMS_PAGE, MARKET_DATA_FAQ),
            terms_hash="bf4879710c904b991848972ec4818ba2cf9e4ce314c09adae84fa2750d3477f7",
            permitted_use=PERSONAL_RESEARCH,
            redistribution="NOT_AUTHORIZED",
            retention=RETENTION,
        ),
        SourceRights(
            source_id="DS-02",
            version="review.2026-11-14.v1",
            reviewed_at=RENEWED_AT,
            review_due=RENEWED_UNTIL,
            evidence_urls=(TERMS_OF_USE, PROHIBITED_USE, MARKET_DATA_FAQ),
            terms_hash="f7c3c8a8fbda48eaa272ff503b8c2e54c6c98ad4f0f2a1e5da3667af5962c7de",
            permitted_use=PERSONAL_RESEARCH,
            redistribution="NOT_AUTHORIZED",
            retention=RETENTION,
        ),
    ),
}


def review_at(source_id: PublicSource, at: datetime) -> SourceRights:
    """The latest review made at or before `at`; its own window then decides validity."""
    made = [r for r in REVIEWS[source_id] if r.reviewed_at <= at]
    return made[-1] if made else REVIEWS[source_id][0]


def continues_for_research(recorded: SourceRights, now: datetime) -> bool:
    """True if a recorded review's data may still be used for research at `now`.

    Either the recorded review itself is in force, or it is a review recorded here and
    the review in force now keeps exactly its use, redistribution and retention.
    """
    if recorded.source_id == "DS-03" or recorded not in REVIEWS[recorded.source_id]:
        return False
    current = review_at(recorded.source_id, now)
    try:
        current.require_research(now)
    except ValueError:
        return False
    return (
        current.permitted_use == recorded.permitted_use
        and current.redistribution == recorded.redistribution
        and current.retention == recorded.retention
    )
