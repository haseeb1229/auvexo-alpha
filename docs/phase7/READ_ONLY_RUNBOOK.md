# Read-only operator terminal runbook

Status: FROZEN before executable implementation, 2026-10-20. Engineering-only; no operational
acceptance is claimed. Follow [ADR025](../adr/025-read-only-private-operator-terminal.md),
[acceptance](READ_ONLY_ACCEPTANCE.md) and the owner [shell clarification](../reference/PHASE_7_STATIC_SHELL_CLARIFICATION.txt).

## Intended startup

Use only the separate development clone. Verify build/config and loopback bind, accepted read
projection identity/permissions and diagnostics token readiness. Never read a broker credential,
retarget the observation runner or attach development tests/UI to its persistent campaign DB.
Build from committed npm lock on pinned Node24.20.0. No token in build/config, URL or browser
storage. The owner enters diagnostics bearer at runtime; token and read snapshots remain in memory.
Only the data-free local shell and allowlisted build assets load without bearer. Every /api/v1
endpoint is protected. Run npm ci then npm run build in web/operator-terminal before the existing
auvexo serve command; FastAPI serves that build same-origin. Vite development is opt-in, fixed
127.0.0.1:5173, with exact dev-origin allowed by explicit create_app configuration only.

## Inspecting truth

Command Center distinguishes API alive, database readiness, operational evidence freshness and
execution authority. A software PASS or mode label does not permit trading. Risk/PAPER renders
only the safe virtual projection; unknown/unconfigured/missing state displays UNKNOWN/UNAVAILABLE,
never zero equity or no positions as a fabricated success. Positions/reservations/UNKNOWN orders,
kill/reconciliation show their source timestamp and provenance. The view never recomputes risk.
Qualification presents engineering acceptance separately from full operational OPEN and unknown
or verified genuine counts. No UI fixture contributes a date. Research shows four reviewed
INCONCLUSIVE outcomes, both OOS consumed, no candidate/champion or profitability promise.
Journal is bounded safe reason/hash/time metadata, no raw payload/download/file selector.
System Health distinguishes diagnostics, read adapter/source status, unconnected task status and
the accepted synthetic/offline gateway; it does not claim actual broker health.

## Disconnect, stale and unavailable

On fetch/DB failure show safe UNAVAILABLE code without SQL/DSN/driver details. Retained snapshots
must be visibly STALE with their original observed timestamp. Never update their as-of time or
replace error with empty-success data. On unauthorized response clear token and all snapshots,
return to sign-in, and do not retry with persisted credentials. No background storage, worker,
analytics or external font/CDN. Reconnect reads fresh snapshots; it never sends a command.

## Shutdown and recovery

Sign out clears memory. Stop only the owned local terminal/API processes; no scheduled task,
operational DB or campaign control. Browser/client rollback changes presentation only, never
journals/ledger/account/policy/activation. No schema/durable state is proposed; restore proof
applies only if implementation later introduces durable state, which needs separate review.

## Protected gates

Phase4 runtime remains9b9038b, observation ACTIVE/full OPEN; first dateOctober21 21:00Pakistan,
>=14dates AND span>=14calendar days/replay/mismatch gates. Phase2 seven genuine dates remain
required;23:00-23:12window/22:57warmup unchanged, no late catch-up. Avoid heavy work20:45-22:15
on/afterOctober21 and22:45-23:20everyday. Stop at safe checkpoint PROTECTED_WINDOW_PENDING
before a long operation that cannot finish before tonight's22:45 window.
PUBLIC source exception dueOctober24 remains active pending selected PRIVATE return; no setting
changes. DS02 rights reviewNovember16; DS03 BLOCKED. No broker SDK/session/credentials/orders,
operational permits, sustained-demo clock, candidate/champion, LIVE or money authority.

## Required release evidence

Full Python/isolated PG/frontend/a11y/security/contract/statics/docs/scans/audits plus exact-final
fresh Windows clone, clean frontend lock/build, exact-head hosted push/PR jobs/logs. Keep single
Phase7 PR OPEN/UNMERGED for independent review. Frozen design certifies none of those future checks.
