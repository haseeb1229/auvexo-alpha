# DS-03 synthetic read-only runbook

Status: FROZEN BEFORE IMPLEMENTATION; 2026-11-02; ADR-028; ENGINEERING_ONLY.
No actual account/session, SDK import or provider network activity.

## Fixed boundary

The outer tool composes only the reviewed synthetic connector. The launcher uses the
current isolated interpreter, fixed installed package module/backend and inherited
anonymous pipes; no caller executable/path/module/profile/account knobs. Ephemeral
key/session bootstrap stays in memory/pipe, never CLI/environment/log/storage.

Ds03ReadPort: attest()->Ds03Attestation, execute(Ds03Request)->Ds03Reply,
disconnect()->None. Ds03Reader.read(request,now) performs fresh pre/post identity,
read-only/rights/expiry/time/spec/lineage checks. Requests are a strict discriminated
union: ATTEST, SYMBOLS, SPEC, TICK, BARS, TICKS, ORDERS, POSITIONS, DEALS,
ORDER_HISTORY, DISCONNECT. History requests bind exact symbol where relevant, UTC
start/end and limit. Replies bind request UUID/operation, typed payload and envelope.
No trade method or SDK object crosses the interface.

Limits: frame65,536 bytes; one pending request;256 requests/session;128 symbols;
256 records/request;10-second monotonic deadline;attestation age<=30 seconds.

## Synthetic inspection and recovery

1. Verify merged-base Development branch and preimplementation freeze commit/hashes.
   Inspect Operational pin read-only only; never modify its task/config/activation.
2. Launch fixed synthetic child and authenticate fresh bootstrap. Pin independent
   expected synthetic DEMO/login digest/server/profile/process/release/config/rights.
3. Discover exact synthetic symbols/suffixes/specs and perform bounded typed reads.
4. Reattest before/after reads; preserve immutable source envelopes/unknowns/gaps.
5. Label untrusted-clock results STRUCTURAL_ONLY_CLOCK_BLOCKED, no qualification.
6. Disconnect and discard in-memory auth/session. Failure closes session; no partial
   result, implicit account switch or silent retry. Recovery needs fresh bootstrap.

## Synthetic secret proofs

Production DS-03 password operations remain inert until later reviewed onboarding.
Only test-owned synthetic read-only passwords in UUID leaves may exercise native
CurrentUser DPAPI/ACL/atomic operations. Test missing/corrupt/wrong-purpose/rotation/
no-replace/reparse/hardlink/redaction failures. Cleanup only exact verified test-owned
leaf; preserve failure evidence. Never inspect/decrypt/rotate existing OI/Operational
credentials. No PA/trading/email/recovery/REAL credential is accepted.

## Publication and review

Run D3-15 after respecting protected20:45–22:15 and22:45–23:20 Asia/Karachi windows.
Retain exact counts/logs; source/history scans before each public push. A real secret
triggers PUBLIC_SECRET_EXPOSURE_RESPONSE_REQUIRED without printing/history rewrite.
No new machine identifiers/private broker data/proprietary alpha in public Git.
One DS-03 PR stays OPEN/UNMERGED for independent exact-SHA review. Candidate SDK
review does not constitute adoption, binary certification, actual rights or onboarding.

When actual account information becomes the next action, report:
PUBLIC SANITIZED ENGINEERING COMPLETE.
PRIVATE_RETURN_REQUIRED_FOR_ACTUAL_MT5_DEMO_ONBOARDING.
Founder returns PRIVATE; verify visibility and obtain accepted actual onboarding,
current provider/terms/package proof before account/session/credential work.
No actual Phase5 orders without full Phase4 closure, accepted actual DS03 and authority.
OI and Phase2/4 campaigns remain unchanged; all genuine forward credit is unaffected.
