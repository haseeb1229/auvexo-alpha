# ADR-013: source-specific engineering acceptance and retained operational gates

Status: FROZEN; independently accepted at bdae1a1978ecfe26c201074fe12e81f2c654a4af
Date: 2026-10-17
Requirements: R-003, R-005, R-006, R-014, R-015, R-018, R-022, R-023, R-029, R-030, R-031, R-035

## Context

The frozen roadmap was read as requiring every earlier calendar/source gate before any
later engineering. Phase 2 public historical/replay evidence, scheduled reliability and
Exness read-only qualification have different dependencies. Retrospective downloads cannot
prove operation; blocked Exness inputs need not invalidate already qualified spot engineering.
The [owner-requested amendment](../reference/BASELINE_CORRECTION_BRIEF.txt) authorizes this
governance design and retiming the existing bounded public-data task. It does not authorize
Phase 3 implementation. The broad verification line about an unchanged scheduler conflicts
with that specific authorization; preserve constraints/history while changing only its clock
and description, recording the actual new registration. No other scheduler/power setting changes.

## Decision

Supersede the all-or-nothing sequencing interpretation in the roadmap and the corresponding
review-point interpretation in ADR-012 after independent acceptance. Retain canonical phases
0-9, all original requirement IDs, numeric evidence targets and ADR-001/002/007/009 authority.
This amendment is not implementer self-acceptance and does not reopen accepted Phase 0/1 work.

1. ENGINEERING / RESEARCH-UNBLOCKING ACCEPTANCE: independent exact-head review identifies
   qualified source/product/instrument/range, contracts, rights and availability policy,
   admitted non-money work and exclusions, with evidence and open operational gates. A new
   owner prompt authorizes implementation. No execution capability may be acquired through
   this disposition; no promotion, broker order, DEMO activation or capital permission follows.
2. FULL OPERATIONAL / ACTIVATION ACCEPTANCE: all applicable original real-environment,
   source, calendar, rights, security and promotion evidence must pass. Every gate retains
   explicit OPEN/BLOCKED status until demonstrated; engineering progress cannot satisfy it.

Phase 2 A (trusted selected public history/replay) is a candidate for source-specific
engineering acceptance. B (seven real scheduled dates) stays OPEN and C (Exness DS-03)
stays BLOCKED pending separately approved secure DEMO onboarding/qualification. Full Phase 2
operational status remains OPEN. After independent acceptance and a new prompt, Phase 3
engineering may use admitted DS-01/02 spot ranges while B/C continue. Exness-dependent
BTC/ETH/XAU work remains unavailable; no spot-to-CFD or cross-source claim transfer.

Phase 4 paper observation may overlap unrelated later research/UI engineering. Phase 5
sustained DEMO qualification may overlap scoped non-money Phase 6/7 work on accepted inputs.
Original >=14 paper days, >=30 DEMO days / >=20 sessions / >=100 lifecycle observations,
>=30 days per new material Phase 6 filter and >=90 live days plus adequate Phase 9 sample
remain unchanged. No incomplete qualification may enable activation or promotion. Phase 5
commissioning remains a separately authorized bounded DEMO preflight; this correction grants none.

The existing Phase 2 daily public task is explicitly retimed to warm-up **22:57 Pakistan /
17:57 UTC**, qualification **23:00-23:12 Pakistan / [18:00,18:12) UTC**. Tonight's start
was already past at entry; first eligible date is **2026-10-18**. A shared pure application
schedule serves wrapper and qualification. All manifest/hash/freshness/duplicate/quality checks,
>=11 observations per symbol, >=600-second span and <=120-second gaps remain. Seven actual
consecutive calendar dates are required; no archive/pilot/fixture/old-window count transfers.
Limited interactive identity, IgnoreNew, no retry/catch-up, network/AC, bounded execution and
owner-restricted logs remain. The old proposal/receipt is historical; the
[new receipt](../amendments/SCHEDULER_2300.md) records actual state. Twelve minutes/day proves
only bounded collector reliability, not 24/7 uptime or live readiness.

