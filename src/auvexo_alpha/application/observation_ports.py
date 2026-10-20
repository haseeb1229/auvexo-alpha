"""Narrow observation ports; only immutable domain values cross inward."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from auvexo_alpha.domain.market_data import Symbol
from auvexo_alpha.domain.observation import (
    ObservationConfig,
    ObservationDayReceipt,
    ObservationFact,
    ObservationProposalTrace,
    ObservationRunEvidence,
    ObservationSimulationTrace,
)
from auvexo_alpha.domain.paper import (
    PaperAccountSnapshot,
    PaperAuthorization,
    PaperDecision,
    PaperInstrumentSpec,
    PaperIntent,
    PaperMarketSnapshot,
    PaperPolicy,
    PaperReservation,
)
from auvexo_alpha.domain.paper_lifecycle import KillLevel, Release


class ObservationSourceUnavailable(Exception):
    """An expected provider/source outage; never identity, corruption or programmer errors."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class PaperSubmission(Protocol):
    @property
    def decision(self) -> PaperDecision: ...
    @property
    def authorization(self) -> PaperAuthorization | None: ...
    @property
    def reservation(self) -> PaperReservation | None: ...


@dataclass(frozen=True)
class ObservationRunStart:
    started_at: datetime


@dataclass(frozen=True)
class DecisionJournalEntry:
    kind: Literal["AUTHORIZED", "DENIED"]
    content_hash: str


@dataclass(frozen=True)
class ObservationSnapshot:
    final_account: PaperAccountSnapshot
    truth_cursor: int
    journal_tail_hash: str
    reservation_hashes: tuple[str, ...]
    outbox_hashes: tuple[str, ...]
    fill_hashes: tuple[str, ...]
    unknown_order_refs: tuple[str, ...]
    mismatch_refs: tuple[str, ...]


class ObservationFeedPort(Protocol):
    def require_ready(self, config: ObservationConfig, *, now: datetime) -> None: ...
    def next_observation(
        self, symbol: Symbol, *, window_start: datetime, window_end: datetime
    ) -> ObservationFact | None: ...


class ObservationPersistencePort(Protocol):
    def verify_schema(self) -> None: ...
    def begin(
        self, config_hash: str, *, kind: Literal["PREFLIGHT", "SCHEDULED"], now: datetime
    ) -> UUID: ...
    def started_run(self, run_id: UUID) -> ObservationRunStart: ...
    def pinned_release(self, config: ObservationConfig) -> Release: ...
    def append_feed(self, run_id: UUID, fact: ObservationFact, *, now: datetime) -> str: ...
    def append_trace(
        self, run_id: UUID, trace: ObservationProposalTrace, *, now: datetime
    ) -> str: ...
    def append_simulation(
        self, run_id: UUID, simulation: ObservationSimulationTrace, *, now: datetime
    ) -> str: ...
    def feeds(self, run_id: UUID) -> tuple[ObservationFact, ...]: ...
    def traces(self, run_id: UUID) -> tuple[ObservationProposalTrace, ...]: ...
    def simulations(self, run_id: UUID) -> tuple[ObservationSimulationTrace, ...]: ...
    def run_snapshot(self, run_id: UUID) -> ObservationSnapshot: ...
    def close(
        self, run_id: UUID, evidence: ObservationRunEvidence, *, now: datetime
    ) -> ObservationDayReceipt: ...


class PaperCommandPort(Protocol):
    def account(self, account_ref: str) -> PaperAccountSnapshot: ...
    def reservations(self, account_ref: str) -> tuple[PaperReservation, ...]: ...
    def acquire_writer(self, account_ref: str, *, now: datetime) -> int: ...
    def reconcile(self, account_ref: str, *, now: datetime) -> bool: ...
    def set_kill(
        self, account_ref: str, level: KillLevel, *, actor: str, now: datetime
    ) -> None: ...
    def authorize(
        self,
        intent: PaperIntent,
        policy: PaperPolicy,
        market: PaperMarketSnapshot,
        spec: PaperInstrumentSpec,
        release: Release,
        *,
        now: datetime,
    ) -> PaperSubmission: ...
    def last_decision(self, account_ref: str) -> DecisionJournalEntry: ...


class PaperTruthPort(Protocol):
    def mark(self, account_ref: str, market: PaperMarketSnapshot, *, now: datetime) -> None: ...


class CausalPaperSimulatorPort(Protocol):
    def recover_pending(
        self, account_ref: str, *, epoch: int, now: datetime
    ) -> tuple[str, ...]: ...
    def accept(
        self,
        intent: PaperIntent,
        submission: PaperSubmission,
        source: ObservationFact,
        *,
        epoch: int,
        now: datetime,
    ) -> None: ...
    def observe(
        self, fact: ObservationFact, *, now: datetime
    ) -> tuple[ObservationSimulationTrace, ...]: ...
