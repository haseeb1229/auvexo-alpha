# ADR-014: deterministic nonproduction spot research

Status: Phase 3 implementation decision; independent review pending
Date: 2026-10-17
Requirements: R-005, R-006, R-007, R-014, R-015, R-022, R-025

## Context

The owner-supplied Phase 3 prompt accepts ADR-013 at bdae1a1 and authorizes source-specific
non-money research after normal PR #3 merge. Full Phase 2 operational B/C remains OPEN.

## Decision

Add strict typed research rights/price-lag contracts, an exact deterministic event-driven
long/flat spot simulator, train-only chronological validation/statistics and append-only
PostgreSQL research metadata with immutable hash-bound local artifacts. Reuse accepted
Phase 2 ingestion/storage/replay; never relax strict observed-as-of or edit old artifacts.
No production order engine, risk authorizer, permit, broker SDK, agent runtime or UI.
Use stdlib Decimal/statistics/random and existing Polars; no new dependency justified.

StudyManifest freezes sources/rights/ranges/hashes, availability, feature/config grid,
splits/embargo, costs, metrics/screen settings, seed/code/lock and resource budgets before
holdout access. Seal selection and record holdout consumption before read; duplicate trials,
fresh reuse and train/validation after holdout are refused under serialized DB transactions.
Artifacts publish before metadata; failed commits may leave unreferenced files, never
adopted implicitly. Public history contains only generic framework/baseline code and
non-sensitive verification; actual data and experiment artifacts remain local/ignored.

## Alternatives

Root-forking a bot, adding statistical libraries without need, using vectorized trades as
accounting truth, SQLite concurrency proof, price-close lookahead and licensing inference
from alpha are rejected. Derived storage optimization requires measured need and parity;
benchmark the current audit shape first.

The owner-supplied [provider-outage resume brief](../reference/PHASE_3_RESUME_BRIEF.txt)
authorizes only the [V2 availability amendment](../phase3/DATA_PLAN_V2.md), frozen locally
at a3924e41d7efc59370a4c9343f14201f115bb394 before broad resumption. Preserve V1's bytes.
Exact-source raw-proven official venue outages remain DEGRADED/explicitly unavailable;
unknown gaps block. No fills or fresh features during a halt; positions carry through it,
adverse stops reconcile on resume, lookbacks rewarm in wall-clock time. Versioned parser
semantics preserve old exact replay; forward migration changes only the uniqueness index
to admit a new parser-version correction without rewriting any historical manifest.

## Consequences

Hourly lag plus next eligible open can defer a signal by an extra full bar; this explicit
conservative assumption avoids inventing intrabar executable prices. Missing data/rights
block affected claims. NO EDGE and INCONCLUSIVE are valid phase outcomes. Data-use rules
propagate through all input lineage; DS-01/02 confer no production promotion rights.

## Validation

[Child requirements](../phase3/ACCEPTANCE_TESTS.md), [preregistered plan](../phase3/DATA_PLAN.md),
hand calculations, independent reference, truncation/leakage/numeric/split/holdout negatives,
real PostgreSQL races/restore, exact source replay, bounded synthetic multi-year scale,
clean Windows clone and exact-head hosted CI. Preserve every existing execution denial.

## Review point

GPT-5.6 Sol independent exact-final-SHA review before Phase 3 merge or any Phase 4 prompt.
Phase 3 PR remains unmerged; scheduled data task unchanged, DS-03 blocked and all money
actions denied. Public exception review remains due 2026-10-24; no visibility change here.
