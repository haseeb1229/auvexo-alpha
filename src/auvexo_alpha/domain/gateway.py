"""Strict synthetic gateway contracts; never operational execution authority."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from auvexo_alpha.domain.contracts import (
    Contract,
    Currency,
    Digest,
    Identifier,
    InstrumentSpec,
    Label,
    Mode,
    MoneyAction,
    NonnegativeAmount,
    PositiveAmount,
    Product,
    UTCTime,
    Venue,
    exact_decimal,
    utc_time,
)
from auvexo_alpha.domain.paper import (
    PaperAuthorization,
    PaperIntent,
    PaperReservation,
    SignedAmount,
)

MAX_MESSAGE_BYTES = 65536
Epoch = Annotated[int, Field(ge=0, le=2147483647)]


class GatewayHello(Contract):
    kind: Literal["hello"] = "hello"
    gateway_id: Label
    session_id: Identifier


class GatewayHealth(Contract):
    kind: Literal["health"] = "health"
    status: Literal["RECONCILE_ONLY", "READY", "DISCONNECTED"]
    observed_at: UTCTime


class AccountAttestation(Contract):
    kind: Literal["attestation"] = "attestation"
    account_ref: Label
    venue: Venue
    server: Label
    account_identifier: Label
    account_kind: Literal["DEMO", "REAL"]
    currency: Currency
    account_mode: Literal["HEDGING", "NETTING"]
    observed_at: UTCTime
    capability_hash: Digest

    @model_validator(mode="after")
    def synthetic_identity(self) -> Self:
        if not self.account_identifier.startswith("synthetic.") or not self.server.startswith(
            "synthetic."
        ):
            raise ValueError("SYNTHETIC_IDENTITY_REQUIRED")
        if not self.account_ref.startswith(("synthetic.", "paper.")):
            raise ValueError("SYNTHETIC_ACCOUNT_REQUIRED")
        return self


def require_attestation(
    actual: AccountAttestation,
    expected: AccountAttestation,
    *,
    mode: Mode,
    now: datetime,
    max_age_seconds: int = 30,
) -> None:
    """Compare independently pinned identity, never infer authority from credentials."""
    actual = AccountAttestation.model_validate_json(actual.canonical_bytes())
    expected = AccountAttestation.model_validate_json(expected.canonical_bytes())
    now = utc_time(now)
    if (
        mode not in (Mode.PAPER, Mode.DEMO)
        or actual.account_kind != "DEMO"
        or expected.account_kind != "DEMO"
    ):
        raise ValueError("ACCOUNT_MODE_DENIED")
    if max_age_seconds < 0 or not timedelta(0) <= now - actual.observed_at <= timedelta(
        seconds=max_age_seconds
    ):
        raise ValueError("ACCOUNT_ATTESTATION_STALE")
    fields = (
        "account_ref",
        "venue",
        "server",
        "account_identifier",
        "account_kind",
        "currency",
        "account_mode",
        "capability_hash",
    )
    if any(getattr(actual, field) != getattr(expected, field) for field in fields):
        raise ValueError("ACCOUNT_ATTESTATION_DRIFT")


class GatewayAccountSnapshot(Contract):
    """Synthetic observed account facts, never permission to spend a balance."""

    kind: Literal["account"] = "account"
    account_ref: Label
    currency: Currency
    balance: SignedAmount
    equity: SignedAmount
    free_margin: SignedAmount
    observed_at: UTCTime

    @model_validator(mode="after")
    def synthetic_account(self) -> Self:
        if not self.account_ref.startswith(("synthetic.", "paper.")):
            raise ValueError("SYNTHETIC_ACCOUNT_REQUIRED")
        return self


class GatewayInstrumentSnapshot(Contract):
    kind: Literal["instrument"] = "instrument"
    spec: InstrumentSpec
    supported_fill: tuple[Literal["IOC", "FOK", "GTC"], ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def unique_fill(self) -> Self:
        if len(set(self.supported_fill)) != len(self.supported_fill):
            raise ValueError("DUPLICATE_FILL_MODE")
        return self


class GatewayDispatch(Contract):
    kind: Literal["dispatch"] = "dispatch"
    intent: PaperIntent
    authorization: PaperAuthorization
    reservation: PaperReservation

    @model_validator(mode="after")
    def paper_bindings(self) -> Self:
        i, a, r = self.intent, self.authorization, self.reservation
        if (
            i.mode != Mode.PAPER
            or not i.account_ref.startswith("paper.")
            or i.action not in (MoneyAction.OPEN, MoneyAction.CLOSE, MoneyAction.CANCEL)
            or a.semantics != "PAPER_NONEXTERNAL"
            or a.account_ref != i.account_ref
            or r.account_ref != i.account_ref
            or a.intent_hash != i.content_hash()
            or r.intent_hash != i.content_hash()
            or a.reservation_id != r.reservation_id
            or r.intent_id != i.intent_id
            or r.logical_key != i.logical_key
            or r.action != i.action
            or r.instrument_id != i.instrument_id
            or r.position_ref != i.position_ref
            or r.target_intent_ref != i.target_intent_ref
            or r.state != "ACTIVE"
            or a.release_hash != i.release_hash
            or a.policy_hash != i.policy_hash
            or a.spec_hash != i.spec_hash
            or a.market_hash != i.snapshot_hash
            or a.account_snapshot_hash != i.account_snapshot_hash
            or r.created_at != a.issued_at
            or r.expires_at != i.expires_at
            or r.quantity != a.exposure.quantity
            or r.notional != a.exposure.notional
            or r.modeled_loss != a.exposure.modeled_loss
            or r.margin != a.exposure.margin_required
            or not i.created_at <= a.issued_at < a.expires_at <= i.expires_at
        ):
            raise ValueError("SYNTHETIC_DISPATCH_BINDING_DENIED")
        return self


class GatewayAck(Contract):
    kind: Literal["ack"] = "ack"
    status: Literal["ACCEPTED", "REJECTED", "UNKNOWN"]
    attempt_id: Identifier


class BrokerOrderFact(Contract):
    fact_kind: Literal["order"] = "order"
    order_ref: Label
    intent_hash: Digest
    quantity: PositiveAmount
    status: Literal[
        "ACKNOWLEDGED", "REJECTED", "UNKNOWN", "PARTIALLY_FILLED", "FILLED", "CANCELED", "EXPIRED"
    ]
    observed_at: UTCTime


class BrokerDealFact(Contract):
    fact_kind: Literal["deal"] = "deal"
    deal_ref: Label
    order_ref: Label
    intent_hash: Digest
    quantity: PositiveAmount
    price: PositiveAmount
    fees: NonnegativeAmount
    observed_at: UTCTime


class BrokerPositionFact(Contract):
    fact_kind: Literal["position"] = "position"
    position_ref: Label
    instrument_id: Label
    quantity: NonnegativeAmount
    side: Literal["BUY", "SELL"]
    observed_at: UTCTime


BrokerFact = Annotated[
    BrokerOrderFact | BrokerDealFact | BrokerPositionFact, Field(discriminator="fact_kind")
]


class GatewayFact(Contract):
    kind: Literal["fact"] = "fact"
    fact: BrokerFact


class GatewayReconcile(Contract):
    kind: Literal["reconcile"] = "reconcile"
    cursor: Epoch = 0


class GatewaySnapshot(Contract):
    kind: Literal["snapshot"] = "snapshot"
    cursor: Epoch = 0
    orders: tuple[BrokerOrderFact, ...] = Field(default=(), max_length=64)
    deals: tuple[BrokerDealFact, ...] = Field(default=(), max_length=64)
    positions: tuple[BrokerPositionFact, ...] = Field(default=(), max_length=64)


class GatewayError(Contract):
    kind: Literal["error"] = "error"
    code: Literal[
        "INVALID_MESSAGE",
        "UNAUTHORIZED",
        "EXPIRED",
        "REPLAY",
        "BINDING_DENIED",
        "RECONCILE_REQUIRED",
        "UNSUPPORTED",
        "UNAVAILABLE",
    ]
    retryable: bool = False


GatewayPayload = Annotated[
    GatewayHello
    | GatewayAccountSnapshot
    | GatewayHealth
    | AccountAttestation
    | GatewayInstrumentSnapshot
    | GatewayDispatch
    | GatewayAck
    | GatewayFact
    | GatewayReconcile
    | GatewaySnapshot
    | GatewayError,
    Field(discriminator="kind"),
]


class GatewayMessage(Contract):
    command_id: Identifier
    correlation_id: Identifier
    causation_id: Identifier | None = None
    source_id: Label
    account_ref: Label
    mode: Mode
    writer_epoch: Epoch
    intent_hash: Digest
    authorization_hash: Digest
    reservation_hash: Digest
    release_hash: Digest
    config_hash: Digest
    created_at: UTCTime
    expires_at: UTCTime
    payload_hash: Digest
    payload: GatewayPayload

    @model_validator(mode="after")
    def envelope_bindings(self) -> Self:
        if self.mode not in (Mode.PAPER, Mode.DEMO) or not self.account_ref.startswith(
            ("synthetic.", "paper.")
        ):
            raise ValueError("OFFLINE_MODE_OR_ACCOUNT_DENIED")
        if self.expires_at <= self.created_at or self.expires_at - self.created_at > timedelta(
            minutes=5
        ):
            raise ValueError("GATEWAY_EXPIRY_INVALID")
        if self.payload_hash != self.payload.content_hash():
            raise ValueError("GATEWAY_PAYLOAD_HASH_MISMATCH")
        if (
            isinstance(self.payload, (AccountAttestation, GatewayAccountSnapshot))
            and self.payload.account_ref != self.account_ref
        ):
            raise ValueError("GATEWAY_ATTESTATION_ACCOUNT_MISMATCH")
        if isinstance(self.payload, GatewayDispatch):
            p = self.payload
            if (
                self.mode != Mode.PAPER
                or self.account_ref != p.intent.account_ref
                or self.writer_epoch != p.authorization.writer_epoch
                or self.intent_hash != p.intent.content_hash()
                or self.authorization_hash != p.authorization.content_hash()
                or self.reservation_hash != p.reservation.content_hash()
                or self.release_hash != p.intent.release_hash
                or not p.authorization.issued_at
                <= self.created_at
                < self.expires_at
                <= p.authorization.expires_at
            ):
                raise ValueError("GATEWAY_DISPATCH_ENVELOPE_MISMATCH")
        return self

    def require_current(self, now: datetime) -> None:
        now = utc_time(now)
        if not self.created_at <= now < self.expires_at:
            raise ValueError("GATEWAY_COMMAND_EXPIRED")


def build_message(
    payload: GatewayPayload,
    *,
    command_id: UUID,
    correlation_id: UUID,
    source_id: str,
    account_ref: str,
    mode: Mode,
    writer_epoch: int,
    intent_hash: str,
    authorization_hash: str,
    reservation_hash: str,
    release_hash: str,
    config_hash: str,
    created_at: datetime,
    expires_at: datetime,
    causation_id: UUID | None = None,
) -> GatewayMessage:
    return GatewayMessage(
        command_id=command_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        source_id=source_id,
        account_ref=account_ref,
        mode=mode,
        writer_epoch=writer_epoch,
        intent_hash=intent_hash,
        authorization_hash=authorization_hash,
        reservation_hash=reservation_hash,
        release_hash=release_hash,
        config_hash=config_hash,
        created_at=created_at,
        expires_at=expires_at,
        payload_hash=payload.content_hash(),
        payload=payload,
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("GATEWAY_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError("GATEWAY_NONFINITE_JSON")


def decode_message(raw: bytes) -> GatewayMessage:
    """Bound before parsing, reject ambiguous JSON, then strict contract validation."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_MESSAGE_BYTES:
        raise ValueError("GATEWAY_MESSAGE_SIZE")
    try:
        json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
        return GatewayMessage.model_validate_json(raw)
    except (RecursionError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("GATEWAY_INVALID_JSON") from error


class OfflineDemoPermit(Contract):
    """Inert reviewed design metadata. No issuer, signature or operational capability."""

    semantics: Literal["OFFLINE_SYNTHETIC_DESIGN_ONLY"] = "OFFLINE_SYNTHETIC_DESIGN_ONLY"
    permit_id: Identifier
    account_ref: Label
    server: Label
    mode: Literal[Mode.DEMO] = Mode.DEMO
    venue: Venue
    product: Product
    instruments: tuple[Label, ...] = Field(min_length=1, max_length=16)
    release_hash: Digest
    config_hash: Digest
    max_notional: PositiveAmount
    max_modeled_loss: PositiveAmount
    valid_from: UTCTime
    valid_until: UTCTime
    revocation_epoch: Epoch
    allowed_commands: tuple[Literal["SUBMIT", "CANCEL", "RECONCILE"], ...] = Field(
        min_length=1, max_length=3
    )

    @model_validator(mode="after")
    def inert_scope(self) -> Self:
        if (
            not self.account_ref.startswith("synthetic.")
            or not self.server.startswith("synthetic.")
            or self.valid_until <= self.valid_from
            or len(set(self.instruments)) != len(self.instruments)
            or len(set(self.allowed_commands)) != len(self.allowed_commands)
            or self.venue == Venue.BINANCE
            and self.product != Product.SPOT
            or self.venue == Venue.EXNESS
            and self.product != Product.CFD
        ):
            raise ValueError("OFFLINE_PERMIT_SCOPE_DENIED")
        return self


def validate_offline_permit(
    permit: OfflineDemoPermit | None,
    *,
    account: AccountAttestation,
    mode: Mode,
    instrument_id: str,
    venue: Venue,
    product: Product,
    release_hash: str,
    config_hash: str,
    notional: NonnegativeAmount,
    modeled_loss: NonnegativeAmount,
    command: str,
    now: datetime,
    revocation_epoch: int,
    expected_hash: str,
) -> bool:
    """Check inert design bounds only; result cannot authorize any transport or risk bypass."""
    if permit is None:
        return False
    try:
        permit = OfflineDemoPermit.model_validate_json(permit.canonical_bytes())
        account = AccountAttestation.model_validate_json(account.canonical_bytes())
        now = utc_time(now)
        require_attestation(account, account, mode=Mode.DEMO, now=now)
        notional, modeled_loss = exact_decimal(notional), exact_decimal(modeled_loss)
        return (
            mode == Mode.DEMO
            and account.account_kind == "DEMO"
            and permit.content_hash() == expected_hash
            and permit.account_ref == account.account_ref
            and permit.server == account.server
            and account.venue == venue == permit.venue
            and product == permit.product
            and instrument_id in permit.instruments
            and release_hash == permit.release_hash
            and config_hash == permit.config_hash
            and permit.valid_from <= now < permit.valid_until
            and permit.revocation_epoch == revocation_epoch
            and command in permit.allowed_commands
            and 0 <= notional <= permit.max_notional
            and 0 <= modeled_loss <= permit.max_modeled_loss
        )
    except (ValueError, TypeError):
        return False
