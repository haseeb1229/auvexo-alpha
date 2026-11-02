# ADR-028: DS-03 synthetic read-only connector foundation

Date: 2026-11-02.
Status: FROZEN BEFORE IMPLEMENTATION / ENGINEERING_ONLY; executable acceptance pending.
Requirements: R-021, R-022, R-029; ER-01 through ER-15; D3-01 through D3-16.
Authority: latest owner macro after verified PR #10 normal merge at
f47770d7886d12240e24390e23f939cb49535a31.

## Context

Phase 2 full operational acceptance remains OPEN. Actual DS-03 account/source/spec/history/
rights qualification remains unavailable. ADR-027 permits temporary-public sanitized
engineering; actual broker account/session/credentials require PRIVATE return and a
separately accepted onboarding step. The [provider review](../phase2/DS03_PROVIDER_REVIEW.md)
found no material contract contradiction. The official Python SDK exposes trades and is
not itself a read-only security boundary.

## Decision

Build a dedicated synthetic-only local connector process, strict immutable versioned
contracts, application attestation and fake terminal. No SDK dependency/import, terminal
launch, broker networking, real account input or actual session. Domain owns DTOs;
application imports only domain/application contracts and stdlib; infrastructure owns
process/IPC/fake/native-secret effects. Keep existing execution/PAPER ports unchanged.

Use a distinct read-only port: attest()->Ds03Attestation,
execute(request:Ds03Request)->Ds03Reply, disconnect()->None. Ds03Reader.read(request,now)
requires fresh pre/post-read attestation and validates immutable reply lineage.
Ds03Request is a discriminated strict union: ATTEST, SYMBOLS, SPEC, TICK, BARS, TICKS,
ORDERS, POSITIONS, DEALS, ORDER_HISTORY, DISCONNECT. Bootstrap fixes identity/backend;
requests cannot select account, server, profile, executable, module, filesystem or shell.
No reflection or SDK object crosses the interface. Unrecognized/trade operations fail
before backend access; order_send, order_check execution, modify/cancel are forbidden.

Limits: 65,536-byte frames, one pending request, 256 requests/session, 128 symbols,
256 records/request, 10-second monotonic deadline, attestation age <=30 seconds. Bind
request UUID, exact release/config hashes, UTC creation/expiry, bounded history ranges,
response correlation, HMAC direction/session/sequence and a fresh ephemeral pipe key.
Use fixed isolated current-interpreter package launch and fixed synthetic backend,
inherited anonymous pipes only, sanitized environment, no listener or caller launch knobs.
Crash/timeout/auth/malformed/replay/mismatch closes the session; recovery requires fresh
bootstrap/identity. No silent retry/account substitution or partial-output acceptance.

Expected identity binds DEMO, redacted login digest, exact synthetic assigned server,
account type/currency/leverage, terminal version/build/profile/process, release/config/
rights and read-only credential provenance plus observable disabled trading. REAL,
CONTEST, UNKNOWN, absent evidence and any pre/post swap fail closed. trade_allowed=False
alone is insufficient proof of investor credential provenance. No inference from filenames.

Discover exact symbols including suffixes; retain all available contract/spec semantics
and explicit unknown sessions/history facts. Immutable source envelopes retain provider,
first-seen, received, processed, available timestamps, account/server/mode/spec/connector/
release/config/rights binding, raw and normalized hashes, history coverage and gaps.
No future leakage, refreshed first-seen, fabricated coverage, accepted time regression or
spec drift. Expired/unknown rights refuse. Untrusted clock labels
STRUCTURAL_ONLY_CLOCK_BLOCKED; no time-quality/source/Phase 5 qualification.

Provide fixed-purpose CurrentUser DPAPI read-only-password code: fixed DS-03 namespace/
purpose/location, restrictive owner ACL, atomic create/rotate/delete, bounded encrypted
purpose-bound envelope and redacted errors. Current Exness syntax: 8–15 ASCII characters,
upper/lower English letters, digits and special character. No OI 32–128 rule reuse.
No environment/CLI/plaintext/log/general-vault API. Production entrypoints remain inert
until later accepted actual onboarding; PUBLIC native tests use only synthetic passwords
in disposable UUID test leaves. No real secret or existing OI slot is touched.

Reuse native mechanics through a minimal protected _DPAPI._purpose() method returning
unchanged OI slot purpose, overridden only by the fixed DS-03 adapter; a fixed DS-03 files
adapter reuses native handle/ACL/atomic mechanics. No arbitrary purpose/path constructor.
Preserve OI slot enum, purposes/envelopes/paths/errors/platform guards and collector import
boundary; rerun inherited proofs without weakening tests. This change belongs to the
new independently reviewed DS-03 executable scope, not retrospective PR #10 acceptance.

SDK NOT ADOPTED, INSTALLED OR IMPORTED. Candidate wheel hash/license/metadata inspection
is evidence only; later adoption needs current dependency/binary/notice audit, real
terminal compatibility proof and accepted private onboarding. No dependency/lock change.

## Alternatives

Execution ports expose unnecessary capabilities. Importing the full SDK during public
synthetic work risks terminal effects. Duplicating native storage creates divergent
security paths; a general vault/plugin/execution API exceeds this fixed-purpose scope.

## Consequences

Synthetic proof establishes software behavior only, not actual provider enforcement,
account availability, rights, history, source qualification, Phase 2 closure or Phase 5
readiness. No broker symbol is presumed available. Actual credentials/sessions and all
trading/money actions remain prohibited. Operational campaigns remain pinned/untouched.

## Validation

[Requirements](../phase2/DS03_ACCEPTANCE.md) map the full macro adversarial matrix.
Run focused/inherited checks, applicable PG, strict typing/lint, docs, equal agent files,
source/history/high-signal scans, locked audit, exact committed fresh Windows clone and
actual public hosted CI. Protect the two local heavy-work windows.

## Review point

One DS-03 PR stays OPEN/UNMERGED for independent exact-SHA review. When actual account
input is next: PUBLIC SANITIZED ENGINEERING COMPLETE;
PRIVATE_RETURN_REQUIRED_FOR_ACTUAL_MT5_DEMO_ONBOARDING. Founder performs PRIVATE return;
verify it and obtain separate accepted onboarding authority. No actual Phase 5 orders
without full Phase 4 closure, accepted actual DS-03 and explicit authority.
