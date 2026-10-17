# Phase 3 nonproduction research implementation

Independent review pending. [Stable child requirements](ACCEPTANCE_TESTS.md) refine the
existing parents; [V1](DATA_PLAN.md) and the frozen [V2 amendment](DATA_PLAN_V2.md) retain
their original hashes. The owner [phase brief](../reference/PHASE_3_BRIEF.txt) and
[resume brief](../reference/PHASE_3_RESUME_BRIEF.txt) define this bounded scope.

## Data and availability

Reuse the Phase 2 collector, raw checksums, PostgreSQL manifests, exact Parquet records
and replay. Typed research eligibility binds source/provider/SPOT instrument/timeframe,
range/version/hash, reviewed rights and expiry, intended use, derived restrictions and
availability. Unknown endpoints, rights, quality or cross-product transfers fail closed.
Neither current source confers promotion entitlement. PRICE_CLOSE_PLUS_CAUSAL_LAG is
explicitly opt-in and positive; original receipt/processing and strict observed-as-of stay.

Complete coverage and official, source-bound provider unavailability are distinct typed
dispositions. A confirmed outage never becomes PASS or a candle. The retained
[BTC diagnosis](evidence/provider-outage-diagnosis.json) distinguishes verified fact-extract
hashes from unavailable original HTML bodies. Certificates bind each instrument's actual
raw/manifest hashes and bounded missing/truncated rows. New unknown gaps stop acquisition.
No replacement venue, synthetic candle, interpolation or forward-fill exists.

spot.v2 rejects truncated full-interval claims with TRUNCATED_INTERVAL and other closing
boundary violations with INTERVAL_BOUNDARY. Legacy spot.v1 keeps its original code in
exact replay. Migration 0004 admits parser-version correction lineage through an expression
uniqueness index; historical payloads, raw bytes and merged migrations remain unchanged.

## Simulation and accounting

The application simulator consumes immutable Candle sequences and a narrow SignalRule.
It imports no execution adapter or safety authorizer. It replays UTC bar closes, opens,
positive-lag publications and effective unavailability in deterministic order. A decision
cannot fill at its close or an already-passed adjacent open. Intrabar stop wins ambiguity;
stops use adverse gap prices and targets receive no favorable gap bonus. Every fill is
SIMULATED. Fees, full-spread/half-side impact, slippage and latency are explicit assumptions.
Synthetic partial-entry tests do not claim historical depth realism. Long/flat unlevered
spot cash, basis, holdings, realized/unrealized PnL and equity reconcile in Decimal.

During unavailability there are no fills, pending entries expire and existing holdings
remain open. Stale marks carry only with STALE_UNAVAILABLE, including final valuation
when replay ends inside a halt. Resume reconciles adverse stops at the first valid open.
Outage exposure is retained separately. Timestamp-adjacent lookbacks exclude unavailable
windows and naturally rewarm. Training medians exclude those windows too. Historical
outage knowledge never blocks an earlier entry or becomes a strategy feature.

## Research workflow and evidence

StudyManifest fixes the generic seven-configuration grid, hypotheses/falsification,
SPOT/hourly inputs, rights, both plan hashes, feature/availability versions, costs,
chronological splits, purge/embargo, seed/code/lock, comparison and resource budgets.
PostgreSQL study/trial/event metadata are append-only; artifacts are immutable hash-addressed
JSON. A dedicated non-login research privilege group can insert research metadata but
cannot mutate it, write ingestion/policy tables or create production capability.

The worker fits training only, records in-sample baselines, runs two expanding folds,
then the entire validation grid at the frozen cost multipliers. It records the training
fit and deterministic validation selection before consuming the holdout. OOS consumes
the instrument/calendar under a serialized global overlap check, before any OOS read.
Changed dataset versions or study IDs cannot make an overlapping calendar fresh.
After consumption, development reads/trials and unselected OOS configs are refused.
Duplicate trials and trial/storage pressure fail explicitly. A failed write may leave an
unreferenced artifact; it is never silently adopted. Recovery restores metadata and artifacts.

Metrics define trade expectancy, profit factor, drawdown/duration/recovery, daily risk
ratios, R, wins/losses, turnover, modeled costs, exposures, tails, asset/regime/UTC-session
segments and outage exposure. Undefined statistics carry null/reason. Regimes use the
training volatility median and causal trend. Circular daily block bootstrap resamples
daily closed-trade PnL/count pairs, including zero-trade days; 7/14/28-day blocks, 2,000
draws and Bonferroni four-comparison lower bounds remain frozen. Trade-order permutations
are sensitivity only. Neighbor stability uses the preregistered validation grid; no
unselected OOS neighborhood search is performed. Insufficient screens give INCONCLUSIVE;
failed adequate screens give NO_EDGE. CANDIDATE would still be nonproduction only.

Rejected candidates retain decision-time evidence, config/feature/simulator versions and
reason ordering. Forward counterfactuals replay isolated observable paths with the same
cost/availability rules. Missing forward evidence stays UNOBSERVABLE. Overlapping
counterfactuals have no summed portfolio-profit output.

The separate synthetic two-year 1m benchmark measures the existing audit-first schema,
pruned scans, filtered load, batched canonical validation, event replay, RSS/CPU and bytes.
It never enters source/experiment eligibility. No dependency or alternate numeric truth
was added. Actual empirical inputs, ledgers and results remain owner-local while PUBLIC.

No Phase 4, Exness/XAU/CFD, broker SDK/account/order, permit or execution enabling is added.
Full Phase 2 operational observation/DS-03 gates and the unchanged daily task remain open.
