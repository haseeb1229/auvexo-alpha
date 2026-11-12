"""Offline orchestration delegates financial decisions and durable state to PAPER."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from auvexo_alpha.application.gateway_ports import (
    FakeExecutionPort,
    GatewayPaperPort,
    SyntheticTransportUnavailable,
)
from auvexo_alpha.application.observation_ports import PaperSubmission
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

# NOT_ATTEMPTED: nothing was claimed or sent; the reservation is still RESERVED with zero
# attempts. UNKNOWN: a durable attempt exists and its result is ambiguous. Neither one is
# ever permission to send: a later dispatch still passes every store guard exactly once.
DispatchOutcome = Literal["RECONCILED", "UNKNOWN", "NOT_ATTEMPTED"]


@dataclass(frozen=True)
class OfflineSubmissionResult:
    submission: PaperSubmission
    outcome: Literal["DENIED", "RECONCILED", "UNKNOWN", "NOT_ATTEMPTED"]


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

    def _pause(self, account_ref: str, *, actor: str, now: datetime) -> None:
        """Journal `actor` at K1, or at the account's own level when that is higher.

        This port has no kill read. The store compares under its account lock instead: a
        request below the current level is refused with EXPLICIT_OWNER_RESUME_REQUIRED
        and changes nothing, so the next level is requested. The first accepted request
        is exactly max(current, K1). Nothing here can lower, clear or resume a kill.
        """
        for level in (KillLevel.K1, KillLevel.K2, KillLevel.K3):
            try:
                self.paper.set_kill(account_ref, level, actor=actor, now=now)
                return
            except ValueError as error:
                if str(error) != "EXPLICIT_OWNER_RESUME_REQUIRED":
                    raise
        self.paper.set_kill(account_ref, KillLevel.K4, actor=actor, now=now)

    def _attest(self, account_ref: str, *, now: datetime) -> bool:
        try:
            attestation = self.transport.attest(now=now)
        except SyntheticTransportUnavailable:
            return False
        try:
            require_attestation(attestation, self.expected_attestation, mode=Mode.PAPER, now=now)
        except ValueError:
            # Drift is journaled at every kill level, then the drift itself is re-raised.
            self._pause(account_ref, actor="offline.identity.drift", now=now)
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
    ) -> OfflineSubmissionResult:
        self._require_ready(intent.account_ref, epoch)
        submission = self.paper.authorize(intent, policy, market, spec, release, now=now)
        if submission.decision.status != "APPROVED":
            return OfflineSubmissionResult(submission, "DENIED")
        if submission.authorization is None:
            raise ValueError("OFFLINE_APPROVAL_AUTHORIZATION_MISSING")
        outcome = self.dispatch(intent, submission.authorization, market, epoch=epoch, now=now)
        return OfflineSubmissionResult(submission, outcome)

    def dispatch(
        self,
        intent: PaperIntent,
        authorization: PaperAuthorization,
        market: PaperMarketSnapshot,
        *,
        epoch: int,
        now: datetime,
    ) -> DispatchOutcome:
        self._require_ready(intent.account_ref, epoch)
        self._ready = None
        if market.content_hash() != authorization.market_hash:
            raise ValueError("OFFLINE_MARKET_BINDING_DENIED")
        if not self._attest(intent.account_ref, now=now):
            # Attestation was unavailable before any claim, so no attempt exists.
            return "NOT_ATTEMPTED"
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

    def _mark_unknown(
        self, account_ref: str, states: tuple[str, ...], *, epoch: int, now: datetime
    ) -> None:
        for pending in self.paper.pending(account_ref):
            if pending.state in states:
                self.paper.mark_unknown(pending.intent_hash, epoch, now=now)

    def reconnect(self, account_ref: str, *, epoch: int, now: datetime) -> bool:
        """Replay/query-only recovery, including a restart with no in-memory send list."""
        self._ready = None
        if account_ref != self.expected_attestation.account_ref:
            raise ValueError("OFFLINE_ACCOUNT_BINDING_DENIED")
        if not self._attest(account_ref, now=now):
            return False
        # Only an attempt without an observed result is ambiguous before the query.
        self._mark_unknown(account_ref, ("SENT_PENDING", "UNKNOWN"), epoch=epoch, now=now)
        acknowledged = ("ACKNOWLEDGED", "PARTIALLY_FILLED")
        try:
            self.transport.query(account_ref, now=now)
        except SyntheticTransportUnavailable:
            self._mark_unknown(account_ref, acknowledged, epoch=epoch, now=now)
            return False
        if self.paper.reconcile(account_ref, now=now):
            self._ready = (account_ref, epoch)
            return True
        # Truth did not reconcile: orders still merely acknowledged hold worst-case
        # capacity as UNKNOWN. No fill is assumed and nothing is sent again.
        self._mark_unknown(account_ref, acknowledged, epoch=epoch, now=now)
        return False

    def failed_protection(self, account_ref: str, *, now: datetime) -> None:
        self._ready = None
        self.paper.set_kill(account_ref, KillLevel.K4, actor="offline.protection.failed", now=now)

    def shutdown(self, account_ref: str, *, now: datetime) -> None:
        self._ready = None
        self._pause(account_ref, actor="offline.shutdown", now=now)
