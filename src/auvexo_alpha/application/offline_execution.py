"""Offline orchestration delegates financial decisions and durable state to PAPER."""

from datetime import datetime
from typing import Literal

from auvexo_alpha.application.gateway_ports import (
    FakeExecutionPort,
    GatewayPaperPort,
    OfflineDispatchResult,
    SyntheticTransportUnavailable,
)
from auvexo_alpha.domain.contracts import Mode
from auvexo_alpha.domain.gateway import AccountAttestation, require_attestation
from auvexo_alpha.domain.paper import (
    PaperAuthorization,
    PaperInstrumentSpec,
    PaperIntent,
    PaperMarketSnapshot,
    PaperPolicy,
)
from auvexo_alpha.domain.paper_lifecycle import KillLevel, Release


class OfflineExecutionCoordinator:
    """Synchronous synthetic dispatch; a persisted claim is never blindly repeated."""

    def __init__(
        self,
        paper: GatewayPaperPort,
        transport: FakeExecutionPort,
        expected_attestation: AccountAttestation,
    ) -> None:
        self.paper, self.transport = paper, transport
        self.expected_attestation = AccountAttestation.model_validate_json(
            expected_attestation.canonical_bytes()
        )
        self._ready: tuple[str, int] | None = None

    def _require_ready(self, account_ref: str, epoch: int) -> None:
        if self._ready != (account_ref, epoch):
            raise ValueError("OFFLINE_RECONCILIATION_REQUIRED")

    def _attest(self, account_ref: str, *, now: datetime) -> bool:
        try:
            attestation = self.transport.attest(now=now)
        except SyntheticTransportUnavailable:
            return False
        try:
            require_attestation(attestation, self.expected_attestation, mode=Mode.PAPER, now=now)
        except ValueError:
            self.paper.set_kill(account_ref, KillLevel.K1, actor="offline.identity.drift", now=now)
            raise
        return True

    def authorize_and_submit(
        self,
        intent: PaperIntent,
        policy: PaperPolicy,
        market: PaperMarketSnapshot,
        spec: PaperInstrumentSpec,
        release: Release,
        *,
        epoch: int,
        now: datetime,
    ) -> OfflineDispatchResult:
        self._require_ready(intent.account_ref, epoch)
        submission = self.paper.authorize(intent, policy, market, spec, release, now=now)
        if submission.decision.status != "APPROVED":
            return OfflineDispatchResult(submission, "DENIED")
        if submission.authorization is None:
            raise ValueError("OFFLINE_APPROVAL_AUTHORIZATION_MISSING")
        outcome = self.dispatch(intent, submission.authorization, market, epoch=epoch, now=now)
        return OfflineDispatchResult(submission, outcome)

    def dispatch(
        self,
        intent: PaperIntent,
        authorization: PaperAuthorization,
        market: PaperMarketSnapshot,
        *,
        epoch: int,
        now: datetime,
    ) -> Literal["RECONCILED", "UNKNOWN"]:
        self._require_ready(intent.account_ref, epoch)
        self._ready = None
        if market.content_hash() != authorization.market_hash:
            raise ValueError("OFFLINE_MARKET_BINDING_DENIED")
        if not self._attest(intent.account_ref, now=now):
            return "UNKNOWN"
        # This accepted-store transaction commits SENT_PENDING and attempts=1 first.
        # Its immutable intent/auth/reservation/freshness/fence checks remain authoritative.
        claimed = self.paper.claim(
            intent.content_hash(),
            epoch,
            now=now,
            authorization=authorization,
        )
        try:
            self.transport.submit(intent, claimed, market, now=now)
        except SyntheticTransportUnavailable:
            self.paper.mark_unknown(intent.content_hash(), epoch, now=now)
            return "UNKNOWN"
        # Unexpected corruption/security/programmer failures propagate. The durable
        # attempted command still cannot be resent; restart recovers it as UNKNOWN.
        if self.paper.reconcile(intent.account_ref, now=now):
            self._ready = (intent.account_ref, epoch)
            return "RECONCILED"
        return "UNKNOWN"

    def reconnect(self, account_ref: str, *, epoch: int, now: datetime) -> bool:
        """Replay/query-only recovery, including a restart with no in-memory send list."""
        self._ready = None
        if account_ref != self.expected_attestation.account_ref:
            raise ValueError("OFFLINE_ACCOUNT_BINDING_DENIED")
        if not self._attest(account_ref, now=now):
            return False
        for pending in self.paper.pending(account_ref):
            if pending.state != "RESERVED":
                self.paper.mark_unknown(pending.intent_hash, epoch, now=now)
        try:
            self.transport.query(account_ref, now=now)
        except SyntheticTransportUnavailable:
            return False
        if self.paper.reconcile(account_ref, now=now):
            self._ready = (account_ref, epoch)
            return True
        return False

    def failed_protection(self, account_ref: str, *, now: datetime) -> None:
        self._ready = None
        self.paper.set_kill(account_ref, KillLevel.K4, actor="offline.protection.failed", now=now)

    def shutdown(self, account_ref: str, *, now: datetime) -> None:
        self._ready = None
        self.paper.set_kill(account_ref, KillLevel.K1, actor="offline.shutdown", now=now)
