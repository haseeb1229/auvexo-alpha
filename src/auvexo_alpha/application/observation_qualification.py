"""Pure observation planning/qualification; database proof alone grants calendar credit."""

from datetime import date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal, localcontext
from hashlib import sha256
from urllib.parse import parse_qs, urlsplit
from uuid import NAMESPACE_URL, uuid5

from auvexo_alpha.domain.contracts import Mode, MoneyAction, utc_time
from auvexo_alpha.domain.observation import (
    OBSERVATION_INSTRUMENTS,
    OBSERVATION_SYMBOLS,
    ObservationCalendarSummary,
    ObservationConfig,
    ObservationDayReceipt,
    ObservationFact,
    ObservationLedgerProof,
    ObservationProposalTrace,
    ObservationResources,
    ObservationRunEvidence,
    ObservationVerification,
    observation_market,
    observation_policy,
    observation_window,
)
from auvexo_alpha.domain.paper import PaperAccountSnapshot, PaperIntent, PaperReservation
from auvexo_alpha.domain.paper_lifecycle import Release
from auvexo_alpha.domain.paper_risk import assess_paper, verify_authorization


def validate_observation_fact(
    config: ObservationConfig, fact: ObservationFact, *, local_day: str, now: datetime
) -> None:
    """Validate original metadata; immutable storage additionally verifies physical bytes."""
    now = utc_time(now)
    candle, manifest = fact.candle, fact.manifest
    begin, end = observation_window(local_day)
    coverage = manifest.coverage
    epoch = datetime(1970, 1, 1, tzinfo=begin.tzinfo)
    url = urlsplit(manifest.source_url)
    query = parse_qs(url.query)
    if (
        candle.symbol not in OBSERVATION_SYMBOLS
        or candle.instrument_id not in OBSERVATION_INSTRUMENTS
        or candle.interval != "1m"
        or candle.source.source_id != "DS-02"
        or manifest.source != config.source
        or manifest.rights != config.rights
        or manifest.parser_version != "spot.v2"
        or manifest.code_revision != config.git_revision
        or manifest.source_hash != candle.source.source_hash
        or candle.source.source_url != manifest.source_url
        or url.scheme != "https"
        or url.netloc != "data-api.binance.vision"
        or url.path != "/api/v3/klines"
        or query.get("symbol") != [candle.symbol]
        or query.get("interval") != ["1m"]
        or set(query) != {"symbol", "interval", "startTime", "endTime", "limit"}
        or query.get("startTime") != [str((candle.open_at - epoch) // timedelta(milliseconds=1))]
        or query.get("endTime") != [str((candle.end_at - epoch) // timedelta(milliseconds=1) - 1)]
        or query.get("limit") != ["1000"]
        or coverage.instrument_id != candle.instrument_id
        or coverage.interval != "1m"
        or coverage.status != "PASS"
        or coverage.observed_rows != 1
        or coverage.expected_rows != 1
        or coverage.rejected_rows != 0
        or coverage.findings
        or coverage.requested_start != candle.open_at
        or coverage.requested_end != candle.end_at
        or coverage.earliest != candle.open_at
        or coverage.latest_end != candle.end_at
        or manifest.normalized_hash != sha256(candle.canonical_bytes()).hexdigest()
        or candle.availability.basis != "OBSERVED_RECEIPT"
        or candle.availability.original_first_seen_at != candle.source.received_at
        or candle.availability.received_at != candle.source.received_at
        or manifest.created_at != candle.source.received_at
        or manifest.processed_at != candle.availability.processed_at
        or not begin <= candle.end_at < end
        or not begin <= candle.source.received_at < end
        or not candle.end_at <= candle.source.received_at <= candle.availability.processed_at
        or not candle.availability.processed_at <= candle.availability.available_at <= now
        or candle.availability.available_at >= end
        or candle.source.received_at - candle.end_at > timedelta(seconds=config.max_gap_seconds)
        or not candle.end_at <= fact.clock.server_at < candle.end_at + timedelta(minutes=1)
        or fact.clock.received_at > candle.source.received_at
    ):
        raise ValueError("OBSERVATION_FACT_INVALID")
    config.rights.require_research(candle.source.received_at)
    config.rights.require_research(now)


def plan_observation_intent(
    config: ObservationConfig,
    fact: ObservationFact,
    account: PaperAccountSnapshot,
    release: Release,
    *,
    now: datetime,
    reservations: tuple[PaperReservation, ...] = (),
) -> PaperIntent | None:
    """Price-independent ten-minute long/flat cycle, never pyramiding or clearing kills."""
    now = utc_time(now)
    begin, end = observation_window(now.date())
    if not begin <= now < end:
        return None
    validate_observation_fact(config, fact, local_day=now.date().isoformat(), now=now)
    if account.account_ref != config.account_ref or account.currency != "USDT":
        raise ValueError("OBSERVATION_ACCOUNT_INVALID")
    instrument = fact.candle.instrument_id
    positions = tuple(p for p in account.positions if p.instrument_id == instrument)
    if len(positions) > 1:
        raise ValueError("OBSERVATION_POSITION_IDENTITY_INVALID")
    minute = int((fact.candle.end_at - begin).total_seconds()) // 60
    spec = next(s for s in config.specs if s.instrument_id == instrument)
    market = observation_market(fact)
    policy = observation_policy(config)
    if positions:
        if minute % 10 != 5 and now < end - timedelta(minutes=5):
            return None
        position = positions[0]
        action, quantity, stop, reference = (
            MoneyAction.CLOSE,
            position.quantity,
            position.stop_price,
            position.position_ref,
        )
    else:
        if (
            minute % 10 != 0
            or now >= end - timedelta(minutes=5)
            or any(r.instrument_id == instrument and r.state != "RELEASED" for r in reservations)
        ):
            return None
        action, reference = MoneyAction.OPEN, None
        with localcontext() as context:
            context.prec = 100
            stop = (fact.candle.close * Decimal("0.99") / spec.price_tick).to_integral_value(
                rounding=ROUND_DOWN
            ) * spec.price_tick
            per_unit = spec.contract_multiplier * (
                fact.candle.close
                - stop
                + fact.candle.close
                * (2 * policy.fee_bps + 2 * policy.slippage_bps + policy.gap_bps)
                / Decimal("10000")
            )
            budget = account.equity * config.max_fixture_risk_fraction
            quantity = (budget / per_unit / spec.quantity_step).to_integral_value(
                rounding=ROUND_DOWN
            ) * spec.quantity_step
            quantity = min(quantity, spec.max_quantity)
        if quantity <= 0 or stop <= 0:
            return None
    identity = f"{config.campaign_id}:{fact.content_hash()}:{action.value}"
    return PaperIntent(
        intent_id=uuid5(NAMESPACE_URL, identity),
        logical_key="observation." + sha256(identity.encode()).hexdigest(),
        account_ref=config.account_ref,
        instrument_id=instrument,
        action=action,
        side="SELL" if action == MoneyAction.CLOSE else "BUY",
        quantity=quantity,
        entry=fact.candle.close,
        stop=stop,
        release_hash=release.content_hash(),
        spec_hash=spec.content_hash(),
        snapshot_hash=market.content_hash(),
        account_snapshot_hash=account.content_hash(),
        policy_hash=policy.content_hash(),
        created_at=now,
        expires_at=min(now + timedelta(seconds=90), end),
        position_ref=reference,
    )


def _trace_valid(config: ObservationConfig, trace: ObservationProposalTrace) -> bool:
    decision, intent = trace.decision, trace.intent
    hashes = (
        intent.content_hash(),
        observation_policy(config).content_hash(),
        trace.account_before.content_hash(),
        trace.market.content_hash(),
        trace.spec.content_hash(),
        trace.release.content_hash(),
    )
    if (
        decision.intent_hash,
        decision.policy_hash,
        decision.account_snapshot_hash,
        decision.market_hash,
        decision.spec_hash,
        decision.release_hash,
    ) != hashes:
        return False
    if (
        intent.account_ref != config.account_ref
        or intent.mode != Mode.PAPER
        or intent.instrument_id not in OBSERVATION_INSTRUMENTS
        or intent.policy_hash != hashes[1]
        or intent.account_snapshot_hash != hashes[2]
        or intent.snapshot_hash != hashes[3]
        or intent.spec_hash != hashes[4]
        or intent.release_hash != hashes[5]
        or trace.spec not in config.specs
        or trace.release.fixture_namespace != "PAPER_QUALIFICATION_FIXTURE"
        or trace.release.release_id != config.fixture_version
        or trace.release.config_hash != config.content_hash()
    ):
        return False
    replay = assess_paper(
        intent,
        observation_policy(config),
        trace.market,
        trace.spec,
        trace.account_before,
        trace.release,
        trace.prior_reservations,
        now=decision.decision_at,
    )
    if replay.status == "DENIED":
        replay = type(replay).model_validate(replay.model_dump() | {"exposure": None})
    if replay != decision:
        return False
    if decision.status == "DENIED":
        return trace.authorization is None and trace.reservation is None
    auth, reservation = trace.authorization, trace.reservation
    return (
        auth is not None
        and reservation is not None
        and auth.intent_hash == hashes[0]
        and reservation.intent_hash == hashes[0]
        and auth.reservation_id == reservation.reservation_id
        and auth.exposure == decision.exposure
        and auth.account_ref == config.account_ref
        and verify_authorization(
            auth,
            intent,
            observation_policy(config),
            trace.market,
            trace.spec,
            trace.account_before,
            trace.release,
            reservation,
            now=decision.decision_at,
            reservations=trace.prior_reservations,
        )
    )


def evaluate_observation_day(
    config: ObservationConfig,
    evidence: ObservationRunEvidence,
    verification: ObservationVerification,
    *,
    now: datetime,
) -> ObservationDayReceipt:
    """Replay-bound result, never authority to persist/count caller-created evidence."""
    # Round trips prohibit model_copy/model_construct validation bypasses.
    config = ObservationConfig.model_validate_json(config.canonical_bytes())
    evidence = ObservationRunEvidence.model_validate_json(evidence.canonical_bytes())
    verification = ObservationVerification.model_validate_json(verification.canonical_bytes())
    now = utc_time(now)
    begin, end = observation_window(evidence.local_day)
    reasons: list[str] = list(dict.fromkeys(evidence.operational_reasons))

    def deny(reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

    if (
        evidence.campaign_id != config.campaign_id
        or evidence.config_hash != config.content_hash()
        or evidence.scheduled_at != begin
        or not begin <= evidence.started_at <= begin + timedelta(seconds=15)
        or not end <= evidence.ended_at <= end + timedelta(seconds=config.shutdown_grace_seconds)
        or evidence.ended_at > now
    ):
        deny("SCHEDULE_OR_CONFIG_INVALID")
    try:
        config.rights.require_research(now)
    except ValueError:
        deny("RIGHTS_UNAVAILABLE")
    valid: dict[str, list[ObservationFact]] = {symbol: [] for symbol in OBSERVATION_SYMBOLS}
    ids: set[str] = set()
    for fact in evidence.facts:
        try:
            validate_observation_fact(config, fact, local_day=evidence.local_day, now=now)
        except ValueError:
            deny("SOURCE_FACT_INVALID")
            continue
        identity = str(fact.observation_id)
        if identity in ids:
            deny("SOURCE_DUPLICATE")
        ids.add(identity)
        previous = valid[fact.candle.symbol]
        if previous and (
            fact.candle.end_at <= previous[-1].candle.end_at
            or fact.candle.availability.available_at
            <= previous[-1].candle.availability.available_at
        ):
            deny("SOURCE_DUPLICATE_OR_OUT_OF_ORDER")
        if fact.candle.source.received_at < evidence.started_at:
            deny("SOURCE_BEFORE_RUN")
        previous.append(fact)
    by_end = [
        {fact.candle.end_at: fact for fact in valid[symbol]} for symbol in OBSERVATION_SYMBOLS
    ]
    paired = sorted(set(by_end[0]) & set(by_end[1]))
    if not paired or paired[0] - begin > timedelta(seconds=config.max_gap_seconds):
        deny("OBSERVATION_START_GAP")
    if not paired or end - paired[-1] > timedelta(seconds=config.max_gap_seconds):
        deny("OBSERVATION_END_GAP")
    if len(paired) < config.minimum_paired_observations:
        deny("INSUFFICIENT_PAIRED_OBSERVATIONS")
    span = paired[-1] - paired[0] if paired else timedelta(0)
    if span < timedelta(seconds=config.minimum_span_seconds):
        deny("INSUFFICIENT_OBSERVATION_SPAN")
    gaps = [
        int((right - left).total_seconds()) for left, right in zip(paired, paired[1:], strict=False)
    ]
    maximum_gap = max(gaps, default=0)
    if maximum_gap > config.max_gap_seconds:
        deny("OBSERVATION_GAP")
    fact_hashes = tuple(fact.content_hash() for fact in evidence.facts)
    trace_hashes = tuple(trace.content_hash() for trace in evidence.traces)
    if (
        verification.run_evidence_hash != evidence.content_hash()
        or verification.source_fact_hashes != fact_hashes
        or verification.trace_hashes != trace_hashes
        or verification.journal_tail_hash != evidence.journal_tail_hash
        or verification.replay_journal_hash != evidence.journal_tail_hash
        or verification.replay_intent_hashes
        != tuple(t.intent.content_hash() for t in evidence.traces)
        or verification.replay_decision_hashes
        != tuple(t.decision.content_hash() for t in evidence.traces)
        or verification.reservation_hashes != evidence.reservation_hashes
        or verification.outbox_hashes != evidence.outbox_hashes
        or verification.fill_hashes != evidence.fill_hashes
    ):
        deny("VERIFICATION_OR_REPLAY_BINDING_INVALID")
    logical_keys: set[str] = set()
    intent_ids: set[str] = set()
    for trace in evidence.traces:
        if not _trace_valid(config, trace):
            deny("PROPOSAL_TRACE_INVALID")
        if trace.source_observation_hash not in fact_hashes:
            deny("PROPOSAL_SOURCE_UNBOUND")
        if trace.intent.logical_key in logical_keys or str(trace.intent.intent_id) in intent_ids:
            deny("DUPLICATE_LOGICAL_INTENT")
        logical_keys.add(trace.intent.logical_key)
        intent_ids.add(str(trace.intent.intent_id))
        source = next(
            (f for f in evidence.facts if f.content_hash() == trace.source_observation_hash), None
        )
        if source is not None and (
            trace.market != observation_market(source)
            or trace.intent.created_at < source.candle.availability.available_at
            or trace.decision.decision_at < trace.intent.created_at
            or trace.decision.decision_at > evidence.ended_at
        ):
            deny("PROPOSAL_CAUSALITY_INVALID")
    approvals = sum(trace.decision.status == "APPROVED" for trace in evidence.traces)
    if not evidence.traces:
        deny("PROPOSAL_EVIDENCE_MISSING")
    if len(evidence.reservation_hashes) != approvals or len(evidence.outbox_hashes) != approvals:
        deny("PROPOSAL_COUNT_CONSERVATION_INVALID")
    if evidence.reservation_hashes != tuple(
        trace.reservation.content_hash()
        for trace in evidence.traces
        if trace.reservation is not None
    ):
        deny("RESERVATION_BINDING_INVALID")
    if evidence.fill_hashes != tuple(fill.content_hash() for fill in evidence.simulation_traces):
        deny("FILL_BINDING_INVALID")
    fact_map = {fact.content_hash(): fact for fact in evidence.facts}
    trace_map = {trace.intent.content_hash(): trace for trace in evidence.traces}
    filled: dict[str, Decimal] = {}
    fill_ids: set[str] = set()
    for fill in evidence.simulation_traces:
        proposal = trace_map.get(fill.intent_hash)
        earlier, later = (
            fact_map.get(fill.proposal_source_hash),
            fact_map.get(fill.fill_source_hash),
        )
        filled[fill.intent_hash] = filled.get(fill.intent_hash, Decimal("0")) + fill.quantity
        identity = str(fill.truth_event_id)
        if (
            identity in fill_ids
            or proposal is None
            or proposal.authorization is None
            or earlier is None
            or later is None
            or (
                proposal is not None
                and proposal.source_observation_hash != fill.proposal_source_hash
            )
        ):
            deny("FILL_CAUSALITY_OR_BINDING_INVALID")
        else:
            assert proposal.authorization is not None and earlier is not None and later is not None
            if (
                earlier.candle.instrument_id != later.candle.instrument_id
                or later.candle.instrument_id != proposal.intent.instrument_id
                or later.candle.end_at <= earlier.candle.end_at
                or later.candle.availability.available_at
                <= earlier.candle.availability.available_at
                or later.candle.source.received_at <= earlier.candle.source.received_at
                or later.candle.availability.available_at > fill.observed_at
                or not proposal.authorization.issued_at
                <= fill.observed_at
                < proposal.authorization.expires_at
                or filled[fill.intent_hash] > proposal.authorization.exposure.quantity
                or fill.observed_at > evidence.ended_at
                or (
                    proposal.intent.action == MoneyAction.OPEN
                    and fill.price > proposal.intent.entry
                )
                or (
                    proposal.intent.action == MoneyAction.CLOSE
                    and fill.price < proposal.intent.entry
                )
            ):
                deny("FILL_CAUSALITY_OR_BINDING_INVALID")
        fill_ids.add(identity)
    if evidence.unknown_order_refs or evidence.final_account.unknown_orders:
        deny("UNRESOLVED_UNKNOWN")
    if evidence.mismatch_refs or not evidence.final_account.journal_healthy:
        deny("LEDGER_MISMATCH")
    if (
        evidence.final_account.account_ref != config.account_ref
        or evidence.final_account.currency != "USDT"
    ):
        deny("FINAL_ACCOUNT_INVALID")
    if not evidence.final_account.reconciled:
        deny("FINAL_RECONCILIATION_REQUIRED")
    if not evidence.resource_snapshots:
        deny("RESOURCE_EVIDENCE_MISSING")
    for resource in evidence.resource_snapshots:
        if not evidence.started_at <= resource.observed_at <= evidence.ended_at:
            deny("RESOURCE_TIME_INVALID")
        if resource.available_ram_bytes < 1_500_000_000:
            deny("RESOURCE_ENTRY_PAUSE")
    return ObservationDayReceipt(
        run_id=evidence.run_id,
        campaign_id=evidence.campaign_id,
        local_day=evidence.local_day,
        kind=evidence.kind,
        config_hash=config.content_hash(),
        git_revision=config.git_revision,
        policy_hash=observation_policy(config).content_hash(),
        spec_hashes=tuple(spec.content_hash() for spec in config.specs),
        rights_hash=config.rights.content_hash(),
        source_hash=config.source.content_hash(),
        schedule_id=config.schedule_id,
        scheduled_at=evidence.scheduled_at,
        started_at=evidence.started_at,
        ended_at=evidence.ended_at,
        evidence_hash=evidence.content_hash(),
        verification_hash=verification.content_hash(),
        status="INCOMPLETE" if reasons else "PASS",
        reasons=tuple(reasons),
        operational_reasons=evidence.operational_reasons,
        first_observation_at=paired[0] if paired else None,
        last_observation_at=paired[-1] if paired else None,
        paired_observations=len(paired),
        max_gap_seconds=maximum_gap,
        proposal_count=len(evidence.traces),
        decision_count=len(evidence.traces),
        authorization_count=approvals,
        denial_count=len(evidence.traces) - approvals,
        reservation_count=len(evidence.reservation_hashes),
        outbox_count=len(evidence.outbox_hashes),
        fill_count=len(evidence.fill_hashes),
        truth_cursor=evidence.truth_cursor,
        journal_tail_hash=evidence.journal_tail_hash,
        final_account_hash=evidence.final_account.content_hash(),
        final_kill=evidence.final_account.kill,
        final_reconciled=evidence.final_account.reconciled,
        position_hashes=tuple(
            position.content_hash() for position in evidence.final_account.positions
        ),
        resource_hashes=tuple(r.content_hash() for r in evidence.resource_snapshots),
        resources=evidence.resource_snapshots,
    )


def observation_resource_actions(resource: ObservationResources) -> tuple[str, ...]:
    """Exact host thresholds; a high-duration counter alone cannot imply high current CPU."""
    actions: list[str] = []
    if resource.available_ram_bytes < 3_000_000_000 or (
        resource.cpu_percent > Decimal("80") and resource.cpu_high_for_seconds >= 60
    ):
        actions.append("PAUSE_OPTIONAL_RESEARCH")
    if resource.available_ram_bytes < 1_500_000_000:
        actions.append("PAUSE_ENTRIES")
    return tuple(actions)


def observation_ledger_tail(receipts: tuple[ObservationDayReceipt, ...]) -> str:
    """Digest the exact immutable ordered receipt payload sequence, including INCOMPLETE."""
    return sha256(b"\n".join(receipt.canonical_bytes() for receipt in receipts)).hexdigest()


def summarize_observation_days(
    receipts: tuple[ObservationDayReceipt, ...],
    proof: ObservationLedgerProof | None,
    *,
    now: datetime,
) -> ObservationCalendarSummary:
    """A witness from verified immutable SQL receipts is required; NON_COUNTING never counts."""
    now = utc_time(now)
    campaign = (
        proof.campaign_id
        if proof is not None
        else (receipts[0].campaign_id if receipts else "unprepared")
    )
    reasons: list[str] = []
    qualified: list[str] = []
    seen: set[str] = set()
    if proof is None:
        reasons.append("ACTIVATION_AND_LEDGER_PROOF_REQUIRED")
    else:
        proof = ObservationLedgerProof.model_validate_json(proof.canonical_bytes())
        if proof.verified_at > now or proof.activated_at > proof.verified_at:
            reasons.append("LEDGER_CLOCK_INVALID")
        if proof.receipt_hashes != tuple(receipt.content_hash() for receipt in receipts):
            reasons.append("LEDGER_RECEIPT_BINDING_INVALID")
        if proof.ledger_tail_hash != observation_ledger_tail(receipts):
            reasons.append("LEDGER_TAIL_BINDING_INVALID")
        if tuple(receipt.local_day for receipt in receipts) != tuple(
            sorted(receipt.local_day for receipt in receipts)
        ):
            reasons.append("LEDGER_DATE_ORDER_INVALID")
        first_start, _ = observation_window(proof.first_eligible_day)
        if proof.activated_at >= first_start:
            reasons.append("ACTIVATION_NOT_BEFORE_FIRST_WINDOW")
        for receipt in receipts:
            start, end = observation_window(receipt.local_day)
            if (
                receipt.campaign_id != campaign
                or receipt.local_day in seen
                or receipt.local_day < proof.first_eligible_day
                or start <= proof.activated_at
                or end > now
            ):
                reasons.append("LEDGER_DATE_INVALID")
            seen.add(receipt.local_day)
            if receipt.status == "PASS" and receipt.kind == "SCHEDULED":
                qualified.append(receipt.local_day)
    qualified = sorted(set(qualified)) if not reasons else []
    span = (
        (date.fromisoformat(qualified[-1]) - date.fromisoformat(qualified[0])).days
        if qualified
        else 0
    )
    complete = len(qualified) >= 14 and span >= 14
    return ObservationCalendarSummary(
        campaign_id=campaign,
        status="INVALID" if reasons and proof is not None else "PASS" if complete else "OPEN",
        reasons=tuple(dict.fromkeys(reasons)),
        qualified_dates=tuple(qualified),
        qualified_count=len(qualified),
        calendar_span_days=span,
        observation_started=proof is not None and not reasons,
    )
