# Phase 3 preregistered coverage and experiment plan

Frozen before new downloads or holdout inspection, 2026-10-17. No proprietary alpha is defined:
these are generic reference baselines. Actual experiment outputs remain ignored/local.

Acquire only BTCUSDT/ETHUSDT DS-01 SPOT **1h monthly 2022-01 through 2025-12**, using the
existing Phase 2 collector/parser/store. These 48 chronological months cover training and
held-out chronology with varying mechanically identified volatility/trend conditions. This
is a study-specific range, not a universal history minimum/cap. Use existing selected PASS
versions when the exact logical range exists. Preserve all earlier manifests and degraded
March 2020 ranges; no splicing incomplete ranges or forward filling. New archives remain
provisional until existing checksum/schema/gap/duplicate/lineage/rights/hash gates pass.

Maximum 96 monthly requests-pairs (192 GETs before retries); <=384 attempted GETs across
bounded invocations, <=64 MiB aggregate response bytes, <=256 MiB added accepted artifacts,
one worker, Polars <=2 threads, no broker endpoints/credentials/provider fallback. Per-invocation
Phase 2 rate/body/row/quota/cooldown limits remain unchanged. Stop on access/rights restrictions.
No new 1m acquisition: the existing October 10-16 daily PASS 1m partitions support short
resolution checks only; hourly OHLC authoritative simulation uses adverse intrabar ordering.
The separate synthetic multi-year 1m performance benchmark never enters the research registry.

Per instrument, freeze exact qualified manifests/hashes in a StudyManifest before running:
train [2022-01-01,2024-01-01), validation [2024-01-03,2025-01-01), OOS
[2025-01-03,2026-01-01). Two-day purge/embargo separates phases, >=48h maximum holding.
Use expanding walk-forward development folds: fit 2022, validate 2023; fit 2022-2023,
validate 2024 after the same gap. No final 2025 OOS until selection is sealed. This calendar
split replaces an unjustified mechanical 60/20/20 because it preserves a full OOS year.
Preregistered price-only availability: finalized close + **1 second**, latency **1 second**.
Execution uses the first subsequent bar open strictly after decision/latency; an adjacent
hour's open already preceding availability cannot fill. Actual 2026 receipts remain unchanged.

Two hypothesis families, two windows each: slow breakout lookbacks **72/168h** (long on a
close above previous-window highs, exit on stop/target/48h horizon) and volatility-conditioned
mean reversion **24/72h** (close >=1.5% below window mean, only at/below the training median
24h mean absolute return, exit on stop/target/24h horizon). Both long/flat only, unlevered
25% cash allocation, 2% stop and 4% target. No parameter expansion after inspection.
Compare NO TRADE, 25% passive spot and fixed-rule 24h trend at the same allocation/costs.
Train-only volatility threshold is frozen before validation/OOS; no OOS fit.

Assumed full spread 5 bps, slippage 2 bps/side, commission 10 bps/side, stress multipliers
1/1.5/2. No historical bid/ask/depth entitlement or realistic-fill claim. No swap/funding
for unlevered spot. Full entry fills in empirical runs; synthetic partial-entry fixtures
are explicitly conservative mechanics tests, not provider evidence. Stop/target ambiguity
uses stop first; adverse stop gaps use the worse open; target gaps receive no favorable bonus.

Initial cash 10,000 USDT per isolated instrument trial, seed 1229, at most seven configs,
64 trials/instrument including folds/baselines/stress, one preregistered study/instrument.
Select one config/family on validation net result (tie: smallest config hash), then freeze
selection before opening OOS. Every trial including losing variants remains recorded.
No tuning/selection after OOS; holdout scope cannot be freshly reopened by another study ID.

Report daily portfolio returns (365-day annualization, zero risk-free target), exact fees,
net expectancy, drawdown/duration/recovery, Sharpe/Sortino/Calmar, average R, win/loss,
turnover, exposure, tails and fixed UTC 8h session bins. Regimes use training-median low/high
volatility plus causal trend, not post-hoc winning periods. Moving/circular daily block
bootstrap: 2,000 resamples, 14-day blocks (>=7-day feature/2-day holding dependence), seed
1229; report 7/28-day sensitivity and Bonferroni-adjusted four family/asset comparisons.
Monte Carlo trade permutation is sensitivity only. Undefined statistics are null with reason.

Candidate screens remain >=100 closed OOS trades, >=6 OOS calendar months, >1 observed
regime, positive net expectancy and positive lower dependence-aware 95% interval (also
adjusted for comparisons), all cost stress surviving, stable preregistered neighbors,
drawdown <=20%. Otherwise INCONCLUSIVE/NO EDGE. No result becomes promotion eligible.
Rights/coverage failure blocks the affected empirical run rather than inventing data.
