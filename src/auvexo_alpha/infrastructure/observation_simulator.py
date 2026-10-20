"""Concrete causal PAPER adapter; accepted stores own truth and reconciliation."""

from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from auvexo_alpha.application.observation_ports import PaperSubmission
from auvexo_alpha.application.observation_simulator import (
    SIMULATOR_VERSION,
    PendingSimulation,
    causal_fill_price,
)
from auvexo_alpha.domain.observation import (
    ObservationFact,
    ObservationSimulationTrace,
    observation_market,
)
from auvexo_alpha.domain.paper import PaperIntent
from auvexo_alpha.infrastructure.paper_store import PaperStore
from auvexo_alpha.infrastructure.paper_truth import PaperTruth


class CausalPaperSimulator:
    def __init__(self, paper: PaperStore, truth: PaperTruth) -> None:
        self.paper, self.truth = paper, truth
        self.pending: dict[str, PendingSimulation] = {}

    def recover_pending(self, account_ref: str, *, epoch: int, now: datetime) -> tuple[str, ...]:
        """Restart never resubmits or invents the lost simulator's pending outcome."""
        unresolved: list[str] = []
        for event in self.paper.journal(account_ref):
            if event["kind"] != "AUTHORIZED":
                continue
            ih = str(event["intent_hash"])
            state = str(self.paper.outbox(ih)["state"])
            if state in ("FILLED", "REJECTED", "CANCELED", "EXPIRED"):
                continue
            unresolved.append(ih)
            if state != "RESERVED":
                self.paper.mark_unknown(ih, epoch, now=now)
                self.truth.status(ih, "UNKNOWN", account_ref=account_ref, now=now)
        return tuple(unresolved)

    def accept(
        self,
        intent: PaperIntent,
        submission: PaperSubmission,
        source: ObservationFact,
        *,
        epoch: int,
        now: datetime,
    ) -> None:
        if submission.decision.status != "APPROVED" or submission.authorization is None:
            raise ValueError("OBSERVATION_SIMULATOR_APPROVAL_REQUIRED")
        ih = intent.content_hash()
        if ih in self.pending or source.candle.instrument_id != intent.instrument_id:
            raise ValueError("OBSERVATION_SIMULATOR_IDENTITY_DENIED")
        if now < source.candle.availability.available_at:
            raise ValueError("OBSERVATION_FILL_CAUSALITY_DENIED")
        auth = self.paper.claim(ih, epoch, now=now, authorization=submission.authorization)
        try:
            self.truth.record_order(
                intent, now=now, writer_epoch=epoch, quantity=auth.exposure.quantity
            )
            self.truth.status(ih, "ACKNOWLEDGED", account_ref=intent.account_ref, now=now)
            self.paper.reconcile(intent.account_ref, now=now)
        except (ValueError, OSError):
            self.paper.mark_unknown(ih, epoch, now=now)
            raise
        self.pending[ih] = PendingSimulation(intent, source, auth.exposure.quantity)

    def observe(
        self, fact: ObservationFact, *, now: datetime
    ) -> tuple[ObservationSimulationTrace, ...]:
        fills: list[ObservationSimulationTrace] = []
        for ih, pending in tuple(self.pending.items()):
            if pending.intent.instrument_id != fact.candle.instrument_id:
                continue
            if fact.candle.end_at <= pending.source.candle.end_at:
                continue
            price = causal_fill_price(pending, fact, now=now)
            if now >= pending.intent.expires_at:
                self.truth.status(ih, "EXPIRED", account_ref=pending.intent.account_ref, now=now)
                del self.pending[ih]
            elif price is not None:
                self.truth.mark(pending.intent.account_ref, observation_market(fact), now=now)
                event_id = uuid5(NAMESPACE_URL, SIMULATOR_VERSION + ih + fact.content_hash())
                self.truth.fill(
                    ih,
                    pending.quantity,
                    price,
                    account_ref=pending.intent.account_ref,
                    now=now,
                    event_id=str(event_id),
                )
                fills.append(
                    ObservationSimulationTrace(
                        label="SIMULATED",
                        version=SIMULATOR_VERSION,
                        intent_hash=ih,
                        proposal_source_hash=pending.source.content_hash(),
                        fill_source_hash=fact.content_hash(),
                        truth_event_id=event_id,
                        quantity=pending.quantity,
                        price=price,
                        observed_at=now,
                    )
                )
                del self.pending[ih]
            self.paper.reconcile(pending.intent.account_ref, now=now)
        return tuple(fills)
