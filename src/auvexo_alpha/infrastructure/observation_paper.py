"""Thin observation adapters; accepted PAPER store/truth own every invariant."""

from datetime import datetime
from typing import Literal, cast

from auvexo_alpha.application.observation_ports import DecisionJournalEntry, PaperSubmission
from auvexo_alpha.domain.paper import (
    PaperAccountSnapshot,
    PaperInstrumentSpec,
    PaperIntent,
    PaperMarketSnapshot,
    PaperPolicy,
    PaperReservation,
)
from auvexo_alpha.domain.paper_lifecycle import KillLevel, Release
from auvexo_alpha.infrastructure.paper_store import PaperStore
from auvexo_alpha.infrastructure.paper_truth import PaperTruth


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
