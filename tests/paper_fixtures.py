"""Synthetic PAPER engineering fixtures; no market or alpha observations."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from auvexo_alpha.domain.contracts import Mode, Product, Venue
from auvexo_alpha.domain.paper import (
    PaperAccountSnapshot,
    PaperInstrumentSpec,
    PaperIntent,
    PaperMarketSnapshot,
    PaperPolicy,
    provisional_policy,
)
from auvexo_alpha.domain.paper_lifecycle import (
    KillLevel,
    Release,
    ReleaseDataEligibility,
    ReleaseKind,
    ReleaseState,
    SourceEligibility,
)
from auvexo_alpha.domain.research import DataUseClass

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)
HASH = "1" * 64


@dataclass
class PaperFixture:
    intent: PaperIntent
    policy: PaperPolicy
    market: PaperMarketSnapshot
    spec: PaperInstrumentSpec
    account: PaperAccountSnapshot
    release: Release
    now: datetime

    def rebind(self, **changes: object) -> PaperIntent:
        payload = self.intent.model_dump()
        payload.update(
            policy_hash=self.policy.content_hash(),
            account_snapshot_hash=self.account.content_hash(),
            snapshot_hash=self.market.content_hash(),
            spec_hash=self.spec.content_hash(),
            release_hash=self.release.content_hash(),
        )
        payload.update(changes)
        return PaperIntent.model_validate(payload)


def fixture_bundle(
    *,
    instrument_id: str = "paper.spot.BTCUSD",
    account_ref: str = "paper.test",
    equity: str = "10000",
    quantity: str = "0.01",
    entry: str = "50000",
    stop: str = "49000",
    now: datetime | None = None,
) -> PaperFixture:
    instant = NOW if now is None else now
    policy_payload = provisional_policy().model_dump()
    policy_payload["allowed_accounts"] = (account_ref,)
    policy = PaperPolicy.model_validate(policy_payload)
    account = PaperAccountSnapshot(
        account_ref=account_ref,
        epoch=1,
        snapshot_id=uuid4(),
        as_of=instant,
        reconciled_at=instant,
        day_start_at=instant.replace(hour=0, minute=0, second=0, microsecond=0),
        cash=Decimal(equity),
        equity=Decimal(equity),
        high_water_equity=Decimal(equity),
        day_start_equity=Decimal(equity),
        reconciled=True,
        kill=KillLevel.K0,
    )
    spec = PaperInstrumentSpec(
        instrument_id=instrument_id,
        spec_version="paper.spot.v1",
        fixture_version="linear.synthetic.v1",
        base_currency="EUR"
        if "SYNTH" in instrument_id
        else "ETH"
        if "ETH" in instrument_id
        else "BTC",
        quote_currency="USD",
        account_currency="USD",
        contract_multiplier=Decimal("1"),
        price_tick=Decimal("0.01"),
        quantity_step=Decimal("0.001"),
        min_quantity=Decimal("0.001"),
        max_quantity=Decimal("1000000"),
        min_notional=Decimal("1"),
        margin_fraction=Decimal("0"),
        observed_at=instant,
    )
    market = PaperMarketSnapshot(
        snapshot_id=uuid4(),
        instrument_id=instrument_id,
        as_of=instant,
        available_at=instant,
        bid=Decimal(entry),
        ask=Decimal(entry),
        adverse_fx=Decimal("1.01"),
        fx_as_of=instant,
        health="HEALTHY",
        session_open=True,
        clock_offset_ms=0,
    )
    release = Release(
        release_id="paper.fixture.fixed.v1",
        kind=ReleaseKind.TEST_ONLY,
        state=ReleaseState.PAPER,
        code_hash=HASH,
        config_hash=HASH,
        data_hash=HASH,
        evidence_hash=HASH,
        allowed_modes=(Mode.PAPER,),
        approved_by=("owner.fixture",),
        created_at=instant,
        data_use=DataUseClass.ENGINEERING_ONLY,
        independent_evidence=False,
        fixture_namespace="PAPER_QUALIFICATION_FIXTURE",
    )
    intent = PaperIntent(
        intent_id=uuid4(),
        logical_key=f"fixture.{uuid4()}",
        account_ref=account_ref,
        instrument_id=instrument_id,
        quantity=Decimal(quantity),
        entry=Decimal(entry),
        stop=Decimal(stop),
        release_hash=release.content_hash(),
        spec_hash=spec.content_hash(),
        snapshot_hash=market.content_hash(),
        account_snapshot_hash=account.content_hash(),
        policy_hash=policy.content_hash(),
        created_at=instant,
        expires_at=instant + timedelta(seconds=30),
    )
    return PaperFixture(intent, policy, market, spec, account, release, instant)


def research_release(*, eligible: bool) -> Release:
    b = fixture_bundle()
    # Typed, hypothetical future acceptance metadata; never inserted in an operational registry.
    eligibility = (
        ReleaseDataEligibility(
            inputs=(
                SourceEligibility(
                    source_id="synthetic.future.source",
                    venue=Venue.BINANCE,
                    product=Product.SPOT,
                    instrument_id="paper.spot.BTCUSD",
                    range_start=b.now - timedelta(days=2),
                    range_end=b.now - timedelta(days=1),
                    dataset_hash=HASH,
                    rights_snapshot_hash=HASH,
                    rights_valid_until=b.now + timedelta(days=1),
                    availability_version="synthetic.v1",
                    availability_hash=HASH,
                    classification=DataUseClass.PROMOTION_ELIGIBLE,
                    intended_use="PROMOTION",
                    reviewer="synthetic.independent.reviewer",
                    reviewed_at=b.now,
                    acceptance_evidence_hash=HASH,
                ),
            )
        )
        if eligible
        else None
    )
    return Release(
        release_id="generic.research.v1",
        kind=ReleaseKind.RESEARCH_EVIDENCED,
        state=ReleaseState.RESEARCH,
        code_hash=HASH,
        config_hash=HASH,
        data_hash=eligibility.content_hash() if eligibility is not None else HASH,
        evidence_hash=HASH,
        allowed_modes=(Mode.PAPER,),
        approved_by=("owner", "independent.reviewer"),
        created_at=b.now,
        data_use=DataUseClass.PROMOTION_ELIGIBLE if eligible else DataUseClass.PERSONAL_RESEARCH,
        independent_evidence=eligible,
        data_eligibility=eligibility,
    )
