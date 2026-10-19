"""Pure exact PAPER risk. No storage, network, credentials or external permits."""

from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal, InvalidOperation, localcontext

from pydantic import ValidationError

from auvexo_alpha.domain.contracts import Contract, Mode, MoneyAction, Product, Venue, utc_time
from auvexo_alpha.domain.paper import (
    PaperAccountSnapshot,
    PaperAuthorization,
    PaperDecision,
    PaperExposure,
    PaperInstrumentSpec,
    PaperIntent,
    PaperMarketSnapshot,
    PaperPolicy,
    PaperReason,
    PaperReservation,
    paper_position_ref,
)
from auvexo_alpha.domain.paper_lifecycle import (
    KillLevel,
    Release,
    ReleaseKind,
    ReleaseState,
    require_release_eligibility,
)

ZERO = Decimal("0")
BPS = Decimal("10000")


def _validated[T: Contract](value: T) -> T:
    # Unlike model_validate(instance), this rechecks copy/construct bypasses recursively.
    return type(value).model_validate_json(value.model_dump_json(warnings="error"))


def _hash(value: Contract) -> str:
    if not isinstance(value, Contract):
        return "0" * 64
    try:
        return _validated(value).content_hash()
    except (TypeError, ValueError, InvalidOperation):
        return "0" * 64


def _decision(
    intent: PaperIntent,
    policy: PaperPolicy,
    market: PaperMarketSnapshot,
    spec: PaperInstrumentSpec,
    account: PaperAccountSnapshot,
    release: Release,
    now: datetime,
    reasons: set[PaperReason],
    exposure: PaperExposure | None = None,
) -> PaperDecision:
    return PaperDecision(
        status="DENIED" if reasons else "APPROVED",
        intent_hash=_hash(intent),
        policy_hash=_hash(policy),
        market_hash=_hash(market),
        spec_hash=_hash(spec),
        account_snapshot_hash=_hash(account),
        release_hash=_hash(release),
        reasons=tuple(reason for reason in PaperReason if reason in reasons),
        exposure=exposure,
        decision_at=now,
    )


def assess_paper(
    intent: PaperIntent,
    policy: PaperPolicy,
    market: PaperMarketSnapshot,
    spec: PaperInstrumentSpec,
    account: PaperAccountSnapshot,
    release: Release,
    reservations: tuple[PaperReservation, ...] = (),
    *,
    now: datetime,
) -> PaperDecision:
    """Evaluate all safely computable reasons in stable order; reserve nowhere.

    Costs are stressed round-trip fees/slippage plus an adverse entry-notional gap:
    notional * (2*fee_bps + 2*slippage_bps + gap_bps) / 10000.
    All outstanding capacity, including expired UNKNOWN, remains until reconciliation.
    """
    now = utc_time(now)
    expected = (
        (intent, PaperIntent),
        (policy, PaperPolicy),
        (market, PaperMarketSnapshot),
        (spec, PaperInstrumentSpec),
        (account, PaperAccountSnapshot),
        (release, Release),
    )
    if (
        any(not isinstance(value, model) for value, model in expected)
        or not isinstance(reservations, tuple)
        or any(not isinstance(value, PaperReservation) for value in reservations)
    ):
        return _decision(
            intent, policy, market, spec, account, release, now, {PaperReason.INVALID_INPUT}
        )
    try:
        intent = _validated(intent)
        policy = _validated(policy)
        market = _validated(market)
        spec = _validated(spec)
        account = _validated(account)
        release = _validated(release)
        reservations = tuple(_validated(value) for value in reservations)
    except (ValidationError, ValueError, TypeError, InvalidOperation):
        return _decision(
            intent, policy, market, spec, account, release, now, {PaperReason.INVALID_INPUT}
        )
    with localcontext() as context:
        context.prec = 256
        try:
            return _assess(intent, policy, market, spec, account, release, reservations, now)
        except (ValidationError, ValueError, InvalidOperation, OverflowError):
            # Precision/range overflow must not become a smaller guessed exposure.
            return _decision(
                intent, policy, market, spec, account, release, now, {PaperReason.INVALID_INPUT}
            )


