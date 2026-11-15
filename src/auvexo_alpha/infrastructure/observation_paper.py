"""Thin observation adapters; accepted PAPER store/truth own every invariant."""

from datetime import datetime
from typing import Literal, cast

from auvexo_alpha.application.observation_ports import (
    DecisionJournalEntry,
    JournalFact,
    PaperSubmission,
)
from auvexo_alpha.domain.observation import ObservationStandingResumeUse
from auvexo_alpha.domain.paper import (
    PaperAccountSnapshot,
    PaperInstrumentSpec,
    PaperIntent,
    PaperMarketSnapshot,
    PaperPolicy,
    PaperReservation,
)
from auvexo_alpha.domain.paper_lifecycle import KillLevel, Release
from auvexo_alpha.infrastructure.paper_store import PROJECTION_EVENTS, PaperStore
from auvexo_alpha.infrastructure.paper_truth import PaperTruth, canonical_payload


class ObservationPaperCommands:
    def __init__(self, paper: PaperStore) -> None:
        self.paper = paper

    def account(self, account_ref: str) -> PaperAccountSnapshot:
        return self.paper.account(account_ref)

    def reservations(self, account_ref: str) -> tuple[PaperReservation, ...]:
        return self.paper.reservations(account_ref)

    def acquire_writer(self, account_ref: str, *, now: datetime) -> int:
        return self.paper.acquire_writer(account_ref, now=now)

    def reconcile(self, account_ref: str, *, now: datetime) -> bool:
        return self.paper.reconcile(account_ref, now=now)

    def roll_flat_boundary(self, account_ref: str, *, now: datetime) -> None:
        # The writer epoch is the one acquire_writer recorded on this same store.
        self.paper.roll_flat_boundary(account_ref, now=now)

    def journal_facts(self, account_ref: str) -> tuple[JournalFact, ...]:
        return tuple(
            JournalFact(
                kind=str(event["kind"]),
                content_hash=str(event["content_hash"]),
                recorded_at=event["recorded_at"],
                account=PaperAccountSnapshot.model_validate_json(
                    canonical_payload(event["data"]["account"])
                )
                if event["kind"] in PROJECTION_EVENTS
                else None,
            )
            for event in self.paper.journal(account_ref)
        )

    def ledger_mismatch_count(self, account_ref: str) -> int:
        return self.paper.ledger_replay(account_ref).mismatch_count

    def standing_resume(
        self, account_ref: str, use: ObservationStandingResumeUse, *, actor: str, now: datetime
    ) -> None:
        self.paper.resume(account_ref, actor=actor, now=now, standing_use=use)

    def set_kill(self, account_ref: str, level: KillLevel, *, actor: str, now: datetime) -> None:
        self.paper.set_kill(account_ref, level, actor=actor, now=now)

    def authorize(
        self,
        intent: PaperIntent,
        policy: PaperPolicy,
        market: PaperMarketSnapshot,
        spec: PaperInstrumentSpec,
        release: Release,
        *,
        now: datetime,
    ) -> PaperSubmission:
        return self.paper.authorize(intent, policy, market, spec, release, now=now)

    def last_decision(self, account_ref: str) -> DecisionJournalEntry:
        event = self.paper.journal(account_ref)[-1]
        if event["kind"] not in ("AUTHORIZED", "DENIED"):
            raise ValueError("OBSERVATION_PROPOSAL_JOURNAL_MISSING")
        return DecisionJournalEntry(
            cast(Literal["AUTHORIZED", "DENIED"], event["kind"]), str(event["content_hash"])
        )


class ObservationPaperTruth:
    def __init__(self, truth: PaperTruth) -> None:
        self.truth = truth

    def mark(self, account_ref: str, market: PaperMarketSnapshot, *, now: datetime) -> None:
        self.truth.mark(account_ref, market, now=now)

    def observe_spec(self, account_ref: str, spec: PaperInstrumentSpec, *, now: datetime) -> None:
        self.truth.observe_spec(account_ref, spec, now=now)
