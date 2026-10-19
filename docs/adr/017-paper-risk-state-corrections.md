# ADR-017: PAPER position identity, contradictory truth and latched loss

Status: FROZEN clarification; local implementation verified, independent review pending
Date: 2026-10-19
Requirements: R-002-P4-01, R-022-P4-02, R-022-P4-03, R-021-P4-01, R-021-P4-02, R-022-P4-04

## Context

The [second resume brief](../reference/PHASE_4_SECOND_RESUME_BRIEF.txt) authorizes
correction of three material defects found during the security resume. The exact second
stop inventory was `045013eaeaf3d9837eab992030cc66d0e961cd4ae5a463d157b0b470ee243b1e`.
The original security stop inventory remains
`f5e69f9f18ba2ef2f85ca4663d2ef00971c64c25f7c0cda3955748228bfde2f0`.
Both recovery packages were verified and preserved before these corrections.
The frozen [acceptance requirements](../phase4/ACCEPTANCE_TESTS.md) and risk thresholds
remain unchanged. This record clarifies their required invariants, not a gate waiver.

## Decision

A plain OPEN creates a new account-scoped position from its own immutable intent UUID.
It cannot carry a position reference, merge exposure, replace a stop, or amend an existing
position. Typed validation, deterministic duplicate checks, transaction serialization,
database uniqueness and the independent virtual order boundary enforce that restriction.
Partial fills of the same authorized OPEN may accumulate only within their own position.
Existing CLOSE/CANCEL semantics remain bounded; no pyramiding or new action is introduced.

Any REJECTED status with nonzero confirmed fills is contradictory. Keep actual exposure,
UNKNOWN and pause-new, retain conservative capacity, refuse healthy reconciliation and
never resend. An append-only independent resolution must bind the observed facts and
prove the terminal quantity before residual capacity can be released. Later facts invalidate
an outdated resolution; history is never erased or treated as a clean rejection.

Reconciliation evaluates marked daily loss and drawdown under the active frozen policy.
A breach persists K2 and its cause in the same account transaction, without waiting for
another proposal. UTC baseline rollover, fresh marks and restart cannot relax the latch.
Only the existing explicit audited owner PAPER resume may relax eligible state after
fresh reconciliation; active loss, drawdown, UNKNOWN or mismatch still refuses resume.
Virtual flows and day rollover preserve high-water and loss history.

## Alternatives

Reject implicit OPEN merge with recalculated risk, UUID reuse through another logical key,
clean rejection after a fill, terminal-status-only capacity release, and day-based automatic
resume. No new thresholds, action vocabulary, dependency or live authority is added.

## Consequences

The direct LOGIN correction in [ADR-016](016-paper-direct-login.md) remains required.
Security-first real PostgreSQL proof precedes the correctness suite. Tests must cover both
contradiction arrival orders, restart/failure boundaries and serialized collision/day-roll
races. A new material invariant failure stops work again. Synthetic evidence never promotes
the four INCONCLUSIVE Phase 3 outcomes or supplies a genuine observation date.

## Validation

Preserve old position bytes under refused attacks; prove independent position identities,
account/UUID uniqueness and concurrent atomic refusal. Prove actual plus retained capacity
through contradictory partial/rejected facts, append-only resolution and no blind retry.
Prove mark-driven K2 before midnight, retained latch through exact rollover/reconnect,
same-day resume refusal and next-day explicit eligible resume. Run all original security,
correctness, recovery, resource, source/history scan, lock audit, clean-clone and CI gates.
No result is inferred from authored or collected tests.

## Review point

GPT-5.6 Sol exact-final-SHA review before merge or persistent observation. Phase 4 PR
remains unmerged. No 14-day PAPER observation, Phase 5, broker capability or money action.
PUBLIC exception governance review remains due 2026-10-24.
