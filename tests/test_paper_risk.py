"""Exact, adversarial PAPER risk evidence from synthetic fixtures only."""

from datetime import timedelta
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st
from paper_fixtures import PaperFixture, fixture_bundle
from pydantic import ValidationError

from auvexo_alpha.domain.contracts import Contract, Mode, MoneyAction, Product, Venue
from auvexo_alpha.domain.paper import (
    PaperAccountSnapshot,
    PaperAuthorization,
    PaperCandidate,
    PaperDecision,
    PaperIntent,
    PaperPosition,
    PaperReason,
    PaperReservation,
    bind_authorization,
    paper_position_ref,
)
from auvexo_alpha.domain.paper_lifecycle import KillLevel, ReleaseState
from auvexo_alpha.domain.paper_risk import assess_paper, verify_authorization


def changed[T: Contract](value: T, **updates: object) -> T:
    payload = value.model_dump()
    payload.update(updates)
    if isinstance(value, PaperAccountSnapshot):
        positions = updates.get("positions", value.positions)
        assert isinstance(positions, tuple)
        marked = sum(
            (p.quantity * p.multiplier * p.mark_price * p.adverse_fx for p in positions),
            Decimal("0"),
        )
        if "equity" in updates and "cash" not in updates:
            payload["cash"] = Decimal(str(updates["equity"])) - marked
        elif "equity" not in updates:
            payload["equity"] = Decimal(str(payload["cash"])) + marked
    return type(value).model_validate(payload)


def assess(b: PaperFixture, reservations: tuple[PaperReservation, ...] = ()) -> PaperDecision:
    return assess_paper(
        b.rebind(), b.policy, b.market, b.spec, b.account, b.release, reservations, now=b.now
    )


def reservation(b: PaperFixture, **updates: object) -> PaperReservation:
    decision = assess(b)
    assert decision.exposure is not None
    exposure = decision.exposure
    payload: dict[str, object] = dict(
        reservation_id=uuid4(),
        intent_id=uuid4(),
        intent_hash=b.intent.content_hash(),
        logical_key=f"other.{uuid4()}",
        account_ref=b.account.account_ref,
        instrument_id=b.intent.instrument_id,
        bucket=exposure.bucket,
        action=MoneyAction.OPEN,
        quantity=exposure.quantity,
        notional=exposure.notional,
        modeled_loss=exposure.modeled_loss,
        margin=exposure.margin_required,
        created_at=b.now,
        expires_at=b.intent.expires_at,
    )
    payload.update(updates)
    return PaperReservation.model_validate(payload)


def position(b: PaperFixture, **updates: object) -> PaperPosition:
    payload: dict[str, object] = dict(
        position_ref="position.one",
        instrument_id=b.intent.instrument_id,
        bucket="crypto",
        quantity=Decimal("0.01"),
        entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
        mark_as_of=b.now,
        fx_as_of=b.now,
        adverse_fx=Decimal("1.01"),
        stop_price=Decimal("49000"),
    )
    payload.update(updates)
    return PaperPosition.model_validate(payload)


def test_p4_hand_loss_roundtrip_cost_stress_and_rounding() -> None:
    b = fixture_bundle(quantity="0.0109")
    decision = assess(b)
    assert decision.status == "APPROVED"
    assert decision.exposure is not None
    # floor(.0109/.001)*.001=.010; notional=.010*50000*1.01=505.
    # stop loss=.010*1000*1.01=10.10; cost=505*(20+10+5)/10000=1.7675.
    assert decision.exposure.quantity == Decimal("0.010")
    assert decision.exposure.notional == Decimal("505")
    assert decision.exposure.modeled_loss == Decimal("11.8675")
    assert decision.exposure.cash_required == Decimal("506.7675")
    assert decision == assess(b)
    with localcontext() as context:
        context.prec = 6
        assert assess(b) == decision


def test_p4_inflated_equity_and_unknown_position_marks_cannot_authorize() -> None:
    b = fixture_bundle()
    b.account = b.account.model_copy(update={"equity": Decimal("20000")})
    assert PaperReason.INVALID_INPUT in assess(b).reasons
    b = fixture_bundle()
    p = position(b, mark_as_of=None)
    b.account = changed(b.account, positions=(p,))
    assert PaperReason.ACCOUNT_STALE in assess(b).reasons