def _assess(
    intent: PaperIntent,
    policy: PaperPolicy,
    market: PaperMarketSnapshot,
    spec: PaperInstrumentSpec,
    account: PaperAccountSnapshot,
    release: Release,
    reservations: tuple[PaperReservation, ...],
    now: datetime,
) -> PaperDecision:
    reasons: set[PaperReason] = set()
    add = reasons.add
    buckets = dict(policy.bucket_by_instrument)
    bucket = buckets.get(intent.instrument_id, "unknown")
    active = tuple(r for r in reservations if r.state != "RELEASED")
    opening = intent.action == MoneyAction.OPEN
    reducing = intent.action in (MoneyAction.CLOSE, MoneyAction.CANCEL)
    marked_equity = account.cash + sum(
        (p.quantity * p.multiplier * p.mark_price * p.adverse_fx for p in account.positions), ZERO
    )
    if account.equity != marked_equity.quantize(
        Decimal("0.000000000000000001"), rounding=ROUND_DOWN
    ):
        add(PaperReason.INVALID_INPUT)
    try:
        require_release_eligibility(release, now)
    except ValueError:
        if opening:
            add(PaperReason.RELEASE_INELIGIBLE)
    if (
        opening
        and release.kind == ReleaseKind.RESEARCH_EVIDENCED
        and (
            release.data_eligibility is None
            or not any(
                source.instrument_id == intent.instrument_id
                and source.venue == intent.venue
                and source.product == intent.product
                for source in release.data_eligibility.inputs
            )
        )
    ):
        add(PaperReason.RELEASE_INELIGIBLE)
    for marked_position in account.positions:
        if not opening and marked_position.position_ref != intent.position_ref:
            continue
        if (
            marked_position.mark_as_of is None
            or marked_position.fx_as_of is None
            or not timedelta(0)
            <= now - marked_position.mark_as_of
            <= timedelta(seconds=policy.max_market_age_seconds)
            or not timedelta(0)
            <= now - marked_position.fx_as_of
            <= timedelta(seconds=policy.max_fx_age_seconds)
        ):
            add(PaperReason.ACCOUNT_STALE)
        if marked_position.instrument_id == market.instrument_id and (
            marked_position.mark_price != market.bid
            or marked_position.adverse_fx != market.adverse_fx
        ):
            add(PaperReason.ACCOUNT_UNRECONCILED)
    if intent.mode != Mode.PAPER:
        add(PaperReason.MODE_MISMATCH)
        if release.kind == ReleaseKind.TEST_ONLY:
            add(PaperReason.FIXTURE_MODE_BLOCKED)
    if intent.account_ref not in policy.allowed_accounts:
        add(PaperReason.ACCOUNT_UNKNOWN)
    if intent.account_ref != account.account_ref or any(
        r.account_ref != account.account_ref for r in active
    ):
        add(PaperReason.ACCOUNT_MISMATCH)
    if (
        intent.release_hash != release.content_hash()
        or intent.policy_hash != policy.content_hash()
        or intent.spec_hash != spec.content_hash()
        or intent.snapshot_hash != market.content_hash()
        or intent.account_snapshot_hash != account.content_hash()
    ):
        add(PaperReason.HASH_MISMATCH)
    if (
        intent.venue not in policy.allowed_venues
        or intent.venue != Venue.BINANCE
        or intent.product not in policy.allowed_products
        or intent.product != Product.SPOT
        or intent.instrument_id not in policy.allowed_instruments
        or intent.venue != spec.venue
        or intent.product != spec.product
        or intent.instrument_id != spec.instrument_id
        or intent.instrument_id != market.instrument_id
    ):
        add(PaperReason.VENUE_PRODUCT_INELIGIBLE)
    permitted_release_states = (
        (ReleaseState.PAPER, ReleaseState.SUSPENDED, ReleaseState.RETIRED)
        if reducing
        else (ReleaseState.PAPER,)
    )
    if (
        release.state not in permitted_release_states
        or Mode.PAPER not in release.allowed_modes
        or not release.approved_by
        or release.created_at > now
        or (release.updated_at is not None and release.updated_at > now)
    ):
        add(PaperReason.RELEASE_INELIGIBLE)
    if not intent.created_at <= now < intent.expires_at:
        add(PaperReason.INTENT_EXPIRED)
    if market.health != "HEALTHY" or market.available_at > now:
        add(PaperReason.MARKET_INVALID)
    if not timedelta(0) <= now - market.as_of <= timedelta(seconds=policy.max_market_age_seconds):
        add(PaperReason.MARKET_STALE)
    if (
        not timedelta(0) <= now - account.as_of <= timedelta(seconds=policy.max_account_age_seconds)
        or not timedelta(0)
        <= now - account.reconciled_at
        <= timedelta(seconds=policy.max_account_age_seconds)
        or account.day_start_at.date() != now.date()
    ):
        add(PaperReason.ACCOUNT_STALE)
    if not account.reconciled:
        add(PaperReason.ACCOUNT_UNRECONCILED)
    if not timedelta(0) <= now - spec.observed_at <= timedelta(seconds=policy.max_spec_age_seconds):
        add(PaperReason.SPEC_STALE)
    if (
        spec.contract_multiplier != 1
        or spec.product != Product.SPOT
        or spec.account_currency != account.currency
        or spec.min_quantity % spec.quantity_step
        or spec.max_quantity % spec.quantity_step
        or any(p.multiplier != 1 or p.stop_price >= p.entry_price for p in account.positions)
        or any(buckets.get(p.instrument_id) != p.bucket for p in account.positions)
        or any(buckets.get(r.instrument_id) != r.bucket for r in active)
    ):
        add(PaperReason.SPEC_UNSUPPORTED)
    if spec.fill_semantics != "LINEAR_LONG_SPOT":
        add(PaperReason.FILL_UNSUPPORTED)
    fx = market.adverse_fx
    if fx is None or market.fx_as_of is None:
        add(PaperReason.FX_UNKNOWN)
    elif not timedelta(0) <= now - market.fx_as_of <= timedelta(seconds=policy.max_fx_age_seconds):
        add(PaperReason.FX_STALE)
    if abs(market.clock_offset_ms) > policy.max_clock_offset_ms:
        add(PaperReason.CLOCK_OFFSET)
    if not market.session_open:
        add(PaperReason.SESSION_CLOSED)
    if intent.entry % spec.price_tick or intent.stop % spec.price_tick:
        add(PaperReason.PRICE_INVALID)
    if opening and intent.entry < market.ask:
        add(PaperReason.PRICE_INVALID)
    if opening and intent.stop >= intent.entry:
        add(PaperReason.STOP_INVALID)
    if (opening and intent.side != "BUY") or (
        intent.action == MoneyAction.CLOSE and intent.side != "SELL"
    ):
        add(PaperReason.SHORT_UNSUPPORTED)
    if not opening and not reducing:
        add(PaperReason.SPEC_UNSUPPORTED)
    if not account.journal_healthy:
        add(PaperReason.JOURNAL_UNHEALTHY)
    if account.unknown_orders or any(r.state == "UNKNOWN" for r in active):
        add(PaperReason.UNKNOWN_ORDER)
    if (
        intent.logical_key in account.prior_logical_keys
        or intent.intent_id in account.prior_intent_ids
        or any(
            r.logical_key == intent.logical_key
            or r.intent_hash == intent.content_hash()
            or r.intent_id == intent.intent_id
            for r in active
        )
    ):
        add(PaperReason.DUPLICATE_INTENT)
    if opening and any(
        position.position_ref == paper_position_ref(account.account_ref, intent.intent_id)
        for position in account.positions
    ):
        add(PaperReason.DUPLICATE_INTENT)
    if account.kill == KillLevel.K4 or (opening and account.kill != KillLevel.K0):
        add(PaperReason.KILL_BLOCKED)
    if any(value > now for value in account.recent_intent_times):
        add(PaperReason.ACCOUNT_STALE)
    if (
        opening
        and sum(
            now - timedelta(minutes=1) < timestamp <= now
            for timestamp in account.recent_intent_times
        )
        >= policy.max_intents_per_minute
    ):
        add(PaperReason.ORDER_RATE_CAP)

    quantity = (intent.quantity / spec.quantity_step).to_integral_value(rounding=ROUND_DOWN)
    quantity *= spec.quantity_step
    if quantity < spec.min_quantity:
        add(PaperReason.MINIMUM_QUANTITY)
    if quantity > spec.max_quantity or quantity <= 0:
        add(PaperReason.QUANTITY_INVALID)
    notional = quantity * spec.contract_multiplier * intent.entry * (fx or ZERO)
    costs = notional * (2 * policy.fee_bps + 2 * policy.slippage_bps + policy.gap_bps) / BPS
    modeled_loss = (
        quantity * spec.contract_multiplier * abs(intent.entry - intent.stop) * (fx or ZERO) + costs
    )
    margin = notional * spec.margin_fraction
    cash_required = notional + costs
    if notional < spec.min_notional:
        add(PaperReason.MINIMUM_NOTIONAL)

    if intent.action == MoneyAction.CLOSE:
        position = next(
            (p for p in account.positions if p.position_ref == intent.position_ref), None
        )
        if position is None or position.instrument_id != intent.instrument_id:
            add(PaperReason.POSITION_UNKNOWN)
        else:
            closing = sum(
                (
                    r.quantity
                    for r in active
                    if r.action == MoneyAction.CLOSE and r.position_ref == position.position_ref
                ),
                ZERO,
            )
            # Do not round an over-close into an apparently valid close.
            if intent.quantity > position.quantity - closing or quantity != intent.quantity:
                add(PaperReason.OVER_CLOSE)
            if intent.entry > market.bid:
                add(PaperReason.PRICE_INVALID)
        # A reduce-only fill creates no new stop risk or margin, but retains quantity.
        modeled_loss = costs
        margin = ZERO
        cash_required = costs
    elif intent.action == MoneyAction.CANCEL:
        target = next(
            (
                r
                for r in active
                if r.intent_id == intent.target_intent_ref and r.action == MoneyAction.OPEN
            ),
            None,
        )
        if target is None or target.instrument_id != intent.instrument_id:
            add(PaperReason.TARGET_UNKNOWN)
        elif any(
            r.action == MoneyAction.CANCEL and r.target_intent_ref == intent.target_intent_ref
            for r in active
        ):
            add(PaperReason.DUPLICATE_INTENT)
        modeled_loss = margin = cash_required = notional = ZERO
    elif opening:
        pending = tuple(r for r in active if r.action == MoneyAction.OPEN)
        position_risks = tuple(
            (
                p,
                p.quantity
                * p.multiplier
                * max(max(p.entry_price, p.mark_price) - p.stop_price, ZERO)
                * p.adverse_fx
                + max(
                    p.modeled_costs,
                    p.quantity
                    * p.multiplier
                    * max(p.entry_price, p.mark_price)
                    * p.adverse_fx
                    * (2 * policy.fee_bps + 2 * policy.slippage_bps + policy.gap_bps)
                    / BPS,
                ),
            )
            for p in account.positions
        )
        total_risk = (
            modeled_loss
            + sum((risk for _, risk in position_risks), ZERO)
            + sum((r.modeled_loss for r in pending), ZERO)
        )
        asset_risk = (
            modeled_loss
            + sum(
                (risk for p, risk in position_risks if p.instrument_id == intent.instrument_id),
                ZERO,
            )
            + sum(
                (r.modeled_loss for r in pending if r.instrument_id == intent.instrument_id), ZERO
            )
        )
        bucket_risk = (
            modeled_loss
            + sum((risk for p, risk in position_risks if p.bucket == bucket), ZERO)
            + sum((r.modeled_loss for r in pending if r.bucket == bucket), ZERO)
        )
        gross = (
            notional
            + sum(
                (
                    p.quantity * p.multiplier * p.mark_price * p.adverse_fx
                    for p in account.positions
                ),
                ZERO,
            )
            + sum((r.notional for r in pending), ZERO)
        )
        margin_total = (
            margin
            + sum((p.margin_used for p in account.positions), ZERO)
            + sum((r.margin for r in pending), ZERO)
        )
        pending_cash = sum((r.notional + r.modeled_loss for r in pending), ZERO)
        if cash_required + pending_cash > account.cash:
            add(PaperReason.BALANCE_CAP)
        caps = (
            (modeled_loss, policy.max_trade_risk_fraction, PaperReason.TRADE_RISK_CAP),
            (asset_risk, policy.max_asset_risk_fraction, PaperReason.ASSET_RISK_CAP),
            (bucket_risk, policy.max_bucket_risk_fraction, PaperReason.BUCKET_RISK_CAP),
            (total_risk, policy.max_total_risk_fraction, PaperReason.TOTAL_RISK_CAP),
            (gross, policy.max_gross_fraction, PaperReason.GROSS_CAP),
            (gross, policy.max_net_fraction, PaperReason.NET_CAP),
            (margin_total, policy.max_margin_fraction, PaperReason.MARGIN_CAP),
        )
        for amount, fraction, reason in caps:
            if amount > account.equity * fraction:
                add(reason)
        # No netting guarantee is inferred: each position/pending open can remain distinct.
        if len(account.positions) + len(pending) + 1 > policy.max_positions:
            add(PaperReason.POSITIONS_CAP)
        daily_loss = max(account.day_start_equity - (account.equity - account.day_net_flows), ZERO)
        drawdown = max(
            account.high_water_equity - (account.equity - account.net_flows_since_high_water), ZERO
        )
        if daily_loss + total_risk > account.day_start_equity * policy.max_daily_loss_fraction:
            add(PaperReason.DAILY_LOSS_CAP)
        if drawdown + total_risk > account.high_water_equity * policy.max_drawdown_fraction:
            add(PaperReason.DRAWDOWN_CAP)
    exposure = PaperExposure(
        quantity=quantity,
        notional=notional,
        modeled_loss=modeled_loss,
        margin_required=margin,
        cash_required=cash_required,
        bucket=bucket,
    )
    return _decision(intent, policy, market, spec, account, release, now, reasons, exposure)


