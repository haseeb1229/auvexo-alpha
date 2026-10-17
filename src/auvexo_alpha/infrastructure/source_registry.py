"""Reviewed source restrictions; this registry cannot confer trading eligibility."""

from datetime import UTC, datetime
from typing import Literal

from auvexo_alpha.domain.market_data import SourceIdentity, SourceRights

TERMS = (
    "https://raw.githubusercontent.com/binance/binance-public-data/master/TERMS_AND_CONDITIONS.md"
)
REST = "https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/faqs/market_data_only.md"


def rights(source_id: Literal["DS-01", "DS-02"]) -> SourceRights:
    return SourceRights(
        source_id=source_id,
        version="review.2026-10-17.v2" if source_id == "DS-01" else "review.2026-10-16.v1",
        reviewed_at=datetime(2026, 10, 17 if source_id == "DS-01" else 16, tzinfo=UTC),
        review_due=datetime(2026, 11, 16, tzinfo=UTC),
        evidence_urls=(TERMS, "https://www.binance.com/en/about-legal/terms", REST),
        terms_hash="99c4921dbe023cd68c1a447775707d621453cc78aec6ac0bfe2e6c06a5114ee0"
        if source_id == "DS-01"
        else "bf4879710c904b991848972ec4818ba2cf9e4ce314c09adae84fa2750d3477f7",
        permitted_use="PERSONAL_NONPRODUCTION_RESEARCH",
        redistribution="CC-BY-NC-SA-4.0" if source_id == "DS-01" else "NOT_AUTHORIZED",
        retention="Private nonproduction research only; review before removal; "
        "no commercial/live-use entitlement",
    )


def identity(source_id: Literal["DS-01", "DS-02"]) -> SourceIdentity:
    return SourceIdentity(
        source_id=source_id,
        provider="BINANCE",
        family="SPOT_ARCHIVE" if source_id == "DS-01" else "SPOT_REST",
        endpoint="https://data.binance.vision/data/spot"
        if source_id == "DS-01"
        else "https://data-api.binance.vision",
        rights_version=rights(source_id).version,
    )