def test_p4_current_policy_costs_cannot_be_removed_from_open_position_risk() -> None:
    b = fixture_bundle()
    p = position(b, stop_price=Decimal("49990"), modeled_costs=Decimal("0"))
    b.account = changed(b.account, positions=(p,))
    b.policy = changed(b.policy, max_total_risk_fraction=Decimal("0.00124"))
    # Equity 10505: cap13.0262. New11.8675 + existing(.101+1.7675) exceeds it.
    assert PaperReason.TOTAL_RISK_CAP in assess(b).reasons


@pytest.mark.parametrize("bad", [0.1, True, Decimal("NaN"), Decimal("Infinity"), "1e-3"])
def test_p4_exact_financial_boundary(bad: object) -> None:
    b = fixture_bundle()
    payload = b.intent.model_dump()
    payload["quantity"] = bad
    with pytest.raises(ValidationError):
        PaperIntent.model_validate(payload)
    # Constructors/copiers that skip validation are still refused by the kernel.
    forged = b.intent.model_copy(update={"quantity": bad})
    assert assess_paper(
        forged, b.policy, b.market, b.spec, b.account, b.release, now=b.now
    ).reasons == (PaperReason.INVALID_INPUT,)


def test_p4_candidate_has_no_authority_and_cannot_mutate() -> None:
    b = fixture_bundle()
    candidate = PaperCandidate(
        candidate_id=uuid4(),
        fixture_evidence_hash=b.release.evidence_hash,
        instrument_id=b.intent.instrument_id,
        side="BUY",
        quantity=Decimal("1"),
        entry=Decimal("50000"),
        stop=Decimal("49000"),
        created_at=b.now,
    )
    with pytest.raises(ValidationError):
        candidate.quantity = Decimal("2")
    assert "authorization_id" not in PaperCandidate.model_fields


@pytest.mark.parametrize("mode", [mode for mode in Mode if mode != Mode.PAPER])
def test_p4_no_nonpaper_mode(mode: Mode) -> None:
    b = fixture_bundle()
    b.intent = b.rebind(mode=mode)
    decision = assess(b)
    assert PaperReason.MODE_MISMATCH in decision.reasons
    assert PaperReason.FIXTURE_MODE_BLOCKED in decision.reasons


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("venue", Venue.EXNESS, PaperReason.VENUE_PRODUCT_INELIGIBLE),
        ("product", Product.PERPETUAL, PaperReason.VENUE_PRODUCT_INELIGIBLE),
        ("account_ref", "paper.wrong", PaperReason.ACCOUNT_UNKNOWN),
        ("side", "SELL", PaperReason.SHORT_UNSUPPORTED),
        ("stop", Decimal("50000"), PaperReason.STOP_INVALID),
        ("quantity", Decimal("0.0009"), PaperReason.MINIMUM_QUANTITY),
        ("entry", Decimal("49999.999"), PaperReason.PRICE_INVALID),
        ("action", MoneyAction.AMEND, PaperReason.SPEC_UNSUPPORTED),
        ("action", MoneyAction.WITHDRAW, PaperReason.SPEC_UNSUPPORTED),
    ],
)
def test_p4_intent_negatives(field: str, value: object, reason: PaperReason) -> None:
    b = fixture_bundle()
    b.intent = b.rebind(**{field: value})
    assert reason in assess(b).reasons


def test_p4_exact_hash_binding_every_input() -> None:
    b = fixture_bundle()
    for field in (
        "release_hash",
        "spec_hash",
        "snapshot_hash",
        "account_snapshot_hash",
        "policy_hash",
    ):
        forged = b.rebind(**{field: "f" * 64})
        result = assess_paper(forged, b.policy, b.market, b.spec, b.account, b.release, now=b.now)
        assert PaperReason.HASH_MISMATCH in result.reasons


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("health", "GAPPED", PaperReason.MARKET_INVALID),
        ("adverse_fx", None, PaperReason.FX_UNKNOWN),
        ("session_open", False, PaperReason.SESSION_CLOSED),
        ("clock_offset_ms", 251, PaperReason.CLOCK_OFFSET),
    ],
)
def test_p4_market_health(field: str, value: object, reason: PaperReason) -> None:
    b = fixture_bundle()
    b.market = changed(b.market, **{field: value})
    assert reason in assess(b).reasons


