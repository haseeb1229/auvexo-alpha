"""Read-only presentation assembly. Routes never query tables."""

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Final, Literal

from fastapi import APIRouter

from auvexo_alpha import __version__
from auvexo_alpha.application.ports import ReadinessProbe
from auvexo_alpha.application.terminal_models import (
    Freshness,
    JournalView,
    PaperView,
    QualificationView,
    ResearchView,
    ReviewedSummary,
    SystemView,
    TerminalSnapshot,
)
from auvexo_alpha.application.terminal_reads import TerminalReadPort
from auvexo_alpha.config import Settings
from auvexo_alpha.domain.contracts import Mode

_LOGGER = logging.getLogger(__name__)
# Presentation labels exist only for modes Settings accepts; any other mode fails closed.
_MODE_LABELS: Final[Mapping[Mode, Literal["RESEARCH", "BACKTEST", "PAPER"]]] = MappingProxyType(
    {Mode.RESEARCH: "RESEARCH", Mode.BACKTEST: "BACKTEST", Mode.PAPER: "PAPER"}
)


def _guarded[T](view: str, read: Callable[[], T], fallback: Callable[[], T]) -> T:
    """One failing read must not blank the other views; system health always renders."""
    try:
        return read()
    except Exception as error:
        # Presentation-only boundary. Log the fixed view name and the exception class,
        # never its message, arguments, headers, tokens or raw driver detail.
        _LOGGER.error(
            "PRESENTATION_VIEW_UNAVAILABLE view=%s error_class=%s", view, type(error).__name__
        )
        return fallback()


def _unavailable() -> Freshness:
    return Freshness(state="UNAVAILABLE", provenance="LOCAL_DIAGNOSTICS", reason="READ_UNAVAILABLE")


def terminal_router(
    settings: Settings, probe: ReadinessProbe, reads: TerminalReadPort
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/terminal")

    def database() -> Literal["READY", "NOT_READY"]:
        return "READY" if probe.ready() else "NOT_READY"

    def system() -> SystemView:
        return SystemView(
            version=__version__,
            mode=_MODE_LABELS[settings.mode],
            database=_guarded("database", database, lambda: "NOT_READY"),
            freshness=Freshness(
                state="AVAILABLE",
                observed_at=datetime.now(UTC),
                provenance="LOCAL_DIAGNOSTICS",
                reason="CURRENT",
            ),
        )

    def qualification(now: datetime) -> QualificationView:
        return _guarded(
            "qualification",
            lambda: reads.qualification(now=now),
            lambda: QualificationView(freshness=_unavailable()),
        )

    def paper(now: datetime) -> PaperView:
        return _guarded(
            "paper", lambda: reads.paper(now=now), lambda: PaperView(freshness=_unavailable())
        )

    def journal(now: datetime) -> JournalView:
        return _guarded(
            "journal",
            lambda: reads.journal(now=now),
            lambda: JournalView(freshness=_unavailable()),
        )

    @router.get("/system", response_model=SystemView)
    def system_view() -> SystemView:
        return system()

    @router.get("/qualification", response_model=QualificationView)
    def qualification_view() -> QualificationView:
        return qualification(datetime.now(UTC))

    @router.get("/reviewed", response_model=ReviewedSummary)
    def reviewed_view() -> ReviewedSummary:
        return ReviewedSummary()

    @router.get("/paper", response_model=PaperView)
    def paper_view() -> PaperView:
        return paper(datetime.now(UTC))

    @router.get("/research", response_model=ResearchView)
    def research_view() -> ResearchView:
        return ResearchView()

    @router.get("/journal", response_model=JournalView)
    def journal_view() -> JournalView:
        return journal(datetime.now(UTC))

    @router.get("/snapshot", response_model=TerminalSnapshot)
    def snapshot() -> TerminalSnapshot:
        now = datetime.now(UTC)
        return TerminalSnapshot(
            system=system(),
            qualification=qualification(now),
            paper=paper(now),
            research=ResearchView(),
            journal=journal(now),
        )

    return router
