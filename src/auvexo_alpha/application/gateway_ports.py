"""Narrow synthetic execution ports; accepted PAPER contracts retain all authority."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from auvexo_alpha.application.observation_ports import PaperSubmission
from auvexo_alpha.domain.gateway import (
    AccountAttestation,
    BrokerDealFact,
    BrokerOrderFact,
    BrokerPositionFact,
    GatewayAccountSnapshot,
    GatewayAck,
    GatewayDispatch,
    GatewayHealth,
    GatewayHello,
    GatewayInstrumentSnapshot,
    GatewaySnapshot,
)
from auvexo_alpha.domain.paper import (
    PaperAuthorization,
    PaperInstrumentSpec,
    PaperIntent,
    PaperMarketSnapshot,
    PaperPolicy,
    PaperPosition,
)
from auvexo_alpha.domain.paper_lifecycle import KillLevel, Release


class SyntheticTransportUnavailable(Exception):
    """Expected synthetic delivery ambiguity; never permission to retry a command."""


@dataclass(frozen=True)
class PendingOfflineAttempt:
    intent_hash: str
    state: str


@dataclass(frozen=True)
class OfflineDispatchResult:
    submission: PaperSubmission
    outcome: Literal["DENIED", "RECONCILED", "UNKNOWN"]


class GatewayPaperPort(Protocol):
    def authorize(
        self,
        intent: PaperIntent,
        policy: PaperPolicy,
        market: PaperMarketSnapshot,
        spec: PaperInstrumentSpec,
        release: Release,
        *,
        now: datetime,
    ) -> PaperSubmission: ...

    def claim(
        self,
        intent_hash: str,
        epoch: int,
        *,
        now: datetime,
        authorization: PaperAuthorization,
    ) -> PaperAuthorization: ...

    def mark_unknown(self, intent_hash: str, epoch: int, *, now: datetime) -> None: ...

    def reconcile(self, account_ref: str, *, now: datetime) -> bool: ...

    def pending(self, account_ref: str) -> tuple[PendingOfflineAttempt, ...]: ...

    def set_kill(
        self,
        account_ref: str,
        level: KillLevel,
        *,
        actor: str,
        now: datetime,
    ) -> None: ...


class GatewayTruthPort(Protocol):
    def record_order(
        self,
        intent: PaperIntent,
        *,
        now: datetime,
        writer_epoch: int,
        quantity: Decimal,
        event_id: str,
    ) -> str: ...

    def mark(
        self,
        account_ref: str,
        market: PaperMarketSnapshot,
        *,
        now: datetime,
        event_id: str,
    ) -> str: ...

    def status(
        self,
        intent_hash: str,
        status: str,
        *,
        account_ref: str,
        now: datetime,
        event_id: str,
    ) -> str: ...

    def fill(
        self,
        intent_hash: str,
        quantity: Decimal,
        price: Decimal,
        *,
        account_ref: str,
        now: datetime,
        event_id: str,
    ) -> str: ...

    def resolve(
        self,
        intent_hash: str,
        status: str,
        confirmed_filled_quantity: Decimal,
        *,
        account_ref: str,
        now: datetime,
        evidence_hash: str,
        event_id: str,
    ) -> str: ...

    def external_position(
        self,
        account_ref: str,
        position: PaperPosition,
        *,
        now: datetime,
        event_id: str,
    ) -> str: ...


class FakeExecutionPort(Protocol):
    """Fake-only effect boundary, never a broker or a mode activation capability."""

    def attest(self, *, now: datetime) -> AccountAttestation: ...

    def submit(
        self,
        intent: PaperIntent,
        authorization: PaperAuthorization,
        market: PaperMarketSnapshot,
        *,
        now: datetime,
    ) -> None: ...

    def query(self, account_ref: str, *, now: datetime) -> None: ...


class FutureExecutionTransport(Protocol):
    """Inert future interface shape; no implementation, credential or activation path.

    A cancel must identify an observed order and carry its own fully bound persisted
    authorization/reservation. Merely knowing an order reference is no authority.
    """

    def connect(self) -> GatewayHello: ...

    def attest(self) -> AccountAttestation: ...

    def account_snapshot(self, account_ref: str) -> GatewayAccountSnapshot: ...

    def instrument_snapshot(self, instrument_id: str) -> GatewayInstrumentSnapshot: ...

    def submit(self, command: GatewayDispatch) -> GatewayAck: ...

    def cancel(self, order: BrokerOrderFact, command: GatewayDispatch) -> GatewayAck: ...

    def query_orders(self, account_ref: str) -> tuple[BrokerOrderFact, ...]: ...

    def query_deals(self, account_ref: str) -> tuple[BrokerDealFact, ...]: ...

    def query_positions(self, account_ref: str) -> tuple[BrokerPositionFact, ...]: ...

    def history(self, account_ref: str, *, after_cursor: int) -> GatewaySnapshot: ...

    def health(self) -> GatewayHealth: ...

    def reconnect(self, account_ref: str, *, after_cursor: int) -> GatewaySnapshot: ...