def test_p4_stale_future_expiry_and_utc_day_boundaries() -> None:
    b = fixture_bundle()
    b.market = changed(b.market, as_of=b.now - timedelta(seconds=3))
    assert PaperReason.MARKET_STALE in assess(b).reasons
    b = fixture_bundle()
    b.market = changed(b.market, fx_as_of=b.now - timedelta(seconds=3))
    assert PaperReason.FX_STALE in assess(b).reasons
    b = fixture_bundle()
    b.account = changed(
        b.account, as_of=b.now - timedelta(seconds=6), reconciled_at=b.now - timedelta(seconds=6)
    )
    assert PaperReason.ACCOUNT_STALE in assess(b).reasons
    b = fixture_bundle()
    b.spec = changed(b.spec, observed_at=b.now - timedelta(days=2))
    assert PaperReason.SPEC_STALE in assess(b).reasons
    b = fixture_bundle()
    b.now += timedelta(seconds=30)
    assert PaperReason.INTENT_EXPIRED in assess(b).reasons
    b = fixture_bundle()
    b.account = changed(b.account, day_start_at=b.account.day_start_at - timedelta(days=1))
    assert PaperReason.ACCOUNT_STALE in assess(b).reasons
    b = fixture_bundle()
    b.market = changed(b.market, available_at=b.now + timedelta(seconds=1))
    assert PaperReason.MARKET_INVALID in assess(b).reasons


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("contract_multiplier", Decimal("2"), PaperReason.SPEC_UNSUPPORTED),
        ("fill_semantics", "UNKNOWN", PaperReason.FILL_UNSUPPORTED),
        ("min_notional", Decimal("600"), PaperReason.MINIMUM_NOTIONAL),
        ("min_quantity", Decimal("0.0025"), PaperReason.SPEC_UNSUPPORTED),
    ],
)
def test_p4_unqualified_specs(field: str, value: object, reason: PaperReason) -> None:
    b = fixture_bundle()
    b.spec = changed(b.spec, **{field: value})
    assert reason in assess(b).reasons


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("max_trade_risk_fraction", PaperReason.TRADE_RISK_CAP),
        ("max_total_risk_fraction", PaperReason.TOTAL_RISK_CAP),
        ("max_asset_risk_fraction", PaperReason.ASSET_RISK_CAP),
        ("max_bucket_risk_fraction", PaperReason.BUCKET_RISK_CAP),
        ("max_gross_fraction", PaperReason.GROSS_CAP),
        ("max_net_fraction", PaperReason.NET_CAP),
        ("max_daily_loss_fraction", PaperReason.DAILY_LOSS_CAP),
        ("max_drawdown_fraction", PaperReason.DRAWDOWN_CAP),
    ],
)
def test_p4_zero_policy_caps(field: str, reason: PaperReason) -> None:
    b = fixture_bundle()
    b.policy = changed(b.policy, **{field: Decimal("0")})
    assert reason in assess(b).reasons


def test_p4_balance_margin_positions_rate_and_tiny_balances() -> None:
    b = fixture_bundle()
    b.account = changed(b.account, cash=Decimal("500"))
    assert PaperReason.BALANCE_CAP in assess(b).reasons
    b = fixture_bundle()
    b.spec = changed(b.spec, margin_fraction=Decimal("1"))
    b.policy = changed(b.policy, max_margin_fraction=Decimal("0"))
    assert PaperReason.MARGIN_CAP in assess(b).reasons
    b = fixture_bundle()
    b.policy = changed(b.policy, max_positions=0, max_intents_per_minute=0)
    result = assess(b)
    assert PaperReason.POSITIONS_CAP in result.reasons
    assert PaperReason.ORDER_RATE_CAP in result.reasons
    tiny = fixture_bundle(equity="0.01")
    assert PaperReason.TRADE_RISK_CAP in assess(tiny).reasons
    assert PaperReason.BALANCE_CAP in assess(tiny).reasons


