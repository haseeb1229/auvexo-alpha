"""Versioned, bounded presentation contracts; never financial authorization."""

from datetime import datetime
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

State = Literal["AVAILABLE", "UNKNOWN", "UNAVAILABLE", "STALE"]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Amount = Annotated[str, Field(pattern=r"^-?(0|[1-9][0-9]{0,17})(\.[0-9]{1,18})?$")]
Count = Annotated[int, Field(ge=0, le=10000)]
ReviewedDate = Annotated[str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]
# The single place the static reviewed wording below is dated. It changes only together
# with a reviewed wording change; it is never a measurement time or a readiness claim.
REVIEWED_AS_OF: Final = "2026-11-12"
# Closed reviewed vocabulary; stored journal kind text is never forwarded to a client.
JournalReason = Literal[
    "AUTHORIZED",
    "DENIED",
    "KILL_STATE",
    "RECONCILIATION",
    "UNKNOWN_ORDER",
    "LOSS_LATCH",
    "DISPATCH_ATTEMPT",
    "OWNER_RESUME",
    "MARK_HEALTH",
    "WRITER_ACQUIRED",
    "OWNER_PIN",
    "EDGE_STATE",
    "DAY_ROLLOVER",
    "INITIALIZED",
    "OTHER",
]


class View(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


class Freshness(View):
    state: State
    observed_at: datetime | None = None
    provenance: Literal[
        "LOCAL_DIAGNOSTICS", "UNCONNECTED", "ISOLATED_SYNTHETIC_PAPER", "REVIEWED_ENGINEERING"
    ]
    reason: Literal[
        "CURRENT",
        "NOT_CONNECTED",
        "READ_UNAVAILABLE",
        "SOURCE_STALE",
        "REVIEWED_SUMMARY",
        "NO_EVENTS",
    ]

    @field_validator("observed_at")
    @classmethod
    def utc_only(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            offset = value.utcoffset()
            if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
                raise ValueError("UTC_REQUIRED")
        return value


class SystemView(View):
    contract_version: Literal["1"] = "1"
    version: str = Field(max_length=32, pattern=r"^[0-9.]+$")
    build: Literal["PHASE7_READ_ONLY_FOUNDATION"] = "PHASE7_READ_ONLY_FOUNDATION"
    # Configured label only, never verified authority; later modes are refused at startup.
    mode: Literal["RESEARCH", "BACKTEST", "PAPER"]
    policy: Literal["phase1.disabled.v1"] = "phase1.disabled.v1"
    execution_enabled: Literal[False] = False
    live_authority: Literal["LOCKED"] = "LOCKED"
    api: Literal["ALIVE"] = "ALIVE"
    database: Literal["READY", "NOT_READY"]
    source: Literal["UNKNOWN"] = "UNKNOWN"
    freshness: Freshness


class QualificationView(View):
    """Measured operational qualification only; UNKNOWN until an authorized projection."""

    phase2_days: Count | None = None
    phase4_days: Count | None = None
    task: Literal["UNKNOWN"] = "UNKNOWN"
    freshness: Freshness


class ReviewedStatement(View):
    """Static reviewed engineering wording. This terminal measures nothing about it."""

    operational: Literal["UNKNOWN"] = "UNKNOWN"
    provenance: Literal["REVIEWED_ENGINEERING"] = "REVIEWED_ENGINEERING"
    reason: Literal["REVIEWED_SUMMARY"] = "REVIEWED_SUMMARY"
    as_of: ReviewedDate = REVIEWED_AS_OF


class ReviewedPhase2(ReviewedStatement):
    status: Literal["OPERATIONAL_ACCEPTANCE_OPEN"] = "OPERATIONAL_ACCEPTANCE_OPEN"


class ReviewedPhase4Observation(ReviewedStatement):
    status: Literal["ENGINEERING_ACCEPTED_OPERATIONAL_ACCEPTANCE_OPEN"] = (
        "ENGINEERING_ACCEPTED_OPERATIONAL_ACCEPTANCE_OPEN"
    )


class ReviewedPhase5(ReviewedStatement):
    status: Literal["OFFLINE_ACCEPTED_COMMISSIONING_NOT_STARTED"] = (
        "OFFLINE_ACCEPTED_COMMISSIONING_NOT_STARTED"
    )


class ReviewedDs03(ReviewedStatement):
    status: Literal["ENGINEERING_ONLY_NO_ACCOUNT"] = "ENGINEERING_ONLY_NO_ACCOUNT"


class ReviewedGateway(ReviewedStatement):
    status: Literal["SYNTHETIC_OFFLINE_ONLY"] = "SYNTHETIC_OFFLINE_ONLY"


class ReviewedBrokerTransport(ReviewedStatement):
    status: Literal["NONE"] = "NONE"


class ReviewedPermitIssuer(ReviewedStatement):
    status: Literal["NONE"] = "NONE"


class ReviewedBinanceLiveDerivatives(ReviewedStatement):
    status: Literal["BLOCKED_BY_POLICY"] = "BLOCKED_BY_POLICY"


class ReviewedSummary(View):
    """Explicitly labelled static block; never operational data or a readiness claim."""

    scope: Literal["STATIC_REVIEWED_ENGINEERING_SUMMARY_NOT_MEASURED"] = (
        "STATIC_REVIEWED_ENGINEERING_SUMMARY_NOT_MEASURED"
    )
    phase2: ReviewedPhase2 = Field(default_factory=ReviewedPhase2)
    phase4_observation: ReviewedPhase4Observation = Field(default_factory=ReviewedPhase4Observation)
    phase5: ReviewedPhase5 = Field(default_factory=ReviewedPhase5)
    ds03: ReviewedDs03 = Field(default_factory=ReviewedDs03)
    gateway: ReviewedGateway = Field(default_factory=ReviewedGateway)
    broker_transport: ReviewedBrokerTransport = Field(default_factory=ReviewedBrokerTransport)
    permit_issuer: ReviewedPermitIssuer = Field(default_factory=ReviewedPermitIssuer)
    binance_live_derivatives: ReviewedBinanceLiveDerivatives = Field(
        default_factory=ReviewedBinanceLiveDerivatives
    )


class PositionView(View):
    position_hash: Digest
    instrument: Literal["BTCUSDT", "ETHUSDT", "UNCLASSIFIED"]
    quantity: Amount
    entry_price: Amount
    mark_price: Amount


class PendingView(View):
    intent_hash: Digest
    state: Literal["RESERVED", "SENT_PENDING", "ACKNOWLEDGED", "UNKNOWN", "PARTIALLY_FILLED"]


class ReservationView(View):
    intent_hash: Digest
    state: Literal["ACTIVE", "PARTIAL", "UNKNOWN", "RELEASED"]
    instrument: Literal["BTCUSDT", "ETHUSDT", "UNCLASSIFIED"]
    quantity: Amount
    notional: Amount
    modeled_loss: Amount


class PaperView(View):
    freshness: Freshness
    balance: Amount | None = None
    equity: Amount | None = None
    currency: Literal["USD", "UNCLASSIFIED"] | None = None
    kill: Literal["K0", "K1", "K2", "K3", "K4"] | None = None
    reconciled: bool | None = None
    unknown_orders: bool | None = None
    active_reservations: Count | None = None
    reservations: tuple[ReservationView, ...] = Field(default=(), max_length=100)
    positions: tuple[PositionView, ...] = Field(default=(), max_length=100)
    pending: tuple[PendingView, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def missing_is_not_empty_success(self) -> "PaperView":
        if self.freshness.state in ("UNKNOWN", "UNAVAILABLE") and (
            any(
                v is not None
                for v in (
                    self.balance,
                    self.equity,
                    self.currency,
                    self.kill,
                    self.reconciled,
                    self.unknown_orders,
                    self.active_reservations,
                )
            )
            or self.positions
            or self.pending
            or self.reservations
        ):
            raise ValueError("UNAVAILABLE_VALUES_MUST_BE_UNKNOWN")
        return self


class ResearchView(View):
    outcomes: tuple[
        Literal["INCONCLUSIVE"],
        Literal["INCONCLUSIVE"],
        Literal["INCONCLUSIVE"],
        Literal["INCONCLUSIVE"],
    ] = ("INCONCLUSIVE",) * 4
    oos: Literal["BOTH_CONSUMED_FOREVER"] = "BOTH_CONSUMED_FOREVER"
    candidate: Literal["NONE"] = "NONE"
    champion: Literal["NONE"] = "NONE"
    scope: Literal["REVIEWED_NONPRODUCTION_SUMMARY"] = "REVIEWED_NONPRODUCTION_SUMMARY"


class JournalEvent(View):
    sequence: Annotated[int, Field(ge=0, le=9007199254740991)]
    observed_at: datetime
    reason: JournalReason
    intent_hash: Digest | None = None
    evidence_hash: Digest

    @field_validator("observed_at")
    @classmethod
    def utc_only(cls, value: datetime) -> datetime:
        Freshness.utc_only(value)
        return value


class JournalView(View):
    freshness: Freshness
    events: tuple[JournalEvent, ...] = Field(default=(), max_length=100)


class TerminalSnapshot(View):
    contract_version: Literal["1"] = "1"
    system: SystemView
    qualification: QualificationView
    reviewed: ReviewedSummary = Field(default_factory=ReviewedSummary)
    paper: PaperView
    research: ResearchView
    journal: JournalView
