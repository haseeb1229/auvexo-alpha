"""P-3/P-14 kernel refinements with hand-computed oracles; synthetic fixtures only."""

import hashlib
import json
from decimal import Decimal

import pytest
from paper_fixtures import fixture_bundle
from pydantic import ValidationError
from test_paper_risk import assess, changed, position

from auvexo_alpha.domain.contracts import MoneyAction
from auvexo_alpha.domain.paper import (
    DEFAULT_MAX_SPREAD_BPS,
    PaperPolicy,
    PaperReason,
    provisional_policy,
    spec_terms_hash,
)
from auvexo_alpha.domain.paper_risk import loss_limits

NEW_POLICY_FIELDS = (
    "max_spread_bps",
    "input_trust",
    "pinned_spec_terms",
    "max_store_clock_skew_ms",
)


def _legacy_hash(payload: dict[str, object]) -> str:
    """Hash restated without any field added after v1; independent of the contract code."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def test_legacy_policy_and_market_hashes_are_unchanged_by_new_default_fields() -> None:
    policy = provisional_policy()
    payload = json.loads(policy.canonical_bytes())
    assert not set(NEW_POLICY_FIELDS) & set(payload)
    full = json.loads(policy.model_dump_json())
    for key in NEW_POLICY_FIELDS:
        full.pop(key)
    assert policy.content_hash() == _legacy_hash(payload)
    assert set(full) == set(payload)
    market = fixture_bundle().market
    assert "price_basis" not in json.loads(market.canonical_bytes())
    # A stated non-default value is part of the identity.
    tighter = changed(policy, max_spread_bps=Decimal("10"))
    assert json.loads(tighter.canonical_bytes())["max_spread_bps"] == "10"
    assert tighter.content_hash() != policy.content_hash()
    bar = changed(market, price_basis="BAR_CLOSE")
    assert bar.content_hash() != market.content_hash()
    assert policy.max_spread_bps == DEFAULT_MAX_SPREAD_BPS == Decimal("50")


def test_bar_close_snapshot_states_its_zero_spread() -> None:
    market = fixture_bundle().market
    with pytest.raises(ValidationError, match="BAR_CLOSE_SPREAD_MUST_BE_ZERO"):
        changed(market, price_basis="BAR_CLOSE", bid=market.ask - Decimal("0.01"))
    bar = changed(market, price_basis="BAR_CLOSE")
    assert bar.spread_bps() == 0


@pytest.mark.parametrize(
    ("bid", "denied"),
    [
        # (40200 - 40000) * 10000 / 40000 = 50 bps exactly: at the cap, allowed.
        ("40000", False),
        # 200.01 * 10000 / 39999.99 = 50.0025.. bps: one tick past the cap.
        ("39999.99", True),
    ],
)
def test_spread_gate_boundary_for_entries(bid: str, denied: bool) -> None:
    b = fixture_bundle(entry="40200", stop="39500")
    b.market = changed(b.market, bid=Decimal(bid))
    result = assess(b)
    assert (PaperReason.SPREAD_WIDE in result.reasons) is denied
    assert result.status == ("DENIED" if denied else "APPROVED")


def test_spread_gate_never_blocks_a_reduce_only_close() -> None:
    b = fixture_bundle()
    b.policy = changed(b.policy, max_spread_bps=Decimal("0"))
    b.market = changed(b.market, ask=b.market.bid + Decimal("100"))
    b.account = changed(b.account, positions=(position(b),))
    b.intent = b.rebind(action=MoneyAction.CLOSE, side="SELL", position_ref="position.one")
    assert assess(b).status == "APPROVED"


def test_store_verified_policy_requires_pins_and_pins_exclude_observation_time() -> None:
    b = fixture_bundle()
    with pytest.raises(ValidationError, match="PAPER_POLICY_TRUST_INVALID"):
        changed(b.policy, input_trust="STORE_VERIFIED")
    later = changed(b.spec, observed_at=b.spec.observed_at.replace(hour=13))
    assert spec_terms_hash(later) == spec_terms_hash(b.spec)
    assert spec_terms_hash(changed(b.spec, min_quantity=Decimal("0.002"))) != spec_terms_hash(
        b.spec
    )
    b.policy = changed(
        b.policy, input_trust="STORE_VERIFIED", pinned_spec_terms=(spec_terms_hash(b.spec),)
    )
    assert assess(b).status == "APPROVED"
    b.spec = changed(b.spec, price_tick=Decimal("0.1"))
    result = assess(b)
    assert PaperReason.SPEC_UNPINNED in result.reasons
    # The caller-supplied trust level cannot be raised or lowered by a caller policy copy:
    # the store authorizes against the owner-pinned policy row (PostgreSQL tests).
    assert PaperPolicy.model_validate_json(b.policy.canonical_bytes()) == b.policy


def test_full_dust_close_below_minimums_is_allowed_partial_dust_is_not() -> None:
    b = fixture_bundle()
    dust = position(b, quantity=Decimal("0.0005"))
    b.account = changed(b.account, positions=(dust,))
    b.spec = changed(b.spec, min_notional=Decimal("100"))
    b.intent = b.rebind(
        action=MoneyAction.CLOSE,
        side="SELL",
        position_ref="position.one",
        quantity=Decimal("0.0005"),
    )
    result = assess(b)
    assert result.status == "APPROVED"
    assert result.exposure is not None and result.exposure.quantity == Decimal("0.0005")
    # A partial dust close of a larger position keeps every minimum.
    b.account = changed(b.account, positions=(position(b, quantity=Decimal("0.0015")),))
    b.intent = b.rebind(quantity=Decimal("0.0005"))
    reasons = assess(b).reasons
    assert PaperReason.MINIMUM_QUANTITY in reasons
    assert PaperReason.MINIMUM_NOTIONAL in reasons
    # An off-step whole remainder is still closable exactly; an over-close never is.
    b.intent = b.rebind(quantity=Decimal("0.0015"))
    assert assess(b).status == "APPROVED"
    b.intent = b.rebind(quantity=Decimal("0.0016"))
    assert PaperReason.OVER_CLOSE in assess(b).reasons


def test_withdrawal_cannot_loosen_percentage_caps() -> None:
    b = fixture_bundle()
    # Day start and high water 10000; 9000 withdrawn; equity 991 after a 9 loss.
    account = changed(
        b.account,
        equity=Decimal("991"),
        high_water_equity=Decimal("10000"),
        day_start_equity=Decimal("10000"),
        day_net_flows=Decimal("-9000"),
        net_flows_since_high_water=Decimal("-9000"),
    )
    daily, daily_cap, drawdown, drawdown_cap = loss_limits(account, b.policy)
    # daily = 10000 - (991 + 9000) = 9; base min(10000, 1000) = 1000; cap 1% = 10.
    assert (daily, daily_cap) == (Decimal("9"), Decimal("10.00"))
    # drawdown = 9; base 1000; cap 5% = 50 (it was 500 before the base followed outflows).
    assert (drawdown, drawdown_cap) == (Decimal("9"), Decimal("50.00"))
    b.account = account
    b.intent = b.rebind(quantity=Decimal("0.001"))
    # New risk .001*1000*1.01 + 50.5*.0035 = 1.18675; 9 + 1.18675 > 10.
    result = assess(b)
    assert PaperReason.DAILY_LOSS_CAP in result.reasons
    assert not {
        PaperReason.TRADE_RISK_CAP,
        PaperReason.TOTAL_RISK_CAP,
        PaperReason.DRAWDOWN_CAP,
    } & set(result.reasons)
    # A deposit never raises a base.
    deposit = changed(b.account, equity=Decimal("11000"), day_net_flows=Decimal("1000"))
    assert loss_limits(deposit, b.policy)[1] == Decimal("100.00")


def test_new_reasons_keep_every_earlier_reason_order() -> None:
    names = [reason.name for reason in PaperReason]
    assert names[-5:] == [
        "SPREAD_WIDE",
        "MARKET_UNVERIFIED",
        "SPEC_UNPINNED",
        "SPEC_UNOBSERVED",
        "CLOCK_UNTRUSTED",
    ]
    assert names.index("TARGET_UNKNOWN") == len(names) - 6
