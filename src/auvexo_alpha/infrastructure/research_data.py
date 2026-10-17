"""Hash-verified, eligibility-checked, sealed-split reader for the research worker."""

from datetime import datetime

from auvexo_alpha.application.research_simulator import validate_prices
from auvexo_alpha.domain.market_data import Candle
from auvexo_alpha.infrastructure.data_store import DataStore, read_bars
from auvexo_alpha.infrastructure.research_ledger import ResearchLedger


class ResearchDataReader:
    def __init__(self, ledger: ResearchLedger, store: DataStore) -> None:
        self.ledger, self.store = ledger, store

    def read(self, study_id: str, phase: str, start: datetime, end: datetime) -> list[Candle]:
        study = self.ledger.authorize_read(study_id, phase, start, end)
        relevant = [
            item
            for item in study.inputs
            if item.manifest.coverage.requested_start < end
            and start < item.manifest.coverage.requested_end
        ]
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
        return bars