def verify_authorization(
    authorization: PaperAuthorization,
    intent: PaperIntent,
    policy: PaperPolicy,
    market: PaperMarketSnapshot,
    spec: PaperInstrumentSpec,
    account: PaperAccountSnapshot,
    release: Release,
    reservation: PaperReservation,
    *,
    now: datetime,
    reservations: tuple[PaperReservation, ...] = (),
) -> bool:
    """Full current check, for a persisted matching authorization/reservation pair.

    The caller also verifies ownership in durable storage and serializes its account.
    Self-reservation is excluded from the duplicate/cap recheck, all others count.
    A stale account hash is deliberately refused rather than treated as blanket authority.
    """
    try:
        authorization = _validated(authorization)
        reservation = _validated(reservation)
        now = utc_time(now)
        if (
            not authorization.issued_at <= now < authorization.expires_at <= intent.expires_at
            or authorization.intent_hash != intent.content_hash()
            or authorization.account_ref != account.account_ref
            or authorization.writer_epoch != account.epoch
            or authorization.reservation_id != reservation.reservation_id
            or reservation.intent_hash != intent.content_hash()
            or reservation.account_ref != account.account_ref
            or reservation.logical_key != intent.logical_key
            or reservation.state != "ACTIVE"
            or reservation.action != intent.action
            or reservation.quantity != authorization.exposure.quantity
            or reservation.notional != authorization.exposure.notional
            or reservation.modeled_loss != authorization.exposure.modeled_loss
            or reservation.margin != authorization.exposure.margin_required
        ):
            return False
        others = tuple(r for r in reservations if r.reservation_id != reservation.reservation_id)
        decision = assess_paper(intent, policy, market, spec, account, release, others, now=now)
        return (
            decision.status == "APPROVED"
            and authorization.policy_hash == decision.policy_hash
            and authorization.account_snapshot_hash == decision.account_snapshot_hash
            and authorization.market_hash == decision.market_hash
            and authorization.spec_hash == decision.spec_hash
            and authorization.release_hash == decision.release_hash
            and authorization.exposure == decision.exposure
        )
    except (ValidationError, ValueError, TypeError, InvalidOperation):
        return False
