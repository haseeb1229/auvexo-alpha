"""Read-only presentation assembly. Routes never query tables."""

from datetime import UTC, datetime

from fastapi import APIRouter

from auvexo_alpha import __version__
from auvexo_alpha.application.ports import ReadinessProbe
from auvexo_alpha.application.terminal_models import (
    Freshness,
    JournalView,
    PaperView,
    QualificationView,
    ResearchView,
    SystemView,
    TerminalSnapshot,
)
from auvexo_alpha.application.terminal_reads import TerminalReadPort
from auvexo_alpha.config import Settings


def terminal_router(
    settings: Settings, probe: ReadinessProbe, reads: TerminalReadPort
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/terminal")

    def system() -> SystemView:
        return SystemView(
            version=__version__,
            mode=settings.mode.value,
            database="READY" if probe.ready() else "NOT_READY",
            freshness=Freshness(
                state="AVAILABLE",
                observed_at=datetime.now(UTC),
                provenance="LOCAL_DIAGNOSTICS",
                reason="CURRENT",
            ),
        )

    @router.get("/system", response_model=SystemView)
    def system_view() -> SystemView:
        return system()

    @router.get("/qualification", response_model=QualificationView)
    def qualification() -> QualificationView:
        return reads.qualification(now=datetime.now(UTC))

    @router.get("/paper", response_model=PaperView)
    def paper() -> PaperView:
        return reads.paper(now=datetime.now(UTC))

    @router.get("/research", response_model=ResearchView)
    def research() -> ResearchView:
        return ResearchView()

    @router.get("/journal", response_model=JournalView)
    def journal() -> JournalView:
        return reads.journal(now=datetime.now(UTC))

    @router.get("/snapshot", response_model=TerminalSnapshot)
    def snapshot() -> TerminalSnapshot:
        now = datetime.now(UTC)
        return TerminalSnapshot(
            system=system(),
            qualification=reads.qualification(now=now),
            paper=reads.paper(now=now),
            research=ResearchView(),
            journal=reads.journal(now=now),
        )

    return router
