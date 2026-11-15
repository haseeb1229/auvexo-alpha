"""Reviewed source restrictions; this registry cannot confer trading eligibility.

The owner-confirmed reviews live in `domain.source_reviews`. Collection and observation
ask for the review made at or before their own instant, so data is always labelled with
the review it was received under, and an expired review refuses by design.
"""

from datetime import datetime

from auvexo_alpha.domain.contracts import utc_time
from auvexo_alpha.domain.market_data import SourceIdentity, SourceRights
from auvexo_alpha.domain.source_reviews import REVIEWS, PublicSource, review_at


def rights(source_id: PublicSource, at: datetime | None = None) -> SourceRights:
    """The review in force at `at`, or the latest review when no instant is given."""
    return REVIEWS[source_id][-1] if at is None else review_at(source_id, utc_time(at))


def identity(source_id: PublicSource, at: datetime | None = None) -> SourceIdentity:
    return SourceIdentity(
        source_id=source_id,
        provider="BINANCE",
        family="SPOT_ARCHIVE" if source_id == "DS-01" else "SPOT_REST",
        endpoint="https://data.binance.vision/data/spot"
        if source_id == "DS-01"
        else "https://data-api.binance.vision",
        rights_version=rights(source_id, at).version,
    )