Future experiment/release manifests must implement and test typed data-use classification:
ENGINEERING_ONLY, PERSONAL_RESEARCH, PROMOTION_ELIGIBLE, BLOCKED, as defined in
[research policy](../RESEARCH_AND_VALIDATION.md). Restrictions propagate through all derived
lineage. Vision is nonproduction research and cannot become promotion eligible on alpha alone;
current appropriate source/intended-use rights are a separate necessary gate. Unknown or
unqualified sources/instruments fail closed. No typed experiment/release implementation now.

Strict observed-as-of remains unchanged. Phase 3 must separately name an opt-in price-close
plus positive causal lag simulation availability policy, retain actual 2026 receipt/processing,
prevent same-close lookahead and record assumptions in the manifest. Macro/news/on-chain
vintages do not inherit price assumptions. No simulator is built now.

Accept the unchanged tested dependency lock under an explicit
[maturity exception](../amendments/DEPENDENCY_MATURITY.md): Windows/CI/restore evidence supports
retention, no auto-upgrade, no cosmetic downgrade, review broker/financial-critical libraries
at adoption. Dependency age is not proof of correctness. Review at next adoption or 2026-11-16.

Require a Phase 3 multi-year 1m benchmark of audit-first Parquet string/canonical-row shape.
Only measured need may justify a later derived optimized representation bound to canonical
dataset/version/hash with exact fixed-point/Decimal parity; no new format or accepted-data rewrite now.

Private-first remains frozen. The temporary owner-approved PUBLIC exception is review-due
2026-10-24; public history cannot be revoked. No broker/session/owner-private data may enter
public history. Before broker credential/session integration or proprietary alpha work,
independent review must resolve PRIVATE return under separate owner instruction or an
owner-approved permanent-public superseding ADR. This ADR does not grant permanent PUBLIC
status or change visibility, billing, permissions or runners.

Before Phase 8, require protected main/release or equivalent reviewed integrity control,
CI-bound release manifest/tag, no unreviewed release, current legal/jurisdiction/data-use
eligibility, EXTERNAL owner/professional tax/statement/recordkeeping disposition, off-device
encrypted recovery and owner-response/uptime proof. No legal, tax or religious conclusion here.

## Alternatives

Retain universal sequential blocking: needlessly couples independent non-money engineering
to future calendar evidence. Declare Phase 2 complete or waive DS-03/seven days: falsifies
operational/source status. Backdate runs, relax observed-as-of, infer data rights from alpha,
renumber phases or build Phase 3 now: violates scope/evidence boundaries. None is adopted.

## Consequences

Acceptance reports must name scope and disposition, retain full operational OPEN status,
and enforce concrete dependencies. Calendar tracks can run alongside accepted non-money
engineering while activation stays closed. Documentation status/navigation is current;
dated handoffs, old scheduler receipt, migrations, locks and accepted data remain untouched.
Execution remains disabled in all modes; Binance live derivatives BLOCKED_BY_POLICY.

## Validation

[Amendment requirement mappings](../REQUIREMENTS_REGISTER.md), current schedule/runbook and
new synthetic boundary/late-start/seven-calendar-date tests; full existing suite, real PostgreSQL,
Ruff/mypy/docs/links, byte-identical agent files, source/history scans and exact-head hosted CI.
Inspect actual registered task after tests/preflight, never count Ready as observation.
Future Phase 3 prompt must require hand-calculated and independent reference correctness,
chronological purge/embargo/walk-forward/OOS/trial/cost tests, source/rights blocking and
NO EDGE validity, with no broker orders. All financial/source gates remain unchanged.

## Review point

The required independent exact-SHA review is supplied in the owner-authorized Phase 3
prompt, accepting this ADR at `bdae1a1` with the source-specific limits below. That prompt
also separately authorizes normal PR #3 merge after an administrative-only acceptance
record, then Phase 3 on a new branch. Full operational gates and later financial gates remain open.

Independent acceptance recorded 2026-10-17: the owner-supplied Phase 3 prompt accepts
exact `bdae1a1978ecfe26c201074fe12e81f2c654a4af`, ADR-013 and DS-01/02 BTC/ETH SPOT
engineering/personal nonproduction research only. Full Phase 2 operational status remains
OPEN; scheduled reliability OPEN, DS-03 BLOCKED. This is a supplied independent disposition,
not a new implementer review. See [acceptance record](../reviews/PHASE_2_RESEARCH_ACCEPTANCE.md).
