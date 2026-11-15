"""Pure campaign v2 gate rules (ADR-032 OBV2-01, OBV2-04, OBV2-05); no I/O."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from auvexo_alpha.application.observation_ports import (
    JournalFact,
    PriorRun,
    StandingAuthorityRecord,
)
from auvexo_alpha.domain.contracts import utc_time
from auvexo_alpha.domain.observation import (
    ObservationClockGate,
    ObservationClockProof,
    ObservationConfig,
    ObservationSpecCheck,
    ObservationStandingResumeUse,
    observation_clock_bound_ms,
    observation_policy,
    observed_spec,
    spec_drift,
)
from auvexo_alpha.domain.paper import PaperAccountSnapshot, PaperInstrumentSpec
from auvexo_alpha.domain.paper_lifecycle import KillLevel

# OBV2-05: the Windows Time inputs a PAPER v2 run requires. The open-interest gate's
# one-second dispersion bound is not applied; the provider offset bound is instead.
REQUIRED_WINDOWS_CHECKS = ("leap_indicator", "time_since_last_good_sync")
# Journal kinds a clean interval between the previous run's last reconciliation and this
# run's standing resume may contain. Anything else is a reason the owner must look first.
STANDING_RESUME_KINDS = frozenset(
    {"WRITER_ACQUIRED_PAUSE_NEW", "RECONCILIATION", "MARK_HEALTH", "FLAT_BOUNDARY_ROLL"}
)


def provider_interval(proof: ObservationClockProof, instant: datetime) -> tuple[datetime, datetime]:
    """Provider-time bounds of a local instant, from one measured request interval."""
    instant = utc_time(instant)
    return (
        instant + (proof.server_at - proof.received_at),
        instant + (proof.server_at - proof.sent_at),
    )


def clock_refusals(
    gate: ObservationClockGate,
    config: ObservationConfig,
    *,
    started_at: datetime,
    window_start: datetime,
    scheduled: bool,
) -> tuple[str, ...]:
    """Each failed OBV2-05 start condition by name; empty means the clock is trusted."""
    statuses = dict(gate.windows_checks)
    failed = [name for name in REQUIRED_WINDOWS_CHECKS if statuses.get(name) != "PASS"]
    proof = gate.provider
    if observation_clock_bound_ms(proof) > observation_policy(config).max_clock_offset_ms:
        failed.append("provider_offset_bound")
    if proof.sent_at < utc_time(started_at):
        failed.append("provider_before_run")
    if scheduled:
        low, high = provider_interval(proof, started_at)
        lateness = timedelta(seconds=config.max_start_lateness_seconds)
        if low < window_start or high > window_start + lateness:
            failed.append("provider_start_window")
    return tuple(failed)


def closing_clock_refusals(
    proof: ObservationClockProof | None,
    config: ObservationConfig,
    *,
    ended_at: datetime,
    window_end: datetime,
) -> tuple[str, ...]:
    """The end guard in provider time: the close lies in [end, end + grace] there too."""
    if proof is None:
        return ("closing_provider_time_missing",)
    failed = []
    if observation_clock_bound_ms(proof) > observation_policy(config).max_clock_offset_ms:
        failed.append("closing_offset_bound")
    if proof.received_at > utc_time(ended_at):
        failed.append("closing_proof_after_close")
    low, high = provider_interval(proof, ended_at)
    if low < window_end or high > window_end + timedelta(seconds=config.shutdown_grace_seconds):
        failed.append("provider_end_window")
    return tuple(failed)


def spec_refusals(
    config: ObservationConfig, checks: Sequence[ObservationSpecCheck]
) -> tuple[str, ...]:
    """`SYMBOL.term` for each drift, `SYMBOL.missing`/`.offset` for an unusable check."""
    failed: list[str] = []
    limit = observation_policy(config).max_clock_offset_ms
    for spec in config.specs:
        symbol = spec.instrument_id.rsplit(".", 1)[1]
        found = [check for check in checks if check.symbol == symbol]
        if len(found) != 1:
            failed.append(symbol + ".missing")
            continue
        failed.extend(symbol + "." + name for name in spec_drift(spec, found[0]))
        if found[0].bound_ms() > limit:
            failed.append(symbol + ".offset")
    return tuple(failed)


def observed_specs(
    config: ObservationConfig, checks: Sequence[ObservationSpecCheck]
) -> tuple[PaperInstrumentSpec, ...]:
    """The pinned specifications at provider time; refuses unless every term still holds."""
    if spec_refusals(config, checks):
        raise ValueError("SPEC_DRIFT")
    by_symbol: dict[str, ObservationSpecCheck] = {check.symbol: check for check in checks}
    return tuple(
        observed_spec(spec, by_symbol[spec.instrument_id.rsplit(".", 1)[1]])
        for spec in config.specs
    )


def plan_standing_resume(
    config: ObservationConfig,
    record: StandingAuthorityRecord | None,
    *,
    run_id: UUID,
    run_activation_id: str | None,
    local_day: str,
    prior: PriorRun | None,
    journal: Sequence[JournalFact],
    account: PaperAccountSnapshot,
    ledger_mismatch_count: int,
    now: datetime,
) -> ObservationStandingResumeUse | tuple[str, ...]:
    """OBV2-01: the facts one use relies on, or every reason it may not be used.

    The authority clears only the K1 a writer acquisition set, after a previous run that
    ended flat, reconciled, unkilled and with zero replay mismatches (or, on the first
    night, after START's audited resume), when today's flat-boundary roll is journaled
    and no other kind of event raised a kill since that boundary.
    """
    if record is None:
        return ("NO_STANDING_AUTHORITY",)
    authority = record.authority
    refused: list[str] = []
    if (
        authority.campaign_hash != config.content_hash()
        or authority.reviewed_sha != config.git_revision
    ):
        refused.append("AUTHORITY_CAMPAIGN_MISMATCH")
    if run_activation_id is None or run_activation_id != record.activation_id:
        refused.append("AUTHORITY_ACTIVATION_MISMATCH")
    if local_day > authority.valid_through:
        refused.append("AUTHORITY_EXPIRED")
    hashes = [fact.content_hash for fact in journal]
    boundary_kind: Literal["START_RESUME", "PREVIOUS_RECEIPT"]
    if prior is None:
        boundary_kind = "START_RESUME"
        boundary_hash = boundary_journal = authority.start_resume_event_hash
        index = hashes.index(boundary_journal) if boundary_journal in hashes else None
        if index is None or journal[index].kind != "OWNER_PAPER_RESUME":
            return (*refused, "START_RESUME_MISSING")
    else:
        receipt = prior.receipt
        if receipt is None or prior.receipt_hash is None:
            return (*refused, "PREVIOUS_RUN_NOT_CLOSED")
        boundary_kind, boundary_hash = "PREVIOUS_RECEIPT", prior.receipt_hash
        boundary_journal = receipt.journal_tail_hash
        if receipt.position_hashes:
            refused.append("PREVIOUS_NOT_FLAT")
        if not receipt.final_reconciled:
            refused.append("PREVIOUS_NOT_RECONCILED")
        if receipt.ledger_mismatch_count != 0:
            refused.append("PREVIOUS_LEDGER_MISMATCH_OR_UNMEASURED")
        if receipt.final_kill != KillLevel.K0:
            refused.append("PREVIOUS_KILL_RAISED")
        index = hashes.index(boundary_journal) if boundary_journal in hashes else None
        if index is None:
            return (*refused, "PREVIOUS_JOURNAL_TAIL_UNKNOWN")
    start = journal[index].account
    if start is None or start.kill != KillLevel.K0 or start.positions or not start.reconciled:
        refused.append("BOUNDARY_STATE_NOT_CLEAN")
    level = start.kill if start is not None else KillLevel.K4
    midnight = utc_time(now).replace(hour=0, minute=0, second=0, microsecond=0)
    roll: str | None = None
    examined = journal[index + 1 :]
    for fact in examined:
        if fact.kind not in STANDING_RESUME_KINDS:
            refused.append("EVENT_" + fact.kind)
            continue
        if fact.account is None:
            continue
        raised = fact.account.kill > level
        if raised and not (
            fact.kind == "WRITER_ACQUIRED_PAUSE_NEW" and fact.account.kill == KillLevel.K1
        ):
            refused.append("KILL_RAISED_BY_" + fact.kind)
        if fact.kind == "RECONCILIATION" and fact.account.unknown_orders:
            refused.append("UNKNOWN_ORDER_SINCE_BOUNDARY")
        if fact.kind == "FLAT_BOUNDARY_ROLL" and fact.account.day_start_at == midnight:
            roll = fact.content_hash
        level = max(level, fact.account.kill)
    if roll is None:
        refused.append("DAY_NOT_ROLLED")
    if account.kill != KillLevel.K1:
        refused.append("KILL_NOT_WRITER_K1")
    if not account.reconciled or account.unknown_orders or account.positions:
        refused.append("ACCOUNT_NOT_FLAT_RECONCILED")
    if ledger_mismatch_count != 0:
        refused.append("LEDGER_MISMATCH")
    if refused or roll is None:
        return tuple(dict.fromkeys(refused))
    return ObservationStandingResumeUse(
        authority_hash=record.authority_hash,
        activation_id=record.activation_id,
        run_id=run_id,
        local_day=local_day,
        boundary=boundary_kind,
        boundary_hash=boundary_hash,
        boundary_journal_hash=boundary_journal,
        roll_event_hash=roll,
        examined_event_hashes=tuple(fact.content_hash for fact in examined),
        journal_tail_hash=hashes[-1],
        evaluated_at=now,
    )
