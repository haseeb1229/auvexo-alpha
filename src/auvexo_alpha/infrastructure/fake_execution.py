"""Deterministic local synthetic transport. No sockets, SDK, session or money path."""

from datetime import datetime
from enum import StrEnum
from uuid import NAMESPACE_URL, uuid5

from auvexo_alpha.application.gateway_ports import GatewayTruthPort, SyntheticTransportUnavailable
from auvexo_alpha.domain.gateway import AccountAttestation
from auvexo_alpha.domain.paper import PaperAuthorization, PaperIntent, PaperMarketSnapshot


class SyntheticScenario(StrEnum):
    ACKNOWLEDGE = "ACKNOWLEDGE"
    REJECT = "REJECT"
    TIMEOUT_BEFORE_SEND = "TIMEOUT_BEFORE_SEND"
    TIMEOUT_AFTER_SEND = "TIMEOUT_AFTER_SEND"
    CRASH_BEFORE_SEND = "CRASH_BEFORE_SEND"
    CRASH_AFTER_SEND = "CRASH_AFTER_SEND"


def synthetic_event_id(intent_hash: str, kind: str) -> str:
    return str(uuid5(NAMESPACE_URL, "auvexo.offline.noncounting.v1:" + intent_hash + ":" + kind))


class FakeExecutionTransport:
    """Fault fixture with durable PAPER truth; in-memory counters never decide retries."""

    def __init__(
        self,
        truth: GatewayTruthPort,
        identity: AccountAttestation,
        scenario: SyntheticScenario = SyntheticScenario.ACKNOWLEDGE,
    ) -> None:
        self.truth, self.scenario = truth, scenario
        self.identity = AccountAttestation.model_validate_json(identity.canonical_bytes())
        self.sent: list[str] = []
        self.queries: list[str] = []
        self.connected = True

    def attest(self, *, now: datetime) -> AccountAttestation:
        if not self.connected:
            raise SyntheticTransportUnavailable("SYNTHETIC_DISCONNECTED")
        return AccountAttestation.model_validate(self.identity.model_dump() | {"observed_at": now})

    def submit(
        self,
        intent: PaperIntent,
        authorization: PaperAuthorization,
        market: PaperMarketSnapshot,
        *,
        now: datetime,
    ) -> None:
        if (
            authorization.intent_hash != intent.content_hash()
            or authorization.account_ref != intent.account_ref
            or authorization.market_hash != market.content_hash()
        ):
            raise ValueError("SYNTHETIC_TRANSPORT_BINDING_DENIED")
        if not self.connected or self.scenario == SyntheticScenario.TIMEOUT_BEFORE_SEND:
            raise SyntheticTransportUnavailable("SYNTHETIC_UNAVAILABLE")
        if self.scenario == SyntheticScenario.CRASH_BEFORE_SEND:
            raise SystemExit("SYNTHETIC_PROCESS_CRASH")
        ih = intent.content_hash()
        # The accepted truth store independently verifies the committed writer fence
        # and exact persisted order quantity. No unclaimed order can be manufactured.
        self.truth.record_order(
            intent,
            writer_epoch=authorization.writer_epoch,
            quantity=authorization.exposure.quantity,
            now=now,
            event_id=synthetic_event_id(ih, "order"),
        )
        self.sent.append(ih)
        self.truth.mark(
            intent.account_ref, market, now=now, event_id=synthetic_event_id(ih, "mark")
        )
        if self.scenario == SyntheticScenario.CRASH_AFTER_SEND:
            raise SystemExit("SYNTHETIC_PROCESS_CRASH")
        if self.scenario == SyntheticScenario.TIMEOUT_AFTER_SEND:
            raise SyntheticTransportUnavailable("SYNTHETIC_RESPONSE_LOST")
        self.truth.status(
            ih,
            "REJECTED" if self.scenario == SyntheticScenario.REJECT else "ACKNOWLEDGED",
            account_ref=intent.account_ref,
            now=now,
            event_id=synthetic_event_id(ih, "response"),
        )

    def query(self, account_ref: str, *, now: datetime) -> None:
        if not self.connected:
            raise SyntheticTransportUnavailable("SYNTHETIC_DISCONNECTED")
        self.queries.append(account_ref)
