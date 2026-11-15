"""Narrow observation ports; only immutable domain values cross inward."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from auvexo_alpha.domain.market_data import Symbol
from auvexo_alpha.domain.observation import (
    ObservationClockGate,
    ObservationClockProof,
    ObservationConfig,
    ObservationDayReceipt,
    ObservationFact,
    ObservationProposalTrace,
    ObservationProvenance,
    ObservationRunEvidence,
    ObservationSimulationTrace,
    ObservationSpecCheck,
    ObservationStandingResume,
    ObservationStandingResumeUse,
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
    # The server's Asia/Karachi date of `started_at`: the run's window day and receipt date.
    local_day: str


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
    # Campaign v2 only: derived by the store, never supplied by the runner.
    day_roll_hash: str | None = None
    terminal_authorization_count: int | None = None
    ledger_mismatch_count: int | None = None


@dataclass(frozen=True)
class JournalFact:
    """One verified journal event as the standing-resume rule reads it (OBV2-01)."""

    kind: str
    content_hash: str
    recorded_at: datetime
    account: PaperAccountSnapshot | None


@dataclass(frozen=True)
class StandingAuthorityRecord:
    """The START record's standing authority, verified by the store against activation."""

    activation_id: str
    authority: ObservationStandingResume
    authority_hash: str


@dataclass(frozen=True)
class PriorRun:
    """The latest earlier run of this campaign after START; `receipt` None = never closed."""

    receipt: ObservationDayReceipt | None
    receipt_hash: str | None


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
    # Campaign v2 standing resume inputs (OBV2-01).
    def run_activation(self, run_id: UUID) -> str | None: ...
    def standing_authority(self, config_hash: str) -> StandingAuthorityRecord | None: ...
    def prior_run(self, run_id: UUID) -> PriorRun | None: ...


class ObservationGatesPort(Protocol):
    """Campaign v2 run-start gates: scheduler provenance, clock and provider specs."""

    def provenance(self, *, window_start: datetime, window_end: datetime) -> ObservationProvenance:
        """Read-only; never raises for a missing or disabled log, it reports UNVERIFIABLE."""
        ...

    def clock(self) -> ObservationClockGate:
        """Windows Time status and one provider-time proof; outage raises unavailable."""
        ...

    def provider_time(self) -> ObservationClockProof: ...
    def spec(self, symbol: Symbol) -> ObservationSpecCheck: ...


class PaperCommandPort(Protocol):
    def account(self, account_ref: str) -> PaperAccountSnapshot: ...
    def reservations(self, account_ref: str) -> tuple[PaperReservation, ...]: ...
    def acquire_writer(self, account_ref: str, *, now: datetime) -> int: ...
    def reconcile(self, account_ref: str, *, now: datetime) -> bool: ...
    # Campaign v2 (ADR-032 OBV2-01, OBV2-02, OBV2-11).
    def roll_flat_boundary(self, account_ref: str, *, now: datetime) -> None: ...
    def journal_facts(self, account_ref: str) -> tuple[JournalFact, ...]: ...
    def ledger_mismatch_count(self, account_ref: str) -> int: ...
    def standing_resume(
        self, account_ref: str, use: ObservationStandingResumeUse, *, actor: str, now: datetime
    ) -> None: ...
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
    def observe_spec(
        self, account_ref: str, spec: PaperInstrumentSpec, *, now: datetime
    ) -> None: ...


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
    # Records simulated truth only; the runner reconciles once the bar's pair is marked.
    def observe(
        self, fact: ObservationFact, *, now: datetime
    ) -> tuple[ObservationSimulationTrace, ...]: ...
