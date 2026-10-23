"""Narrow query ports; no database/provider/financial commands in application."""

from datetime import datetime
from typing import Protocol

from auvexo_alpha.application.terminal_models import (
    Freshness,
    JournalView,
    PaperView,
    QualificationView,
)


class TerminalReadPort(Protocol):
    def qualification(self, *, now: datetime) -> QualificationView: ...
    def paper(self, *, now: datetime) -> PaperView: ...
    def journal(self, *, now: datetime) -> JournalView: ...


class UnconnectedTerminalReads:
    """Explicit missing integration, never fake successful operational data."""

    @staticmethod
    def freshness() -> Freshness:
        return Freshness(state="UNKNOWN", provenance="UNCONNECTED", reason="NOT_CONNECTED")

    def qualification(self, *, now: datetime) -> QualificationView:
        return QualificationView(freshness=self.freshness())

    def paper(self, *, now: datetime) -> PaperView:
        return PaperView(freshness=self.freshness())

    def journal(self, *, now: datetime) -> JournalView:
        return JournalView(freshness=self.freshness())
