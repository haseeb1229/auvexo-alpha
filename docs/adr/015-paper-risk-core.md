# ADR-015: deterministic isolated PAPER safety core

Status: ACCEPTED/FROZEN for Checkpoint A engineering at e3f39e0397e1846c37febcebc246ea91c9f2eb78; full Phase 4 OPEN
Date: 2026-10-18
Requirements: R-002, R-003, R-004, R-006, R-008, R-021, R-022-A, R-022-B, R-022-C, R-022-D, R-022-E, R-023, R-024, R-025

## Context

The owner-supplied Phase 4 Checkpoint A brief independently accepts Phase 3 at
bb69220818a519e122d2cd9b1cad75559c2fa244, with four INCONCLUSIVE outcomes and no
champion. Documentation-only acceptance 5a3c03f58dbcc351c85ac799800fed74c01ebce3
passed hosted PR/push runs 39114504660/39114500986. Normal PR #4 merge
b24c42bc07dcd9bc1b62b04d32cc92f047116125 has parents
26b20ca5f0ef18e5300d5213b1cc8d2667bb71d3 and
5a3c03f58dbcc351c85ac799800fed74c01ebce3. Phase 4 branch starts at that merge.

## Decision

Freeze [child requirements](../phase4/ACCEPTANCE_TESTS.md) before implementation.
Reuse strict frozen contracts, Decimal boundaries, canonical hashes, PostgreSQL,
SQLAlchemy/Alembic and existing test tools; no dependency addition. Keep the
foundation execution denier and disabled policy unchanged. New PAPER authorization
has explicit non-external semantics, no signing key, and cannot satisfy a broker/live gate.

ER-08's ban on test fixtures in the production runtime registry remains intact.
The owner's bounded exception creates a physically separate TEST_ONLY fixture namespace
for PAPER engineering, never a tradable release/alpha registry entry. Production registry
starts empty. Real release transitions require independently accepted eligible research
and audited owner/reviewer metadata; labels never grant environment permissions.
No Phase 3 result is imported, promoted, retuned or reread as fresh OOS.

Account-serialized PostgreSQL transactions atomically persist intent, authorization,
reservation and outbox. Immutable histories have database mutation guards; mutable
projections are separate. A separate simulator-owned virtual truth ledger gives
reconciliation independent facts. Runtime reads truth; it cannot write it or research/
foundation policy. Persist and fence attempts before the simulated boundary. Ambiguity
retains capacity and pauses new exposure; restart reconciles without blind retry.
Partial actual exposure plus residual reservation cannot exceed the original modeled
capacity. Terminal corrections append, including late fills and external facts.

K0-K4 and edge-state plumbing persist through restart/day boundaries. Only explicit
audited owner PAPER commands resume; agent input cannot promote/resume. Known fresh
reduce-only actions still require exact authorization and cannot reverse/over-close.
UTC flow-adjusted loss/high-water records preserve loss history across virtual adjustments.

## Alternatives

Reject fake champions, SQLite concurrency proof, in-memory outboxes, comparing a table
to itself, retrying unknown sends, blanket approval tokens, home-grown live signatures,
broker SDKs, paid services and new dependencies. No persistent observation task yet.

## Consequences

All evidence is synthetic engineering unless explicitly identified otherwise. No alpha,
broker-spec qualification, live readiness or Phase 4 operational acceptance follows.
Phase 2 B/C and privacy/security/source/financial gates remain open. Current public
exception review is due 2026-10-24. Same-disk recovery is not disaster recovery.

## Validation

Frozen child requirements require exact arithmetic/properties, real PostgreSQL
multi-thread/process races, immutable-role negatives, durable faults/reconciliation,
backup/restore, resource percentiles, inherited denials, locked scans/audit, exact Windows
clone and hosted CI. Failures remain evidence and cannot be hidden or waived by tuning.

## Review point

GPT-5.6 Sol exact-final-SHA review before Phase 4 PR merge or any persistent PAPER
observation. Do not start a 14-day count or Phase 5. Preserve the daily Phase 2 task.
