"""Thin delegates to accepted PAPER stores; no copied financial state machine."""

from datetime import datetime
from decimal import Decimal

from auvexo_alpha.application.gateway_ports import PendingOfflineAttempt
from auvexo_alpha.domain.paper import (
    PaperAuthorization,
    PaperInstrumentSpec,
    PaperIntent,
    PaperMarketSnapshot,
    PaperPolicy,
    PaperPosition,
)
from auvexo_alpha.domain.paper_lifecycle import KillLevel, Release
from auvexo_alpha.infrastructure.paper_store import PaperStore, Submission
from auvexo_alpha.infrastructure.paper_truth import PaperTruth


class OfflinePaperAdapter:
    def __init__(self, store: PaperStore) -> None:
        self.store = store

    def authorize(
        self,
        intent: PaperIntent,
        policy: PaperPolicy,
        market: PaperMarketSnapshot,
        spec: PaperInstrumentSpec,
        release: Release,
        *,
        now: datetime,
    ) -> Submission:
        return self.store.authorize(intent, policy, market, spec, release, now=now)

    def claim(
        self,
        intent_hash: str,
        epoch: int,
        *,
        now: datetime,
        authorization: PaperAuthorization,
    ) -> PaperAuthorization:
        return self.store.claim(intent_hash, epoch, now=now, authorization=authorization)

    def mark_unknown(self, intent_hash: str, epoch: int, *, now: datetime) -> None:
        self.store.mark_unknown(intent_hash, epoch, now=now)

    def reconcile(self, account_ref: str, *, now: datetime) -> bool:
        return self.store.reconcile(account_ref, now=now)

    def pending(self, account_ref: str) -> tuple[PendingOfflineAttempt, ...]:
        pending = []
        for event in self.store.journal(account_ref):
            if event["kind"] != "AUTHORIZED":
                continue
            intent_hash = str(event["intent_hash"])
            state = str(self.store.outbox(intent_hash)["state"])
            if state not in ("FILLED", "REJECTED", "CANCELED", "EXPIRED"):
                pending.append(PendingOfflineAttempt(intent_hash, state))
        return tuple(pending)

    def set_kill(
        self,
        account_ref: str,
        level: KillLevel,
        *,
        actor: str,
        now: datetime,
    ) -> None:
        self.store.set_kill(account_ref, level, actor=actor, now=now)


class OfflineTruthAdapter:
    def __init__(self, truth: PaperTruth) -> None:
        self.truth = truth

    def record_order(
        self,
        intent: PaperIntent,
        *,
        now: datetime,
        writer_epoch: int,
        quantity: Decimal,
        event_id: str,
    ) -> str:
        return self.truth.record_order(
            intent,
            now=now,
            writer_epoch=writer_epoch,
            quantity=quantity,
            event_id=event_id,
        )

    def mark(
        self,
        account_ref: str,
        market: PaperMarketSnapshot,
        *,
        now: datetime,
        event_id: str,
    ) -> str:
        return self.truth.mark(account_ref, market, now=now, event_id=event_id)

    def status(
        self,
        intent_hash: str,
        status: str,
        *,
        account_ref: str,
        now: datetime,
        event_id: str,
    ) -> str:
        return self.truth.status(
            intent_hash,
            status,
            account_ref=account_ref,
            now=now,
            event_id=event_id,
        )

    def fill(
        self,
        intent_hash: str,
        quantity: Decimal,
        price: Decimal,
        *,
        account_ref: str,
        now: datetime,
        event_id: str,
    ) -> str:
        return self.truth.fill(
            intent_hash,
            quantity,
            price,
            account_ref=account_ref,
            now=now,
            event_id=event_id,
        )

    def resolve(
        self,
        intent_hash: str,
        status: str,
        confirmed_filled_quantity: Decimal,
        *,
        account_ref: str,
        now: datetime,
        evidence_hash: str,
        event_id: str,
    ) -> str:
        return self.truth.resolve(
            intent_hash,
            status,
            confirmed_filled_quantity,
            account_ref=account_ref,
            now=now,
            evidence_hash=evidence_hash,
            event_id=event_id,
        )

    def external_position(
        self,
        account_ref: str,
        position: PaperPosition,
        *,
        now: datetime,
        event_id: str,
    ) -> str:
        return self.truth.external_position(account_ref, position, now=now, event_id=event_id)