def test_p4_pending_all_caps_duplicate_unknown_and_expiry_retention() -> None:
    b = fixture_bundle()
    original = reservation(b)
    # Different logical/hash identity, but same bucket risk accumulates.
    reservations = tuple(
        changed(original, reservation_id=uuid4(), intent_hash=f"{i:064x}", logical_key=f"other.{i}")
        for i in range(4)
    )
    result = assess(b, reservations)
    assert PaperReason.BUCKET_RISK_CAP in result.reasons
    assert PaperReason.ASSET_RISK_CAP in result.reasons
    unknown = changed(
        original,
        state="UNKNOWN",
        expires_at=b.now - timedelta(seconds=1),
        created_at=b.now - timedelta(seconds=20),
    )
    assert PaperReason.UNKNOWN_ORDER in assess(b, (unknown,)).reasons
    duplicate = changed(original, logical_key=b.intent.logical_key)
    assert PaperReason.DUPLICATE_INTENT in assess(b, (duplicate,)).reasons
    b.account = changed(b.account, prior_logical_keys=(b.intent.logical_key,))
    assert PaperReason.DUPLICATE_INTENT in assess(b).reasons


def test_p4_observed_flows_do_not_erase_loss_or_drawdown() -> None:
    b = fixture_bundle()
    b.account = changed(
        b.account,
        equity=Decimal("10900"),
        day_net_flows=Decimal("1000"),
        net_flows_since_high_water=Decimal("1000"),
    )
    assert PaperReason.DAILY_LOSS_CAP in assess(b).reasons
    b.account = changed(
        b.account,
        equity=Decimal("8400"),
        day_net_flows=Decimal("-1000"),
        net_flows_since_high_water=Decimal("-1000"),
    )
    result = assess(b)
    assert PaperReason.DAILY_LOSS_CAP in result.reasons
    assert PaperReason.DRAWDOWN_CAP in result.reasons
    # An observed deposit can never clear explicit suspension/pause.
    b.account = changed(
        b.account,
        equity=Decimal("20000"),
        day_net_flows=Decimal("10000"),
        net_flows_since_high_water=Decimal("10000"),
        kill=KillLevel.K1,
    )
    assert PaperReason.KILL_BLOCKED in assess(b).reasons


@pytest.mark.parametrize("level", list(KillLevel))
def test_p4_kills_reduce_only_fresh_known_position(level: KillLevel) -> None:
    b = fixture_bundle()
    b.account = changed(b.account, positions=(position(b),), kill=level)
    if level != KillLevel.K0:
        assert PaperReason.KILL_BLOCKED in assess(b).reasons
    b.intent = b.rebind(action=MoneyAction.CLOSE, side="SELL", position_ref="position.one")
    result = assess(b)
    assert result.status == ("DENIED" if level == KillLevel.K4 else "APPROVED")
    # Even a kill close cannot over-close/reverse or use stale truth.
    b.intent = b.rebind(quantity=Decimal("0.011"))
    assert PaperReason.OVER_CLOSE in assess(b).reasons
    b.intent = b.rebind(quantity=Decimal("0.01"))
    b.account = changed(b.account, journal_healthy=False)
    assert PaperReason.JOURNAL_UNHEALTHY in assess(b).reasons


def test_p4_close_capacity_pending_does_not_release_open_capacity() -> None:
    b = fixture_bundle()
    b.account = changed(b.account, positions=(position(b),), kill=KillLevel.K3)
    b.intent = b.rebind(action=MoneyAction.CLOSE, side="SELL", position_ref="position.one")
    r = reservation(
        b,
        action=MoneyAction.CLOSE,
        position_ref="position.one",
        quantity=Decimal("0.006"),
        intent_hash="f" * 64,
    )
    assert PaperReason.OVER_CLOSE in assess(b, (r,)).reasons
    b.intent = b.rebind(quantity=Decimal("0.004"))
    assert assess(b, (r,)).status == "APPROVED"
    b.account = changed(b.account, unknown_orders=True)
    assert PaperReason.UNKNOWN_ORDER in assess(b, (r,)).reasons


