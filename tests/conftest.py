"""Synthetic inputs only. No broker credentials or real market observations."""

import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr

from auvexo_alpha.config import Settings
from auvexo_alpha.domain.contracts import EvidenceRefs, Mode, MoneyAction, Product, Venue


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_password=SecretStr(secrets.token_urlsafe(32)),
        api_token=SecretStr(secrets.token_urlsafe(32)),
    )


@pytest.fixture
def intent_data() -> dict[str, object]:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return dict(
        command_id=uuid4(),
        correlation_id=uuid4(),
        source_id="synthetic-test",
        mode=Mode.PAPER,
        created_at=now,
        expires_at=now + timedelta(minutes=1),
        candidate_id=uuid4(),
        intent_id=uuid4(),
        instrument_id="synthetic-BTCUSD",
        venue=Venue.EXNESS,
        product=Product.CFD,
        side="BUY",
        quantity="0.01",
        proposed_entry="100",
        proposed_stop="90",
        market_state_id=uuid4(),
        evidence=EvidenceRefs(
            source_ids=("synthetic-test",), dataset_version="0" * 64, strategy_version="test-only"
        ),
        account_ref="synthetic-account",
        action=MoneyAction.OPEN,
        policy_version="phase1.disabled.v1",
        time_in_force="IOC",
    )
