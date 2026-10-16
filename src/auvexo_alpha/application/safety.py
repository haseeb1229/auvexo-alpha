"""Zero-capability execution boundary. There is deliberately no adapter registry."""

from pydantic import ValidationError

from auvexo_alpha.domain.contracts import Mode, Product, TradeIntent, Venue
from auvexo_alpha.domain.errors import Denial, ErrorCode

POLICY_VERSION = "phase1.disabled.v1"


def deny_execution(payload: object) -> Denial:
    try:
        intent = TradeIntent.model_validate(payload)
    except ValidationError:
        return Denial(code=ErrorCode.INVALID_INPUT, reason="PHASE_1_EXECUTION_DISABLED")
    if (
        intent.venue == Venue.BINANCE
        and intent.product == Product.PERPETUAL
        and intent.mode in (Mode.LIVE, Mode.LIVE_LIMITED)
    ):
        return Denial(code=ErrorCode.BLOCKED_BY_POLICY, reason="BINANCE_LIVE_DERIVATIVES_BLOCKED")
    return Denial(code=ErrorCode.NOT_AVAILABLE, reason="PHASE_1_EXECUTION_DISABLED")