def test_p4_cancel_exact_target_and_duplicate_cancel() -> None:
    b = fixture_bundle()
    target = reservation(b, intent_hash="f" * 64)
    b.account = changed(b.account, kill=KillLevel.K2)
    b.intent = b.rebind(action=MoneyAction.CANCEL, target_intent_ref=target.intent_id)
    result = assess(b, (target,))
    assert result.status == "APPROVED"
    cancel = changed(
        target, action=MoneyAction.CANCEL, intent_hash="e" * 64, target_intent_ref=target.intent_id
    )
    assert PaperReason.DUPLICATE_INTENT in assess(b, (target, cancel)).reasons
    b.intent = b.rebind(target_intent_ref=uuid4())
    assert PaperReason.TARGET_UNKNOWN in assess(b, (target,)).reasons


def test_p4_authorization_is_exact_expiring_nonexternal_and_no_stale_bypass() -> None:
    b = fixture_bundle()
    decision = assess(b)
    auth = bind_authorization(decision, b.intent, b.account, uuid4(), uuid4(), b.now)
    r = reservation(b, reservation_id=auth.reservation_id, logical_key=b.intent.logical_key)
    assert verify_authorization(
        auth,
        b.intent,
        b.policy,
        b.market,
        b.spec,
        b.account,
        b.release,
        r,
        now=b.now,
        reservations=(r,),
    )
    for field in (
        "intent_hash",
        "policy_hash",
        "account_snapshot_hash",
        "market_hash",
        "spec_hash",
        "release_hash",
    ):
        altered = changed(auth, **{field: "f" * 64})
        assert not verify_authorization(
            altered, b.intent, b.policy, b.market, b.spec, b.account, b.release, r, now=b.now
        )
    assert not verify_authorization(
        auth, b.intent, b.policy, b.market, b.spec, b.account, b.release, r, now=b.intent.expires_at
    )
    newer = changed(b.account, epoch=b.account.epoch + 1)
    assert not verify_authorization(
        auth, b.intent, b.policy, b.market, b.spec, newer, b.release, r, now=b.now
    )
    changed_r = changed(r, modeled_loss=Decimal("0"))
    assert not verify_authorization(
        auth, b.intent, b.policy, b.market, b.spec, b.account, b.release, changed_r, now=b.now
    )
    with pytest.raises(ValidationError):
        changed(auth, semantics="LIVE")
    with pytest.raises(ValueError, match="BINDING_DENIED"):
        bind_authorization(
            decision,
            changed(b.intent, quantity=Decimal("0.02")),
            b.account,
            uuid4(),
            uuid4(),
            b.now,
        )


@given(st.integers(min_value=1, max_value=20000))
def test_p4_quantization_never_rounds_up(units: int) -> None:
    quantity = Decimal(units) / Decimal("1000000")
    b = fixture_bundle(quantity=format(quantity, "f"))
    result = assess(b)
    assert result.exposure is not None
    rounded = result.exposure.quantity
    assert rounded <= quantity
    assert rounded % b.spec.quantity_step == 0
    assert quantity - rounded < b.spec.quantity_step


@given(st.integers(min_value=0, max_value=10000))
def test_p4_stricter_trade_cap_never_allows_previously_denied_risk(limit: int) -> None:
    b = fixture_bundle()
    b.policy = changed(b.policy, max_trade_risk_fraction=Decimal(limit) / Decimal("1000000"))
    result = assess(b)
    assert result.exposure is not None
    expected = result.exposure.modeled_loss > b.account.equity * b.policy.max_trade_risk_fraction
    assert (PaperReason.TRADE_RISK_CAP in result.reasons) == expected


def test_p4_reason_order_and_no_arbitrary_authorization() -> None:
    b = fixture_bundle()
    b.account = changed(b.account, kill=KillLevel.K4, reconciled=False, unknown_orders=True)
    b.market = changed(b.market, health="UNKNOWN")
    decision = assess(b)
    assert decision.reasons == tuple(reason for reason in PaperReason if reason in decision.reasons)
    with pytest.raises(ValueError):
        bind_authorization(decision, b.rebind(), b.account, uuid4(), uuid4(), b.now)
    with pytest.raises(ValidationError):
        PaperAuthorization.model_validate({"permit": "enable"})


