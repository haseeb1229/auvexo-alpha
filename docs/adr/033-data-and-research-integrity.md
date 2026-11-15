# ADR-033: Data and research integrity

Status: ACCEPTED on 2026-11-15 with its implementation, after the independent review
recorded in [the OD-23 review](../reviews/OD23_INDEPENDENT_REVIEW_2026-11-15.md).
Applies to new collection and to future studies only. No historical bar, event, trial or
Phase 3 outcome is rewritten, re-run or re-labelled.

Date: 2026-11-13. Owner: founder. Author: Claude (founder-requested OD-23 closure run).

Requirements: findings D-7, D-8, D-10, D-11, RS-8, RS-9, RS-10 and DB-2 of the
[rebaseline audit](../reviews/AUVEXO_FULL_A_TO_Z_REBASELINE_2026-11-12.md);
[data architecture](../DATA_ARCHITECTURE.md); [research and validation](../RESEARCH_AND_VALIDATION.md);
[ADR-013](013-source-specific-acceptance.md); [ADR-014](014-nonproduction-research.md).

## Context

The audit recorded seven integrity gaps that were not fixed on 2026-11-12:

- archive (DS-01) and REST (DS-02) bars for the same minute were never compared;
- a minute the provider never serves wedged the live feed forever, because its checkpoint
  only advances on a complete batch;
- reports loaded whole tables and refuse beyond 10,000 rows, which qualification would
  eventually hit;
- a provider cooldown was global across two different hosts and could not be ended early;
- holdout consumption was enforced only in application code, was not resumable and did
  not log reads after consumption;
- trial hashes for code, lock and input bars were recorded but not verified;
- walk-forward fold years were hard-coded and one fold duplicated the validation window.

## Decision

All of this is in main-chain migration `0006_data_research_integrity`, which only adds.
Every new table revokes PUBLIC, grants least privilege and refuses UPDATE, DELETE and
TRUNCATE.

1. **Cross-source comparison.** `compare-sources` compares every stored DS-01 version
   with every DS-02 version for each bar in a range of at most 31 days. Identical bars are
   recorded as matched. A difference becomes a durable conflict holding both sides'
   values, hashes and rights versions. No source is preferred, and no bar or availability
   time changes. Research reads refuse any version involved in a recorded conflict.
2. **Reviewed gaps.** When the provider repeatedly serves a range without a bar, the owner
   can record a gap with `record-gap`. That needs at least two distinct stored responses
   that requested the whole range, report the gap themselves and contain none of its bars,
   and no other stored response with a bar in it, plus a reviewer label. Only then does the
   collector move past it. Nothing is filled or repaired. The gap stays in coverage
   permanently and the UTC day containing it can never qualify.
3. **Bounded reporting.** Qualification reads only the events, manifests, cooldowns and
   gaps for the days it judges. Reconciliation pages through rows. `coverage` and
   `evidence` take an explicit range of at most 31 days. Qualification semantics are
   unchanged.
4. **Host-scoped cooldowns.** A cooldown applies to the host that caused it,
   `data.binance.vision` or `data-api.binance.vision`, matching Binance's per-IP, per-host
   limits. A cooldown recorded before this change still blocks both hosts, and reports
   show it once per host, each ended only by that host's passed probe. The 418, 429,
   403 and 451 handling is unchanged. `release-cooldown` lets the owner end one early with
   a recorded reason; the collector then sends exactly one probe, and only a passed probe
   clears the host. Any UTC day touched by a cooldown on any host cannot qualify.
5. **Database-enforced holdouts (future studies).** The research role can no longer
   insert a holdout opening. Opening goes through a SECURITY DEFINER function that checks
   the study, the seal, a frozen one-config-per-family selection and a complete validation
   grid, all under lock. Every authorized read is logged with phase and range, including
   out-of-sample reads after completion. An interrupted holdout resumes without reopening:
   identical trials are accepted, different ones refused, and only missing trials added.
6. **Real trial identity.** At registration and at every read, the study's code hash must
   equal the running research code, its lock hash must equal `uv.lock`, and every input
   manifest must exist in the store with its hash. Each new trial artifact carries the
   config, the cost model, the availability policy, those hashes, its authorized read
   receipts and the digest of the bars it actually consumed. Any mismatch refuses.
7. **Walk-forward folds.** Folds are derived from the registered training span alone
   (rule `expanding.train-span.365-day-segments.v1`), never from hard-coded years, and
   never overlap validation. Fold output is marked informational and selection uses
   validation only, unless a future preregistration says otherwise
   ([template](../phase3/FUTURE_STUDY_PREREGISTRATION_TEMPLATE.md)). For the Phase 3 split
   the rule reproduces the old first fold and drops the duplicate; the recorded Phase 3
   outcomes are not touched.
8. **Disposable test databases.** Research-ledger integration tests each use their own
   generated `auvexo_test_<hex>` database, dropped afterwards.

## Alternatives

- **Prefer one source when they disagree.** Rejected: it would let the convenient answer
  win. A conflict is evidence and stays visible.
- **Forward-fill or skip a missing minute automatically.** Rejected: fabricates or hides
  a fact. The reviewed gap keeps the hole and lets collection continue.
- **Raise the report budget.** Rejected: it only delays the failure and keeps loading
  whole tables.
- **Keep one global cooldown.** Rejected: the provider scopes limits per host, so a
  global one blocks safe work for nothing; it remains the rule for old events.
- **Enforce holdouts in application code only.** Rejected: the audit showed a role with
  insert rights can bypass it.

## Consequences

- Operators must pass a day range to `coverage` and `evidence`.
- Three new owner commands exist: `compare-sources`, `record-gap`, `release-cooldown`.
- The walk-forward trial count for a Phase 3-shaped study drops from 61 to 54.
- A future study whose code or lock changes after registration must be registered anew.
- The code hash covers every module the research path imports, including
  `domain/source_reviews.py`, `infrastructure/data_store.py` and
  `application/data_quality.py`. So a rights renewal or a collector edit also changes it.
  That binding is kept on purpose. The operating rule: no change to a research-hashed
  module, rights renewals included, is released while a holdout is OPEN. A holdout is
  opened only when no rights review falls due before it can complete. Breaking the rule
  fails closed: reads refuse, and the consumed holdout has no result.
- The database refuses a trial of any phase unless a gate-authorized read of that phase
  for the same study exists with its bars bound to a digest. It refuses to freeze a
  selection until every registered config has its own validation trial.
- Remaining limit: the database cannot prove that a trial's result was computed from the
  bars it read, or that the frozen selection follows the validation results. Artifacts
  live outside the database. The research role, using raw SQL after a logged validation
  read, could still file made-up validation trials and freeze any one-config-per-family
  selection. The application checks each artifact's identity and read digests, and the
  logged receipts show every read, but only review can catch such a forgery.

## Validation

Unit tests cover same, missing, conflicting and revised bars, gap evidence refusals,
cooldown scoping, release and single probe, fold derivation, and trial-identity
mismatches. PostgreSQL tests (on a disposable cluster and in CI) cover the conflict
tables, a gap that unwedges the feed and stays visible after a later provider revision,
qualification beyond 10,000 rows, two concurrent holdout resumers after a crash (exactly
one completes, one opening, earlier trials unchanged), raw trial inserts refused without a
bound read of their phase, a selection refused before the validation grid is complete, the
recovery drill covering every guarded table, and the database dropping each generated test
database.

## Review point

Independent review of the implementing pull request before merge. Any new study must use
the template and pass these gates; the consumed Phase 3 holdouts may never be named.
