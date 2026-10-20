"""Future bounded observation orchestration; PREPARED campaigns cannot start."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from threading import Event
from typing import Literal, cast
from uuid import NAMESPACE_URL, uuid5

from auvexo_alpha.application.observation_ports import (
    CausalPaperSimulatorPort,
    ObservationFeedPort,
    ObservationPersistencePort,
    ObservationSourceUnavailable,
    PaperCommandPort,
    PaperTruthPort,
)
from auvexo_alpha.application.observation_qualification import (
    observation_resource_actions,
    plan_observation_intent,
    validate_observation_fact,
)
from auvexo_alpha.domain.contracts import utc_time
from auvexo_alpha.domain.market_data import Symbol
from auvexo_alpha.domain.observation import (
    OBSERVATION_SYMBOLS,
    ObservationConfig,
    ObservationDayReceipt,
    ObservationFact,
    ObservationProposalTrace,
    ObservationResources,
    ObservationRunEvidence,
    observation_market,
    observation_policy,
    observation_window,
)
from auvexo_alpha.domain.paper_lifecycle import KillLevel


def resource_actions(resource: ObservationResources, *, healthy: bool) -> tuple[str, ...]:
    actions = tuple(
        "PAUSE_NEW_ENTRIES" if action == "PAUSE_ENTRIES" else action
        for action in observation_resource_actions(resource)
    )
    if not healthy and "PAUSE_NEW_ENTRIES" not in actions:
        actions += ("PAUSE_NEW_ENTRIES",)
    return actions


class ObservationRunner:
    def __init__(
        self,
        config: ObservationConfig,
        observations: ObservationPersistencePort,
        paper: PaperCommandPort,
        truth: PaperTruthPort,
        feed: ObservationFeedPort,
        *,
        simulator: CausalPaperSimulatorPort,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        cancel: Event | None = None,
        resources: Callable[[datetime], ObservationResources],
        pause_optional_research: Callable[[], bool] | None = None,
    ) -> None:
        self.config, self.observations, self.paper, self.truth, self.feed = (
            config,
            observations,
            paper,
            truth,
            feed,
        )
        self.clock, self.cancel = clock, cancel or Event()
        self.resources = resources
        self.pause_optional_research = pause_optional_research
        self.simulator = simulator

    def run(
        self, *, kind: Literal["PREFLIGHT", "SCHEDULED"] = "SCHEDULED"
    ) -> ObservationDayReceipt:
        now = utc_time(self.clock())
        self.observations.verify_schema()
        # Server activation/schema/window checks happen before any feed or writer action.
        run_id = self.observations.begin(self.config.content_hash(), kind=kind, now=now)
        started_at = utc_time(self.observations.started_run(run_id).started_at)
        window_start, window_end = observation_window(started_at.date())
        release = self.observations.pinned_release(self.config)
        epoch = self.paper.acquire_writer(self.config.account_ref, now=now)
        recovery_pending = self.simulator.recover_pending(
            self.config.account_ref, epoch=epoch, now=now
        )
        self.paper.reconcile(self.config.account_ref, now=now)
        self.feed.require_ready(self.config, now=now)
        samples: list[ObservationResources] = []
        paired: dict[datetime, dict[str, ObservationFact]] = {}
        planned: set[str] = set()
        feed_failed = False
        feed_gap = False
        research_pause_unconfirmed = False
        previous_pair: datetime | None = None
        while not feed_failed and not self.cancel.is_set() and utc_time(self.clock()) < window_end:
            for symbol in OBSERVATION_SYMBOLS:
                try:
                    fact = self.feed.next_observation(
                        cast(Symbol, symbol), window_start=window_start, window_end=window_end
                    )
                except ObservationSourceUnavailable:
                    feed_failed = True
                    break
                if fact is None:
                    continue
                now = utc_time(self.clock())
                validate_observation_fact(
                    self.config, fact, local_day=started_at.date().isoformat(), now=now
                )
                self.observations.append_feed(run_id, fact, now=now)
                for fill in self.simulator.observe(fact, now=now):
                    self.observations.append_simulation(run_id, fill, now=now)
                account = self.paper.account(self.config.account_ref)
                if any(p.instrument_id == fact.candle.instrument_id for p in account.positions):
                    market = observation_market(fact)
                    if any(
                        p.instrument_id == fact.candle.instrument_id
                        and p.mark_snapshot_hash != market.content_hash()
                        for p in account.positions
                    ):
                        self.truth.mark(self.config.account_ref, market, now=now)
                self.paper.reconcile(self.config.account_ref, now=now)
                pair = paired.setdefault(fact.candle.end_at, {})
                if symbol in pair:
                    raise ValueError("OBSERVATION_DUPLICATE_PAIRED_FACT")
                pair[symbol] = fact
                if set(pair) != set(OBSERVATION_SYMBOLS):
                    continue
                if (
                    previous_pair is not None
                    and (fact.candle.end_at - previous_pair).total_seconds()
                    > self.config.max_gap_seconds
                ):
                    feed_gap = True
                    current = self.paper.account(self.config.account_ref)
                    self.paper.set_kill(
                        self.config.account_ref,
                        max(current.kill, KillLevel.K1),
                        actor="deterministic.observation.source_gap",
                        now=now,
                    )
                previous_pair = fact.candle.end_at
                resource = self.resources(now)
                samples.append(resource)
                account = self.paper.account(self.config.account_ref)
                actions = resource_actions(
                    resource, healthy=account.journal_healthy and not account.unknown_orders
                )
                if "PAUSE_OPTIONAL_RESEARCH" in actions:
                    if (
                        self.pause_optional_research is None
                        or self.pause_optional_research() is not True
                    ):
                        research_pause_unconfirmed = True
                        actions += ("PAUSE_NEW_ENTRIES",)
                if "PAUSE_NEW_ENTRIES" in actions:
                    self.paper.set_kill(
                        self.config.account_ref,
                        max(account.kill, KillLevel.K1),
                        actor="deterministic.observation.resource_pause",
                        now=now,
                    )
                for paired_fact in pair.values():
                    account = self.paper.account(self.config.account_ref)
                    reservations = self.paper.reservations(self.config.account_ref)
                    intent = plan_observation_intent(
                        self.config,
                        paired_fact,
                        account,
                        release,
                        now=now,
                        reservations=reservations,
                    )
                    if intent is None or intent.content_hash() in planned:
                        continue
                    planned.add(intent.content_hash())
                    market = observation_market(paired_fact)
                    spec = next(
                        s for s in self.config.specs if s.instrument_id == intent.instrument_id
                    )
                    submission = self.paper.authorize(
                        intent, observation_policy(self.config), market, spec, release, now=now
                    )
                    event = self.paper.last_decision(self.config.account_ref)
                    trace = ObservationProposalTrace(
                        proposal_id=uuid5(
                            NAMESPACE_URL, "observation.proposal." + intent.content_hash()
                        ),
                        source_observation_hash=paired_fact.content_hash(),
                        intent=intent,
                        decision=submission.decision,
                        account_before=account,
                        market=market,
                        spec=spec,
                        release=release,
                        authorization=submission.authorization,
                        reservation=submission.reservation,
                        prior_reservations=reservations,
                        journal_event_hash=event.content_hash,
                    )
                    self.observations.append_trace(run_id, trace, now=now)
                    if submission.decision.status == "APPROVED":
                        self.simulator.accept(intent, submission, paired_fact, epoch=epoch, now=now)
            self.cancel.wait(1)
        now = utc_time(self.clock())
        self.paper.reconcile(self.config.account_ref, now=now)
        state = self.observations.run_snapshot(run_id)
        evidence = ObservationRunEvidence(
            run_id=run_id,
            campaign_id=self.config.campaign_id,
            local_day=started_at.date().isoformat(),
            kind="SCHEDULED" if kind == "SCHEDULED" else "NON_COUNTING",
            scheduled_at=window_start,
            started_at=started_at,
            ended_at=now,
            config_hash=self.config.content_hash(),
            facts=self.observations.feeds(run_id),
            traces=self.observations.traces(run_id),
            simulation_traces=self.observations.simulations(run_id),
            final_account=state.final_account,
            truth_cursor=state.truth_cursor,
            journal_tail_hash=state.journal_tail_hash,
            reservation_hashes=state.reservation_hashes,
            outbox_hashes=state.outbox_hashes,
            fill_hashes=state.fill_hashes,
            unknown_order_refs=state.unknown_order_refs,
            mismatch_refs=state.mismatch_refs,
            operational_reasons=tuple("recovery.pending." + ih for ih in recovery_pending)
            + (("observation.feed.unavailable",) if feed_failed else ())
            + (("observation.feed.gap",) if feed_gap else ())
            + (("observation.research.pause_unconfirmed",) if research_pause_unconfirmed else ()),
            resource_snapshots=tuple(samples),
        )
        return self.observations.close(run_id, evidence, now=now)