def test_p4_position_risk_uses_conservative_current_mark() -> None:
    b = fixture_bundle()
    # Profit increases current equity; mark-to-stop downside cannot remain the old 10.
    b.account = changed(b.account, positions=(position(b, mark_price=Decimal("60000")),))
    result = assess(b)
    assert PaperReason.TOTAL_RISK_CAP in result.reasons
    assert PaperReason.BUCKET_RISK_CAP in result.reasons
    assert PaperReason.DAILY_LOSS_CAP in result.reasons


def test_p4_three_distinct_btc_positions_are_three_positions() -> None:
    b = fixture_bundle()
    b.account = changed(
        b.account,
        positions=tuple(position(b, position_ref=f"position.{index}") for index in range(3)),
    )
    assert PaperReason.POSITIONS_CAP in assess(b).reasons


def test_p4_released_reservation_not_capacity_but_historical_key_still_duplicate() -> None:
    b = fixture_bundle()
    r = reservation(b, state="RELEASED", logical_key=b.intent.logical_key)
    assert assess(b, (r,)).status == "APPROVED"
    b.account = changed(b.account, prior_logical_keys=(b.intent.logical_key,))
    assert PaperReason.DUPLICATE_INTENT in assess(b, (r,)).reasons


def test_p4_daily_pending_risk_applies_before_marked_limit() -> None:
    b = fixture_bundle()
    b.account = changed(b.account, equity=Decimal("9910"))
    # Current loss90 <100 but candidate worst-case11.8675 takes it beyond100.
    result = assess(b)
    assert PaperReason.DAILY_LOSS_CAP in result.reasons


def test_p4_deep_construct_bypass_rejected() -> None:
    b = fixture_bundle()
    fake_position = position(b).model_copy(update={"quantity": Decimal("Infinity")})
    fake_account = b.account.model_copy(update={"positions": (fake_position,)})
    result = assess_paper(b.intent, b.policy, b.market, b.spec, fake_account, b.release, now=b.now)
    assert result.reasons == (PaperReason.INVALID_INPUT,)


@pytest.mark.parametrize("offset", [-1, 1])
def test_p4_clock_and_freshness_microsecond_boundaries(offset: int) -> None:
    b = fixture_bundle()
    age = timedelta(seconds=2, microseconds=offset)
    b.market = changed(b.market, as_of=b.now - age)
    result = assess(b)
    assert (PaperReason.MARKET_STALE in result.reasons) == (offset == 1)


def test_p4_policy_cannot_widen_checkpoint_to_exness() -> None:
    b = fixture_bundle()
    b.policy = changed(b.policy, allowed_venues=(Venue.EXNESS,))
    b.spec = changed(b.spec, venue=Venue.EXNESS)
    b.intent = b.rebind(venue=Venue.EXNESS)
    assert PaperReason.VENUE_PRODUCT_INELIGIBLE in assess(b).reasons


@pytest.mark.parametrize("state", [ReleaseState.SUSPENDED, ReleaseState.RETIRED])
def test_p4_suspended_release_can_reduce_known_fresh_position(state: ReleaseState) -> None:
    b = fixture_bundle()
    b.account = changed(b.account, positions=(position(b),), kill=KillLevel.K3)
    b.release = changed(b.release, state=state)
    assert PaperReason.RELEASE_INELIGIBLE in assess(b).reasons
    b.intent = b.rebind(action=MoneyAction.CLOSE, side="SELL", position_ref="position.one")
    assert assess(b).status == "APPROVED"
    b.market = changed(b.market, as_of=b.now - timedelta(seconds=3))
    assert PaperReason.MARKET_STALE in assess(b).reasons


