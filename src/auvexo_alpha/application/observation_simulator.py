"""Pure causal simulated-fill calculations over immutable domain inputs."""

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_DOWN, Decimal
from typing import Literal

from auvexo_alpha.domain.contracts import MoneyAction, utc_time
from auvexo_alpha.domain.observation import (
    ObservationFact,
)
from auvexo_alpha.domain.paper import PaperIntent

SIMULATOR_VERSION: Literal["paper.observation.simulator.v1"] = "paper.observation.simulator.v1"


@dataclass(frozen=True)
class PendingSimulation:
    intent: PaperIntent
    source: ObservationFact
    quantity: Decimal


def causal_fill_price(
    pending: PendingSimulation, later: ObservationFact, *, now: datetime
) -> Decimal | None:
    """A later received final close may satisfy the original simulated limit only."""
    now = utc_time(now)
    before, after = pending.source.candle, later.candle
    if (
        after.instrument_id != pending.intent.instrument_id
        or before.instrument_id != after.instrument_id
        or after.source.source_id != "DS-02"
        or after.finalization != "FINAL"
        or after.interval != "1m"
        or after.end_at <= before.end_at
        or after.availability.available_at <= before.availability.available_at
        or after.source.received_at <= before.source.received_at
        or now < after.availability.available_at
        or later.content_hash() == pending.source.content_hash()
    ):
        raise ValueError("OBSERVATION_FILL_CAUSALITY_DENIED")
    if now >= pending.intent.expires_at:
        return None
    # Accepted slippage assumption: five basis points adverse, never a better limit.
    slip = Decimal("0.0005")
    price = after.close * (
        Decimal("1") + slip if pending.intent.action == MoneyAction.OPEN else Decimal("1") - slip
    )
    price = price.quantize(Decimal("0.000000000000000001"), rounding=ROUND_DOWN)
    if pending.intent.action == MoneyAction.OPEN:
        return price if pending.intent.stop < price <= pending.intent.entry else None
    if pending.intent.action == MoneyAction.CLOSE:
        return price if price >= pending.intent.entry else None
    raise ValueError("OBSERVATION_FILL_ACTION_DENIED")
