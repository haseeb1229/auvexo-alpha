"""Concrete campaign v2 start gates: scheduler log, Windows Time and provider facts."""

import hashlib
import subprocess
from collections.abc import Callable
from datetime import datetime

from auvexo_alpha.domain.market_data import Symbol
from auvexo_alpha.domain.observation import (
    ObservationClockGate,
    ObservationClockProof,
    ObservationProvenance,
    ObservationSpecCheck,
)
from auvexo_alpha.infrastructure.observation_feed import ObservationFeed
from auvexo_alpha.infrastructure.oi_runtime import diagnose_clock_status, read_clock_status
from auvexo_alpha.infrastructure.scheduler_provenance import current_provenance

PAPER_OBSERVATION_TASK = "\\AuvexoAlpha-Paper-Observation"


class ObservationStartGates:
    def __init__(
        self,
        feed: ObservationFeed,
        *,
        task_path: str = PAPER_OBSERVATION_TASK,
        clock_status: Callable[[], str] = read_clock_status,
        provenance: Callable[..., ObservationProvenance] = current_provenance,
    ) -> None:
        self.feed, self.task_path = feed, task_path
        self.clock_status, self._provenance = clock_status, provenance

    def provenance(self, *, window_start: datetime, window_end: datetime) -> ObservationProvenance:
        return self._provenance(self.task_path, window_start=window_start, window_end=window_end)

    def clock(self) -> ObservationClockGate:
        """The same read-only System32 status query and rules as the open-interest gate."""
        try:
            output = self.clock_status()
        except (OSError, ValueError, subprocess.SubprocessError):
            # An unreadable status has no passing input: every check below fails, so the
            # gate is recorded and refuses the night as CLOCK_UNTRUSTED.
            output = ""
        diagnosis = diagnose_clock_status(output, None)
        return ObservationClockGate(
            windows_time_hash=hashlib.sha256(output.encode("utf8")).hexdigest(),
            windows_checks=tuple((check.name, check.status) for check in diagnosis.checks),
            provider=self.feed.provider_time(),
        )

    def provider_time(self) -> ObservationClockProof:
        return self.feed.provider_time()

    def spec(self, symbol: Symbol) -> ObservationSpecCheck:
        return self.feed.spec(symbol)
