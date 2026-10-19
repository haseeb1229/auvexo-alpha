# ADR-020: bounded PAPER authorization roundtrips

Status: ACCEPTED/FROZEN for Checkpoint A engineering at e3f39e0397e1846c37febcebc246ea91c9f2eb78; full Phase 4 OPEN
Date: 2026-10-19
Requirements: R-022-P4-03, R-023-P4-01, R-024-P4-01, R-025-P4-01

## Context

The [performance remediation](../reference/PHASE_4_PERFORMANCE_REMEDIATION_BRIEF.txt)
accepts correctness/security/recovery at c0a470bbf9530ccd89d82df6e96811df2ed20cda,
with PR #5 unmerged and the full-transaction target still open. Entry evidence and
the one unchanged baseline reproduction are retained locally. Diagnostic profiling
found five journal replays and nine runtime checkout catalog roundtrips per authorization.

## Decision

Reuse one fully verified journal only within the same account-locked authorization
transaction. Pass that local history explicitly to projection/reservation/edge checks;
append successful in-transaction events to its local tail. Never retain mutable account,
reservation, journal or privilege state across transactions. Preserve every hash,
projection, duplicate, UNKNOWN, truth-cursor, kill, reservation and atomic outbox check.

If consolidating checkout SQL, evaluate the entire existing catalog attestation on every
checkout using one coherent statement snapshot. Preserve endpoint/UTC checks, complete
grant/role/column/sequence/definer coverage, comparison/error precedence and rollback
before application access. Do not cache mutable security results or broaden privileges.
Only immutable expected allowlists may be prepared once per bound engine.

## Alternatives

Reject weaker locks, deferred/asynchronous authorization, cached mutable state,
incomplete attestation, changed Decimal math/durability, changed targets/workload,
outlier removal, changed percentile definitions or repeated acceptance runs.

## Consequences

The benchmark source, sample counts, three instruments, research phases, two workers,
queue 32 and 5x burst stay frozen. Profiling is diagnostic, not acceptance evidence.
Keep the unchanged original benchmark and every historical receipt intact.

## Validation

Prove unchanged decisions and atomic journal/reservation/outbox effects, corruption
refusal, races, crash rollback and all earlier correctness/security invariants.
Declare one final frozen benchmark only after coherent code and focused safety tests.
Any measured admitted/primary reservation transaction above 100 ms stops remediation;
no lucky rerun. If performance passes, rerun all required correctness/security/full-suite,
recovery, scans, audit, exact-final clone and coherent exact-head hosted CI.

## Review point

GPT-5.6 Sol exact-new-SHA review before merge. PR #5 stays unmerged. Preserve collector
priority 22:45-23:20 Pakistan, and inspect genuine qualification read-only afterward.
No persistent observation, Phase 5, broker/order/permit work or paid service.
