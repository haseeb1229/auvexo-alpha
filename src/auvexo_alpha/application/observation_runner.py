"""Bounded observation orchestration; PREPARED campaigns cannot start."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Event
from typing import Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from auvexo_alpha.application.observation_gates import (
    clock_refusals,
    observed_specs,
    plan_standing_resume,
    provider_interval,
    spec_refusals,
)
from auvexo_alpha.application.observation_ports import (
    CausalPaperSimulatorPort,
    ObservationFeedPort,
    ObservationGatesPort,
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
    ObservationClockGate,
    ObservationClockProof,
    ObservationConfig,
    ObservationDayReceipt,
    ObservationFact,
    ObservationProposalTrace,
    ObservationProvenance,
    ObservationResources,
    ObservationRunEvidence,
    ObservationSpecCheck,
    observation_market,
    observation_policy,
    observation_window,
)
from auvexo_alpha.domain.paper import PaperInstrumentSpec
from auvexo_alpha.domain.paper_lifecycle import KillLevel

_STABLE_CODE = re.compile(r"[A-Z][A-Z0-9_]{2,63}")
RunKind = Literal["PREFLIGHT", "SCHEDULED"]


def resource_actions(resource: ObservationResources, *, healthy: bool) -> tuple[str, ...]:
    actions = tuple(
        "PAUSE_NEW_ENTRIES" if action == "PAUSE_ENTRIES" else action
        for action in observation_resource_actions(resource)
    )
    if not healthy and "PAUSE_NEW_ENTRIES" not in actions:
        actions += ("PAUSE_NEW_ENTRIES",)
    return actions


def failure_reason(error: Exception) -> str:
    """Receipt label for a failed run: the type and a project code, never exception text.

    Arbitrary messages can hold local paths, SQL or credential context, so only a bare
    UPPER_SNAKE code is carried. A non-empty reason can only make a date INCOMPLETE.
    """
    code = str(error)
    suffix = "." + code if _STABLE_CODE.fullmatch(code) else ""
    return ("observation.run.failed." + type(error).__name__ + suffix)[:96]


@dataclass
class _Progress:
    """Run facts that the final receipt binds, kept where a failure path can read them."""

    fenced: bool = False
    recovery_pending: tuple[str, ...] = ()
    samples: list[ObservationResources] = field(default_factory=list)
    feed_failed: bool = False
    feed_gap: bool = False
    research_pause_unconfirmed: bool = False
    # Campaign v2 start gates and refusals (ADR-032); each refusal is an operational
    # reason, so a refused night can only evaluate INCOMPLETE.
    refusals: tuple[str, ...] = ()
    provenance: ObservationProvenance | None = None
    clock_gate: ObservationClockGate | None = None
    closing_clock: ObservationClockProof | None = None
    spec_checks: tuple[ObservationSpecCheck, ...] = ()
    window_completed: bool = False


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
        gates: ObservationGatesPort,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        cancel: Event | None = None,
        resources: Callable[[datetime], ObservationResources],
        pause_optional_research: Callable[[], bool] | None = None,
    ) -> None:
        if not config.is_v2:
            # v1 configurations and receipts stay readable; v1 can begin nothing (ADR-032).
            raise ValueError("OBSERVATION_CAMPAIGN_VERSION_RETIRED")
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
        self.gates = gates

    def run(self, *, kind: RunKind = "SCHEDULED") -> ObservationDayReceipt:
        now = utc_time(self.clock())
        self.observations.verify_schema()
        # Server activation/schema/window checks happen before any feed or writer action.
        run_id = self.observations.begin(self.config.content_hash(), kind=kind, now=now)
        progress = _Progress()
        try:
            self._observe(run_id, kind, now, progress)
            return self._close(run_id, kind, progress, ())
        except Exception as error:
            # A started date gets exactly one further close, carrying the failure as a
            # reason that can only evaluate INCOMPLETE. The original error still propagates;
            # if this close fails too, that failure surfaces with the original as context.
            self._close(run_id, kind, progress, (failure_reason(error),))
            raise

    def _start_gates(
        self, kind: RunKind, started_at: datetime, window_start: datetime, progress: _Progress
    ) -> bool:
        """OBV2-06 provenance, OBV2-05 clock and OBV2-04 specifications, before any writer."""
        if kind == "SCHEDULED":
            lateness = timedelta(seconds=self.config.max_start_lateness_seconds)
            progress.provenance = self.gates.provenance(
                window_start=window_start, window_end=window_start + lateness
            )
            if progress.provenance.status != "VERIFIED":
                progress.refusals += (
                    "observation.provenance." + progress.provenance.status.lower(),
                )
                return False
        try:
            progress.clock_gate = self.gates.clock()
        except ObservationSourceUnavailable:
            progress.refusals += ("observation.clock.unavailable",)
            return False
        failed = clock_refusals(
            progress.clock_gate,
            self.config,
            started_at=started_at,
            window_start=window_start,
            scheduled=kind == "SCHEDULED",
        )
        if failed:
            progress.refusals += tuple("observation.clock.untrusted." + name for name in failed)
            return False
        try:
            progress.spec_checks = tuple(
                self.gates.spec(cast(Symbol, symbol)) for symbol in OBSERVATION_SYMBOLS
            )
        except ObservationSourceUnavailable:
            progress.refusals += ("observation.spec.unavailable",)
            return False
        failed = spec_refusals(self.config, progress.spec_checks)
        if failed:
            progress.refusals += tuple("observation.spec.drift." + name for name in failed)
            return False
        return True

    def _roll(self, now: datetime, progress: _Progress) -> bool:
        """OBV2-02 flat-boundary roll; a refusal is journaled with K1 by the kernel."""
        try:
            self.paper.roll_flat_boundary(self.config.account_ref, now=now)
        except ValueError as error:
            code = str(error)
            if code == "UTC_DAY_NOT_ADVANCED":
                # Already rolled for this UTC day, or never rollable today; the store
                # derives `day_rolled` for the receipt from the journal either way.
                return True
            if not code.startswith("FLAT_BOUNDARY_ROLL_REFUSED:"):
                raise
            progress.refusals += tuple(
                "observation.day_roll.refused." + reason
                for reason in code.split(":", 1)[1].split(",")
                if _STABLE_CODE.fullmatch(reason)
            ) or ("observation.day_roll.refused",)
            return False
        return True

    def _record_specs(self, specs: tuple[PaperInstrumentSpec, ...]) -> None:
        """Record each pinned specification as observed at provider time (OBV2-04)."""
        for spec in specs:
            # A provider time slightly ahead of the local clock is never recorded early.
            while (now := utc_time(self.clock())) < spec.observed_at:
                if self.cancel.wait(min(1.0, (spec.observed_at - now).total_seconds())):
                    raise ValueError("OBSERVATION_RUN_CANCELLED")
            self.truth.observe_spec(self.config.account_ref, spec, now=now)
        self.paper.reconcile(self.config.account_ref, now=utc_time(self.clock()))

    def _standing_resume(self, run_id: UUID, local_day: str, progress: _Progress) -> None:
        """OBV2-01: clear exactly the writer-acquisition K1, or record why not."""
        account_ref = self.config.account_ref
        now = utc_time(self.clock())
        self.paper.reconcile(account_ref, now=now)
        record = self.observations.standing_authority(self.config.content_hash())
        decision = plan_standing_resume(
            self.config,
            record,
            run_id=run_id,
            run_activation_id=self.observations.run_activation(run_id),
            local_day=local_day,
            prior=self.observations.prior_run(run_id),
            journal=self.paper.journal_facts(account_ref),
            account=self.paper.account(account_ref),
            ledger_mismatch_count=self.paper.ledger_mismatch_count(account_ref),
            now=now,
        )
        if record is None or isinstance(decision, tuple):
            codes = decision if isinstance(decision, tuple) else ("NO_STANDING_AUTHORITY",)
            progress.refusals += tuple(
                "observation.standing_resume.refused." + code for code in codes
            )
            return
        self.paper.standing_resume(
            account_ref, decision, actor=record.authority.owner, now=utc_time(self.clock())
        )

    def _window_open(self, window_end: datetime, progress: _Progress) -> bool:
        """Local time, and provider time as estimated at the start gate, before the end."""
        now = utc_time(self.clock())
        if progress.clock_gate is None:
            return now < window_end
        return now < window_end or provider_interval(progress.clock_gate.provider, now)[0] < (
            window_end
        )

    def _observe(self, run_id: UUID, kind: RunKind, now: datetime, progress: _Progress) -> None:
        start = self.observations.started_run(run_id)
        started_at, local_day = utc_time(start.started_at), start.local_day
        window_start, window_end = observation_window(local_day)
        release = self.observations.pinned_release(self.config)
        if not self._start_gates(kind, started_at, window_start, progress):
            return
        account_ref = self.config.account_ref
        epoch = self.paper.acquire_writer(account_ref, now=now)
        progress.fenced = True
        progress.recovery_pending = self.simulator.recover_pending(
            account_ref, epoch=epoch, now=now
        )
        self.paper.reconcile(account_ref, now=now)
        if not self._roll(utc_time(self.clock()), progress):
            return
        specs = observed_specs(self.config, progress.spec_checks)
        self._record_specs(specs)
        if kind == "SCHEDULED":
            self._standing_resume(run_id, local_day, progress)
        self.feed.require_ready(self.config, now=utc_time(self.clock()))
        policy = observation_policy(self.config)
        paired: dict[datetime, dict[str, ObservationFact]] = {}
        planned: set[str] = set()
        previous_pair: datetime | None = None
        while (
            not progress.feed_failed
            and not self.cancel.is_set()
            and self._window_open(window_end, progress)
        ):
            for symbol in OBSERVATION_SYMBOLS:
                try:
                    fact = self.feed.next_observation(
                        cast(Symbol, symbol), window_start=window_start, window_end=window_end
                    )
                except ObservationSourceUnavailable:
                    progress.feed_failed = True
                    break
                if fact is None:
                    continue
                now = utc_time(self.clock())
                validate_observation_fact(self.config, fact, local_day=local_day, now=now)
                self.observations.append_feed(run_id, fact, now=now)
                # OBV2-07: every market used to authorize or to value is a stored truth
                # mark, consumed by the reconciliation below before any authorization.
                self.truth.mark(account_ref, observation_market(fact, self.config), now=now)
                for fill in self.simulator.observe(fact, now=now):
                    self.observations.append_simulation(run_id, fill, now=now)
                pair = paired.setdefault(fact.candle.end_at, {})
                if symbol in pair:
                    raise ValueError("OBSERVATION_DUPLICATE_PAIRED_FACT")
                pair[symbol] = fact
                if set(pair) != set(OBSERVATION_SYMBOLS):
                    continue
                # One reconciliation per completed pair, after both symbols are marked for
                # the same bar end. Each position is valued at its own latest mark, so a
                # reconciliation between the two marks would value the other symbol on the
                # previous bar, past the 60 s bound (OBV2-03), and pause with K1. Facts
                # simulated against either bar of the pair are consumed here, before any
                # decision below.
                now = utc_time(self.clock())
                self.paper.reconcile(account_ref, now=now)
                if (
                    previous_pair is not None
                    and (fact.candle.end_at - previous_pair).total_seconds()
                    > self.config.max_gap_seconds
                ):
                    progress.feed_gap = True
                    current = self.paper.account(account_ref)
                    self.paper.set_kill(
                        account_ref,
                        max(current.kill, KillLevel.K1),
                        actor="deterministic.observation.source_gap",
                        now=now,
                    )
                previous_pair = fact.candle.end_at
                resource = self.resources(now)
                progress.samples.append(resource)
                account = self.paper.account(account_ref)
                actions = resource_actions(
                    resource, healthy=account.journal_healthy and not account.unknown_orders
                )
                if "PAUSE_OPTIONAL_RESEARCH" in actions:
                    if (
                        self.pause_optional_research is None
                        or self.pause_optional_research() is not True
                    ):
                        progress.research_pause_unconfirmed = True
                        actions += ("PAUSE_NEW_ENTRIES",)
                if "PAUSE_NEW_ENTRIES" in actions:
                    self.paper.set_kill(
                        account_ref,
                        max(account.kill, KillLevel.K1),
                        actor="deterministic.observation.resource_pause",
                        now=now,
                    )
                for paired_fact in pair.values():
                    # STORE_VERIFIED binds each decision's time to the database clock.
                    now = utc_time(self.clock())
                    account = self.paper.account(account_ref)
                    reservations = self.paper.reservations(account_ref)
                    intent = plan_observation_intent(
                        self.config,
                        paired_fact,
                        account,
                        release,
                        now=now,
                        reservations=reservations,
                        specs=specs,
                    )
                    if intent is None or intent.content_hash() in planned:
                        continue
                    planned.add(intent.content_hash())
                    market = observation_market(paired_fact, self.config)
                    spec = next(s for s in specs if s.instrument_id == intent.instrument_id)
                    submission = self.paper.authorize(
                        intent, policy, market, spec, release, now=now
                    )
                    event = self.paper.last_decision(account_ref)
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
        progress.window_completed = not progress.feed_failed and not self.cancel.is_set()

    def _close(
        self,
        run_id: UUID,
        kind: RunKind,
        progress: _Progress,
        failure: tuple[str, ...],
    ) -> ObservationDayReceipt:
        """Bind current reconciled state into one receipt; any `failure` forces INCOMPLETE."""
        if progress.window_completed and not failure:
            # OBV2-05 end guard: the close is checked in provider time as well.
            try:
                progress.closing_clock = self.gates.provider_time()
            except ObservationSourceUnavailable:
                progress.refusals += ("observation.clock.closing_unavailable",)
        now = utc_time(self.clock())
        if progress.fenced:
            # Without this run's writer fence nothing is reconciled on its behalf; the
            # store then refuses a closure that is not the current reconciled state.
            self.paper.reconcile(self.config.account_ref, now=now)
        start = self.observations.started_run(run_id)
        started_at = utc_time(start.started_at)
        window_start, _ = observation_window(start.local_day)
        state = self.observations.run_snapshot(run_id)
        evidence = ObservationRunEvidence(
            run_id=run_id,
            campaign_id=self.config.campaign_id,
            local_day=start.local_day,
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
            operational_reasons=progress.refusals
            + tuple("recovery.pending." + ih for ih in progress.recovery_pending)
            + (("observation.feed.unavailable",) if progress.feed_failed else ())
            + (("observation.feed.gap",) if progress.feed_gap else ())
            + (
                ("observation.research.pause_unconfirmed",)
                if progress.research_pause_unconfirmed
                else ()
            )
            + failure,
            resource_snapshots=tuple(progress.samples),
            provenance=progress.provenance,
            clock_gate=progress.clock_gate,
            closing_clock=progress.closing_clock,
            spec_checks=progress.spec_checks,
            day_roll_hash=state.day_roll_hash,
            terminal_authorization_count=state.terminal_authorization_count,
            ledger_mismatch_count=state.ledger_mismatch_count,
        )
        return self.observations.close(run_id, evidence, now=now)
