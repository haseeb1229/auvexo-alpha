# Offline gateway operations and trust boundaries

Scope: Phase5 OFFLINE/PRE-COMMISSIONING, synthetic ENGINEERING_ONLY. Actual commissioning
NOT STARTED. This is no Exness/account/DS03 evidence, no broker transport or money authority.
See [ADR024](../adr/024-parallel-operational-release-and-engineering.md) and
[frozen acceptance](OFFLINE_ACCEPTANCE.md). The active Phase4 runtime remains a separate
pinned release; development never changes its checkout/task/config/activation/date evidence.

## Startup and inspection process

The outer tool `python -m tools.offline_gateway` serves inherited anonymous stdin/stdout
pipes only. It opens no socket/listener/provider connection. The local parent generates
an ephemeral fake32-byte IPC key and sends bootstrap only over the inherited private pipe;
never argv, environment, logs, config or a broker credential store. The child returns a
fresh authenticated session identity. Every bounded canonical JSON frame is HMAC-bound to
that session, sequence and complete immutable gateway envelope. Expiry/hash/account/epoch/
release/config bindings are validated; duplicate IDs/sequence and prior-process frames
are refused. Bootstrap assumes the trusted parent exclusively owns inherited pipe handles;
this does not certify a future cross-user credential service or OS ACL implementation.

The child is inspection-only: hello, health, synthetic attestation/spec and reconciliation
snapshots. It never becomes an execution listener. Dispatch is explicitly UNSUPPORTED.
Its health remains RECONCILE_ONLY. Use tools from tests as synthetic harnesses, not daemon
registration or operational commissioning. No frontend/browser route can submit through it.

## Synthetic dispatch and durable recovery

OfflineExecutionCoordinator uses GatewayPaperPort and a fake-only transport. A thin
OfflinePaperAdapter delegates accepted authorization/risk/reservation/claim/reconciliation
and kill rules to PaperStore. OfflineTruthAdapter delegates authoritative simulated facts
to PaperTruth. The accepted PAPER_NONEXTERNAL authorization is never DEMO authority.
OfflineDemoPermit is inert contract/design validation: no issuer/signer or code path turns
its boolean validation into transport permission or bypasses deterministic risk.

For isolated synthetic tests: initialize accepted PAPER fixture, reattest account/spec,
acquire writer fence and explicitly audited owner resume only under accepted rules.
Authorize first; the accepted atomic store persists reservation/outbox and durable claim
SENT_PENDING/attempt before fake send. Duplicate delivery never blindly sends again.
Transport timeout preserves UNKNOWN capacity; unexpected failures propagate with durable
attempt retained. Reconnect/terminal-restart simulations default to query/reconcile only,
never automatic owner resume or blind resend. Broker-like facts remain authoritative.
No exactly-once external-delivery claim is made.

After crash before send, the committed attempt can still be ambiguous and is not blindly
retried. After acceptance before persistence, query/replay independently retained synthetic
facts before readiness. Partial fills and late deals retain residual reservations; a cancel
request does not manufacture finality. Cancel/fill races reconcile exact received facts.
Manual external synthetic positions or local/fact mismatches pause through accepted core
rules and require explicit investigation. Never patch account balances or delete journals.

Failed protection escalates K4. Kill/revocation suspends new dispatch under accepted guards;
credentials/connection health never reset it. Shutdown pauses new entries; preserve state
and reconcile on restart. If unsupported instrument/fill, stale writer, tampered risk/
reservation/permit or identity/account/server drift is found, refuse/pause. Stable safe error
codes only; no raw exceptions/secret-bearing input in process output.

## Qualification and future commissioning gates

All tests/fake facts/restore evidence are synthetic and NON_COUNTING; Phase5 sustained-demo
clock is zero and no Phase4 date can come from development. Actual commissioning still
requires full Phase4 review, account/spec/terms/source eligibility, secure credential service,
real IPC/security acceptance and separate explicit owner authorization. No MetaTrader5
package/import/terminal, Exness website/account/session, broker key, DS03 or broker order.
No live permit, withdrawal/transfer capability, DEMO/REAL execution or execution_enabled=true.

Protect Phase4 20:45-22:15 and Phase2 22:45-23:20 Pakistan from heavy development work.
Phase4 ACTIVE/full OPEN, Phase2 full operational OPEN/DS03 BLOCKED, Phase3 four INCONCLUSIVE
results and no candidate/champion. PUBLIC independent governance review due2026-10-24 is
unwaived; DS02 rights next review2026-11-16. Before broker SDK/session/credentials/DS03 or
proprietary alpha require PRIVATE return or accepted owner-approved permanent-public ADR.
No visibility/settings mutation is authorized. Same-disk synthetic recovery does not prove
encrypted off-device disaster recovery or broker realism.
