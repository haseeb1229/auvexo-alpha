# ADR-023: Phase 4 actual-feed PAPER observation qualification

Status: FROZEN for Checkpoint B implementation on 2026-10-20; independent exact-SHA
review and separate owner START remain required. Observation dates = 0.

Requirements: R-002-P4-01, R-022-P4-01 through R-022-P4-04, R-006-P4-01/02,
R-008-P4-01, R-023-P4-01, R-024-P4-01, R-025-P4-01; child requirements
[OB-01 through OB-15](../phase4/OBSERVATION_ACCEPTANCE.md).

## Context

Checkpoint A was independently accepted at
`e3f39e0397e1846c37febcebc246ea91c9f2eb78`. Documentation-only acceptance commit
`e39d590caa008608d0dbd543418021f0e6fcd10b` passed exact-head push run 39323596190 /
job 118303614777 and PR run 39323603425 / job 118303637839, each with 1273 tests
passing. PR #5 merged normally at `dbe3cd6f47bf5a48c044df2f36cba5ea7081ca09`;
its verified parents are `b24c42bc07dcd9bc1b62b04d32cc92f047116125` and the
acceptance commit. Remote main pointed to that merge when this branch was created.
The diff from the accepted source was documentation only. Full Phase 4 remains OPEN.

The [owner brief](../reference/PHASE_4_CHECKPOINT_B_BRIEF.txt) authorizes machinery
for actual-feed, nonproduction PAPER engineering, not observation START or Phase 5.
The existing polling checkpoint can catch up historical bars; it cannot be used
unchanged for counting newly observed bars. The existing two-second market-age cap
also means finalized minute closes often produce correct stale-market denials.

## Decision

Implement the frozen [acceptance requirements](../phase4/OBSERVATION_ACCEPTANCE.md)
and [runbook](../phase4/OBSERVATION_RUNBOOK.md). Reuse DS-02 PublicHTTP, parsers,
Candle contracts, rights records, manifests and immutable local archives. A separate
observation feed key requests only the latest finalized minute in the current window;
no checkpoint catch-up, archives, synthetic bars, alternate venues or forward fill.
Preserve provider end/event time and original receipt/processing/availability times.
Market `as_of` remains the bar end, never the receipt time. Existing numeric risk and
freshness limits remain unchanged. Valid denials, including all-denial runs, can meet
operational criteria; neither simulated fills nor profit are a daily minimum.

Use a USDT virtual account and exact `binance.spot.BTCUSDT` / `binance.spot.ETHUSDT`
identities. Quote/account currency identity is 1 USDT per USDT, never an asserted
USD peg. Versioned engineering spread/fee/slippage/gap assumptions confer no claim
of executable exchange prices. The separate `paper.observation.fixture.v1` release
is TEST_ONLY, ENGINEERING_ONLY and PAPER_QUALIFICATION_FIXTURE. Production remains
empty. OPEN is long only; reductions name the existing position. Quantity planning
is bounded by 0.05% equity and the unchanged kernel caps. Price direction never
controls cadence. Every proposal and resulting decision is durably replayable.

Only an approved, claimed, durably recorded SIMULATED PAPER order may later fill.
A fill requires a later independently received, verified bar with strictly later
provider end and availability, bounded quantity/price/expiry and versioned assumptions.
Crash ambiguity becomes UNKNOWN/reconciliation-only; it never causes blind resend.
New/increased exposure is denied on stale/unknown/gapped source. Existing truth is
retained. No invented final close if feed disappears. No automatic clearing of
K2/K3/K4, suspension, manual pause or loss latch. Startup writer fencing and truth
reconciliation precede proposals. K1 writer pause does not authorize implicit resume;
any owner resume uses the existing explicit audited owner-command path.

Persistent databases use `auvexo_paperobs_<20hex>` and three dedicated direct LOGINs
with the accepted group/attribute/checkout attestation model. Administrative sessions
only provision/migrate/restore. An observation-only additive schema/version table
requires base migration 0005 and leaves merged migrations and normal DEV 0004 intact.
No default Alembic head change. Runtime cannot manufacture truth/source facts; the
truth identity has only the explicitly attested observation ingestion additions.
Append-only source, proposal, verification and receipt records bind the existing
PAPER journal. Date uniqueness, server-clock window guards and activation authority
prevent runtime backdating and double credit. Counter derives from verified immutable
qualified receipts, not a mutable integer or imported JSON. PREPARED is inactive;
tests/preflight/restore never activate or qualify the real campaign. An owner START
record must bind the independently reviewed exact SHA and future eligible date;
this prompt creates no such record.

The future task definition is limited interactive owner, no stored password or
highest privileges, no wake/power mutation, one instance, no catch-up, at
21:00-22:00 Asia/Karachi (16:00-17:00 UTC). Starts more than 15 seconds late refuse.
The definition helper must not register/start any task. Qualified closure requires
at least 14 distinct genuine post-START dates AND last-date minus first-date >=14
calendar days. Fourteen consecutive dates alone span only 13 days and are insufficient.

## Alternatives

Rejected: using historical polling checkpoints, receipt timestamps to freshen closes,
relaxing risk caps, fixture-only calendar credit, runtime-supplied PASS flags, a mutable
counter, ephemeral TEST/RESTORE as the campaign store, admin-backed runtime pools,
editing merged migrations, automatic kill reset, or starting the task before review.
An observation-only schema extension avoids changing the accepted default migration
head while enabling database-enforced append-only schedule/date controls.

## Consequences

The harness can qualify engineering operation without approvals or profitability.
It cannot qualify alpha, promote a fixture or enable money. Rights expire at the
existing 2026-11-16 review gate unless independently renewed; missed days can extend
the campaign beyond it, in which case operation stops for rights review. Raw feed,
receipts, credentials and dumps stay ignored/local. PUBLIC exception review is due
2026-10-24; settings remain untouched. Phase 2 collection keeps absolute priority.

## Validation

Freeze precedes executable edits. Required adversarial, real-PG direct-LOGIN,
immutable-ledger, causal replay, recovery, full inherited tests/statics/docs/scans,
hash-required dependency audit and exact-final Windows clean clone are listed in
OB-15. Preserve all Checkpoint A timing receipts; never rerun that benchmark.
New PR remains open/unmerged with exact-head push and PR run/job/log success.

## Review point

GPT-5.6 Sol exact-final-SHA review BEFORE task registration and a separate explicit
owner START. Later activation cannot waive rights, protected windows, zero money
capability or public governance. Material correctness/security/recovery/CI/dependency
regressions stop the affected phase with preserved evidence.
