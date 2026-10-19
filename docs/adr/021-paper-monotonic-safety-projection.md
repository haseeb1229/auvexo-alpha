# ADR-021: monotonic transaction-local PAPER safety projection

Status: ACCEPTED/FROZEN for Checkpoint A engineering at e3f39e0397e1846c37febcebc246ea91c9f2eb78; full Phase 4 OPEN
Date: 2026-10-19
Requirements: R-021-P4-02, R-022-P4-02/03/04, R-023-P4-01, R-024-P4-01

## Context

The [fifth resume](../reference/PHASE_4_FIFTH_RESUME_BRIEF.txt) authorizes correcting
the pending-truth/loss-denial projection interaction and completing the retained
[performance drafts](020-paper-transaction-performance.md). The preserved stopped
aggregate is 5399debc21698394c66841dafd688a2ab575759b77a534a9bd7bd8cb644573a0;
reviewed HEAD remains c0a470bbf9530ccd89d82df6e96811df2ed20cda.

## Decision

Within the account-locked transaction, keep one authoritative local account projection.
Each later transition derives from the latest established projection. Pending truth
sets reconciled false without advancing its cursor; a subsequent loss denial latches
at least K2 on that same projection. It cannot restore an older reconciled flag or
relax any other safety field. Journal and durable projections agree atomically.

Only authoritative reconciliation can consume pending truth and restore reconciliation
readiness. It does not clear K2. Owner resume and subsequent authorization retain all
existing truth-cursor, health, freshness, loss and explicit owner checks. No authority
is issued by these denials. Preserve existing event kinds, ordered reasons and hash
envelopes; do not substitute the separate marked-loss helper if doing so changes their
semantics or loses conservative projected-risk denial behavior.

## Alternatives

Reject assertion-only changes, stale projection reuse, silent auto-resume, weaker
database guards, skipped tests, mutable cross-transaction caches, broader privileges,
changed benchmark workload/limits or repeated final acceptance attempts.

## Consequences

The frozen requirements, benchmark script, all sample/admission/competitor settings,
dependencies and migrations stay unchanged. Retained optimizations remain unverified
until real PostgreSQL correctness and full direct-LOGIN security reruns pass.

## Validation

Run focused real-PG pending-truth/loss cases FIRST: each loss reason and both, multiple
pending facts, repeated denial, blocked owner resume/authority, real reconciliation
without K2 reset, later healthy explicit owner resume, and injected rollback boundaries.
Then verify prior fixes, retained optimization scope/tail/drift checks, full PG/security
and query/index/profile follow-up. Declare ONE final unchanged benchmark only afterward.
Any transaction above 100 ms stops for formal performance-governance disposition.
If it passes, complete all mandatory changed-source verification, exact-final clone
and coherent exact-head push/PR runs AND jobs before independent review.

## Review point

GPT-5.6 Sol exact-new-SHA review or formal performance-budget disposition. Keep PR #5
unmerged; no observation, Phase 5 or broker/money work. Collector priority takes
precedence during 22:45-23:20 Pakistan; inspect qualification read-only afterward.