@pytest.mark.parametrize("reference", ["position.one", "position.eth", "paper.other.position"])
def test_p4_open_rejects_every_position_reference_without_mutation(reference: str) -> None:
    b = fixture_bundle(quantity="0.001", stop="40000")
    original = position(b, quantity=Decimal("0.100"), stop_price=Decimal("49999"))
    b.account = changed(b.account, positions=(original,))
    before = b.account.canonical_bytes()
    old_position = original.canonical_bytes()
    with pytest.raises(ValidationError, match="OPEN_REQUIRES_NEW_POSITION"):
        b.rebind(position_ref=reference)
    # A caller skipping Pydantic validation still cannot reach risk approval.
    forged = b.rebind().model_copy(update={"position_ref": reference})
    result = assess_paper(forged, b.policy, b.market, b.spec, b.account, b.release, now=b.now)
    assert result.status == "DENIED"
    assert result.reasons == (PaperReason.INVALID_INPUT,)
    assert b.account.canonical_bytes() == before
    assert b.account.positions[0].canonical_bytes() == old_position
    assert b.account.positions[0].quantity == Decimal("0.100")
    assert b.account.positions[0].stop_price == Decimal("49999")


def test_p4_open_cannot_reference_cross_instrument_position() -> None:
    b = fixture_bundle(quantity="0.001")
    original = position(b, instrument_id="paper.spot.ETHUSD", position_ref="position.eth")
    b.account = changed(b.account, positions=(original,))
    before = b.account.canonical_bytes()
    with pytest.raises(ValidationError, match="OPEN_REQUIRES_NEW_POSITION"):
        b.rebind(position_ref=original.position_ref)
    assert b.account.canonical_bytes() == before
    assert b.account.positions[0].instrument_id == "paper.spot.ETHUSD"


@pytest.mark.parametrize("reservation_state", ["ACTIVE", "PARTIAL", "UNKNOWN"])
def test_p4_pending_uuid_reuse_denied_even_under_new_logical_key(reservation_state: str) -> None:
    b = fixture_bundle()
    pending = reservation(
        b,
        intent_id=b.intent.intent_id,
        logical_key="previous.logical",
        intent_hash="f" * 64,
        state=reservation_state,
    )
    b.intent = b.rebind(logical_key="different.logical")
    assert PaperReason.DUPLICATE_INTENT in assess(b, (pending,)).reasons


def test_p4_terminal_uuid_reuse_is_denied_from_immutable_history() -> None:
    b = fixture_bundle()
    b.account = changed(b.account, prior_intent_ids=(b.intent.intent_id,))
    before = b.account.canonical_bytes()
    b.intent = b.rebind(logical_key="different.logical")
    result = assess(b)
    assert result.status == "DENIED"
    assert PaperReason.DUPLICATE_INTENT in result.reasons
    assert b.account.canonical_bytes() == before


def test_p4_generated_position_collision_denied_even_without_prior_id_projection() -> None:
    b = fixture_bundle(quantity="0.001")
    original = position(
        b, position_ref=paper_position_ref(b.account.account_ref, b.intent.intent_id)
    )
    b.account = changed(b.account, positions=(original,))
    before = original.canonical_bytes()
    assert PaperReason.DUPLICATE_INTENT in assess(b).reasons
    assert b.account.positions[0].canonical_bytes() == before


def test_p4_independent_open_identity_is_deterministic_account_scoped_and_distinct() -> None:
    b = fixture_bundle()
    first_id, second_id = uuid4(), uuid4()
    first = paper_position_ref("paper.test", first_id)
    assert first == paper_position_ref("paper.test", first_id)
    assert first != paper_position_ref("paper.test", second_id)
    assert first != paper_position_ref("paper.other", first_id)
    assert len(first) == 73 and first.startswith("position.")
    first_intent = b.rebind(intent_id=first_id, logical_key="first.independent")
    second_intent = b.rebind(intent_id=second_id, logical_key="second.independent")
    for intent in (first_intent, second_intent):
        result = assess_paper(intent, b.policy, b.market, b.spec, b.account, b.release, now=b.now)
        assert result.status == "APPROVED"
        assert intent.position_ref is None
    with pytest.raises(ValueError, match="VIRTUAL_PAPER_IDENTITY"):
        paper_position_ref("real.account", first_id)


def test_p4_uuid_history_requires_exact_canonical_identifiers() -> None:
    b = fixture_bundle()
    with pytest.raises(ValidationError):
        changed(b.account, prior_intent_ids=("not-a-uuid",))
    with pytest.raises(ValidationError, match="DUPLICATE_PRIOR_INTENT_ID"):
        changed(b.account, prior_intent_ids=(b.intent.intent_id, b.intent.intent_id))
