# Research and validation

Status: FROZEN method; numerical promotion criteria PROVISIONAL and preregistered per study.

The research unit is a falsifiable hypothesis, not a prompt or a profitable equity curve.
Register hypothesis_id, rationale, assets/products, horizon, data/features/availability,
entry/exit/sizing rules, baseline, expected mechanism, falsification criteria, experiment
budget, parameter space, split plan, metrics and decision rule before examining holdout.
Archive all trials, including failed variants. New search after holdout inspection consumes
that holdout; use fresh forward data rather than relabeling it untouched.

Initial hypothesis families are deliberately simple: slow trend breakout with fixed risk,
session-conditioned XAU behavior, and BTC/ETH volatility-conditioned mean reversion.
These are research candidates, not claimed edges. Compare to NO TRADE, an appropriate
passive exposure benchmark, and a simple fixed-rule strategy at comparable risk/cost.
No leverage optimization to manufacture attractive returns.

## Reproducible pipeline and proof

1. Freeze dataset manifest, code/dependency versions, seed, calendar and feature definitions.
2. Split chronologically: initial default 60% train, 20% validation, 20% untouched OOS,
   adjusted before experimentation for time span/regimes. Never random-shuffle time series.
3. Purge overlapping labels across split boundaries and embargo at least the maximum
   label/holding horizon. Fit scalers/feature selection/regime models on training only.
4. Run rolling/expanding walk-forward folds with parameter selection inside each training
   window. Seal OOS selection until final evaluation; track every trial for selection bias.
5. Use an event-driven deterministic fill/accounting simulator. Vectorized feature search
   is exploration; authoritative claims must replay order chronology and the common intent/risk
   rules. Compare both on small hand-calculated fixtures.
6. Model bid/ask spread, commissions, swaps/funding, contract sizes, FX, slippage, latency,
   rejected/partial/unknown fills where relevant. A bar touched limit is not guaranteed fill.
   If stop and target are touched in the same bar, use adverse ordering or higher-resolution
   evidence; do not choose favorable chronology. Next-bar availability prevents same-close leakage.
7. Stress costs at 1x/1.5x/2x assumptions, parameter neighborhoods, delayed data/entry and
   missing periods. Segment by regime, asset, session and major event without post-hoc cherry-picking.
8. Report confidence intervals via dependence-aware/block bootstrap where justified, tail
   scenarios and Monte Carlo trade-order stress. Monte Carlo is sensitivity, not proof that
   serial dependence disappears. Correct multiple comparisons or report adjusted evidence.
9. Reproduce from a clean environment and compare to an independent small reference fixture.
   A reviewer can trace every trade to available-at data and versioned decisions.

Metrics (where meaningful, with definitions and sample sizes): net expectancy, profit factor,
max drawdown and duration/recovery, Sharpe, Sortino, Calmar, average R, win rate, average
win/loss, tail losses/expected shortfall, turnover, fees, slippage, gross/net exposure,
strategy correlation, and performance by regime/asset/event. Declare annualization frequency,
risk-free assumption and mark-to-market method; undefined ratios remain null with reason.
Use daily portfolio returns for comparable risk-adjusted metrics; irregular trade returns
must not be annualized as if independent daily observations. R uses preregistered initial
modeled risk including costs, never a post-trade denominator that improves the result.

Candidate screening default: >=100 closed trades and >=6 months OOS spanning more than
one regime, net positive expectancy with a positive lower 95% dependence-aware interval,
cost stress survivability, stable neighboring parameters, and drawdown within the
preregistered experiment limit. These are minimum screens, not statistical sufficiency
or guaranteed profitability. Low-frequency strategies may require much longer observation.
Failure or insufficient sample yields NO EDGE/INCONCLUSIVE and more research, not relaxed
criteria after seeing results. Operational readiness can pass with no tradable champion;
capital authorization cannot.

## Champion, challenger and evidence artifacts

RESEARCH -> CANDIDATE -> VALIDATED -> PAPER -> SHADOW -> LIVE_LIMITED -> LIVE;
any active state may become SUSPENDED, then reviewed requalification or RETIRED.
DEMO is an account/execution mode used during PAPER/SHADOW operational qualification,
not a second strategy lifecycle. A lifecycle label never overrides environment permissions.
CHAMPION means the currently authorized strategy release for its scope; challengers may
run against the same timestamped market in paper/shadow. The production registry contains
code/config/data provenance hashes, allowed modes, evidence manifest and approvals.
No AI promotion or silent mutation. Every promotion creates a release artifact and rollback
target. Live promotion requires both alpha evidence and independent operational/security proof.

ExperimentReport contains preregistration, full trial ledger, dataset manifest, splits,
cost models, metrics with uncertainty, baseline comparison, sensitivity charts/tables,
failure analysis, reproducibility command and decision. Immutable artifacts bind the release.

## Mandatory counterfactual book

Record every otherwise-valid rejected candidate, including risk, blackout, execution,
data health, regime, news/macro and policy rejection. Capture candidate/intent hash,
decision timestamp, contemporaneous features/prices, policy versions, all rejection
reasons and their evaluation order, intended entry/exit/size, simulator version and horizon.
Missing data creates an UNOBSERVABLE outcome; do not fill gaps with invented prices.
Generate forward hypothetical outcomes using the same frozen cost/fill rules. Clearly label
counterfactuals as simulated, never broker fills. Keep overlapping candidates and capacity
constraints in paired portfolio replay; summing all rejected winners is invalid attribution.

Evaluate filters through paired with/without replays on the same admissible candidates,
including saved losses, foregone gains, coverage and uncertainty. Randomized paper/shadow
ablations can test selection bias when safe; observations alone do not establish causality.
News, macro, agents and alternative data must demonstrate incremental net value after
cost/latency. This never authorizes bypassing the real risk kernel to run an experiment.

## Edge decay and model roadmap

Compare expected OOS distribution with recent shadow/live behavior, execution costs and
data coverage. Default monitoring windows 30/90 days and 50/100 trades (both time and
minimum samples considered); preregister change thresholds and control false alarms.
NORMAL -> WATCH on a weak warning; REDUCE only under an approved size rule; SUSPEND on
hard risk breach or confirmed degradation; INVESTIGATE creates a research task. Hard
risk caps operate even with insufficient statistical sample. Suspended strategies never
auto-resume or self-edit. Record drift reason, evidence and owner-reviewed disposition.

Later models: logistic/statistical baseline, then boosted trees/regime models, calibration
and anomaly detection only after deterministic baseline and leakage tests. Deep learning,
GPU use and reinforcement-learning execution are deferred until measurable need and
resource review. Pretrained LLMs explain/investigate; they do not supply missing historical truth.
Historical LLM evaluation can leak future knowledge through model pretraining even when tool
retrieval is point-in-time correct. Record known training cutoff/version and contamination
limits; do not count a historical LLM narrative as clean OOS evidence. Material LLM filters
require prospective frozen-model paper/shadow evaluation before any promotion claim.
