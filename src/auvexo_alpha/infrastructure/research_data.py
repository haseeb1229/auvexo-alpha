"""Hash-verified, eligibility-checked, sealed-split reader for the research worker."""

from dataclasses import dataclass
from datetime import datetime

from auvexo_alpha.application.research_simulator import validate_prices
from auvexo_alpha.domain.market_data import Candle
from auvexo_alpha.infrastructure.data_store import DataStore, read_bars
from auvexo_alpha.infrastructure.research_ledger import ResearchLedger


@dataclass(frozen=True)
class ResearchRead:
    """Bars served under one logged read receipt, with the digest the ledger recorded."""

    bars: list[Candle]
    digest: str


class ResearchDataReader:
    def __init__(self, ledger: ResearchLedger, store: DataStore) -> None:
        self.ledger, self.store = ledger, store

    def read(self, study_id: str, phase: str, start: datetime, end: datetime) -> ResearchRead:
        authorized = self.ledger.authorize_read(study_id, phase, start, end)
        study = authorized.study
        relevant = [
            item
            for item in study.inputs
            if item.manifest.coverage.requested_start < end
            and start < item.manifest.coverage.requested_end
        ]
        versions = {item.manifest.dataset_version for item in relevant}
        # A recorded archive/REST disagreement on a bar this read would serve is unresolved
        # truth: refuse rather than silently using either side.
        if any(
            versions & {conflict.archive_version, conflict.rest_version}
            for conflict in self.store.conflicts(study.instrument, study.timeframe, start, end)
        ):
            raise ValueError("CROSS_SOURCE_CONFLICT_UNRESOLVED")
        bars: list[Candle] = []
        for item in relevant:
            self.store.verify(item.manifest)
            bars.extend(
                b
                for b in read_bars(self.store.path(item.manifest))
                if start <= b.open_at and b.end_at <= end
            )
        bars.sort(key=lambda b: b.open_at)
        outages = tuple(
            o
            for item in relevant
            for o in item.outages
            if o.source_manifest == item.manifest.dataset_version
        )
        validate_prices(bars, outages)
        if bars[0].open_at != start or bars[-1].end_at != end:
            raise ValueError("INCOMPLETE_REGISTERED_RESEARCH_RANGE")
        return ResearchRead(bars, self.ledger.bind_read(authorized, bars))
