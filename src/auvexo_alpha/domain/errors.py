"""Sanitized error vocabulary shared by local adapters."""

from enum import StrEnum
from typing import Literal

from auvexo_alpha.domain.contracts import Contract


class ErrorCode(StrEnum):
    NOT_AVAILABLE = "NOT_AVAILABLE"
    BLOCKED_BY_POLICY = "BLOCKED_BY_POLICY"
    INVALID_INPUT = "INVALID_INPUT"
    UNAUTHORIZED = "UNAUTHORIZED"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"


class Denial(Contract):
    status: Literal["DENIED"] = "DENIED"
    code: ErrorCode
    retryable: Literal[False] = False
    reason: Literal["PHASE_1_EXECUTION_DISABLED", "BINANCE_LIVE_DERIVATIVES_BLOCKED"]
