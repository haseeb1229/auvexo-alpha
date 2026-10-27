# OI-FWD-v1 proposed paired forward experiment preregistration

Status: PROPOSED — PENDING INDEPENDENT EXACT-SHA REVIEW.
NO IMPLEMENTATION / COLLECTION / ACTIVATION AUTHORITY. Date:2026-10-27.
Protocol oi-fwd.v1, seed1229: one study, two symbols, two fixed models.
See [rights](SOURCES_AND_RIGHTS.md), [runbook](OPEN_INTEREST_RUNBOOK.md) and
[acceptance](OPEN_INTEREST_ACCEPTANCE.md). Bind the accepted document hash and later
code/parser/rights/task versions before collection or any result inspection.

## Hypothesis, baseline and outcome

Hypothesis: a fixed causal hourly OI-change predictor improves next-slot fractional-OI
absolute forecast error over persistence for BOTH BTCUSDT and ETHUSDT. This tests OI
predictability only: no price-alpha, trading-value, profitability or execution claim.
Only DS-04-A1 current USDⓈ-M OI snapshots. No price/funding/index/basis/trade/account/
third-party input, target or helper. Score symbols separately under stable native units.

Let Q[h] be the originally admitted positive OI snapshot for hourly UTC slot h.
Baseline B[h]=0 predicts next-slot fractional change, equivalent to persistence of level.
Augmented A[h]=clip((Q[h]-Q[h-1])/Q[h-1],-0.05,+0.05).
Outcome Y[h]=(Q[h+1]-Q[h])/Q[h], available only after the next slot is actually observed.
The outcome is never a feature. Nominal next-hour slot prediction does not assert exactly
60minutes between provider observations; retain actual provider/receipt gaps. Freeze
prediction after h's processing within its first60seconds and before h+1; never recalculate
it using later corrections or evidence unavailable at that prediction instant.

Selection rationale is pre-result: a generic persistence null and one fixed clipped
first-difference extrapolation. No comparison/selection of Phase3 families, configurations
or empirical outcomes. Neither consumed OOS holdout is opened, rerun, ranked or reused.
No parameter/horizon/grid/model search. Both models have zero fitted parameters, so no
training/selection partition is required. Unit level/absolute change are audit diagnostics;
only the fixed fractional change enters A[h]. No auxiliary feature variants.

## Future window and admission

PHASE6_FORWARD_CLOCK=ZERO. Only after proposal acceptance, separately accepted executable
implementation and explicit owner START fix T0 as the first UTC midnight strictly after
START. T0 must be future/unconsumed, no pre-START import credit. First48hours are causal
warm-up only. EvalStart=T0+48hours; EvalEnd=EvalStart+90calendar days,
with confirmation interval [EvalStart,EvalEnd). Require h>=EvalStart and both h and
h+1 slots strictly before EvalEnd for scoring; no target acquisition extends the window.
Retain an otherwise created terminal forecast as unscored. No favourable early stop,
optional extension, retrospective replacement window or new-study-ID evaluation reuse.
Current rights must cover the whole window; separate renewals are required, not presumed.
Rights interruptions leave gaps and no catch-up. No actual date is created by this design.

Preschedule hourly snapshots outside protected windows.
Schedule eligibility of h-1,h,h+1 is fixed BEFORE prediction from the protected-window
calendar alone. At h, create and retain an immutable prediction whenever INPUT slots
h-1 and h pass the admission rules below; do not condition forecast creation on whether
the future h+1 response will arrive. Retain this prediction and a missing-outcome flag
if its target later fails. Only when h+1 arrives can paired SCORING eligibility be known.
For scoring, each input and target must originally be received AND processed in its
slot's first60seconds; nonfuture provider time; provider age=received_at minus provider_time in [0,120seconds], including target; exact source/
product/symbol/hash/parser/current rights and positive finite OI; trusted local UTC.
No duplicate provider fact/recycled/out-of-order/future data or ambiguous unit/version drift.
Repeated equal
VALUE with a distinct current provider time is not itself a gap; identical provider-time/
content cannot qualify a later slot. Keep every gap/exclusion and original timestamps.
No interpolation, forward-fill, another venue or row-count history bridging.

Protected windows exclude UTC16:00,17:00,18:00 acquisition slots. Requiring all three
adjacent slots excludes prediction centers15:00-19:00UTC, leaving at most19/day.
These intentional missing hours do not prove continuous uptime. Adjacent hourly labels
are nonoverlapping in nominal time; serial/cross-symbol dependence still matters.
Unit stability is an explicit assumption; never infer contracts/base/notional conversion.
Unit/product ambiguity stops affected interpretation for independent review, no rescaling.

## Sample, metrics and latency

A joint-valid UTC evaluation day has >=16eligible pairs for EACH symbol. Retain all90
calendar labels in sequence; invalid days are null, never compressed away. Require
>=80joint-valid days AND >=1500eligible pairs per symbol within joint-valid days, plus
canonical>=30genuine forward days and every rights/quality gate. These are independent:
80times16 is insufficient. Shortfall is INCONCLUSIVE, never a lower sample target.

Paired loss difference D[h]=abs(Y[h]-B[h])-abs(Y[h]-A[h]); positive favors augmentation.
For each symbol compute each joint-valid day's mean D, then equally average valid
daily means. These are the two co-primary effects, in fractional-OI units. Do not pool
absolute BTC/ETH values or overweight higher-count days. Secondary descriptive only:
per-model MAE/RMSE/bias, coverage/outages/lag/clipping. No alternative success metric.
No trades exist, so no PnL/commission/slippage/funding-cost model or trading-cost claim.
Retain actual request/processing delay and refuse late/unavailable information rather
than assume instantaneous data. Default paid spendUSD0; no paid source/model.

## Dependence, multiplicity and decision

Aligned moving-block bootstrap:90UTCday vectors, symbols sampled jointly, null days
retained. Primary block L=14days,5000resamples,seed1229. Sample starts uniformly from
0..(90-L); concatenate complete blocks until>=90labels, truncate to90. No circular
bridging of study end. Resampled statistic is the equal-weight mean of nonnull daily
means. Use the same draws for both symbols; never drop an adverse draw. If any required
statistic cannot be calculated, INCONCLUSIVE rather than choosing favourable draws.

Sort5000resampled effects per symbol. Zero-based lower index floor(0.025*(5000-1));
upper index ceil(0.975*(5000-1)), no interpolation. Two one-sided comparisons use
nominal Bonferroni per-symbol97.5% lower bounds/familywise5%. Dependence/bootstrap
adequacy is an assumption, not guaranteed finite-sample error control. Repeat the same
mechanics at L=7and28 as sensitivity; they cannot replace a failed primary L=14 result.

- PASS_RESEARCH_PREDICTABILITY: all gates pass, BOTH primary lower bounds strictly
  exceed0.0001 (one basis point of fractional OI), and BOTH7/28day sensitivity lower
  bounds are strictly positive. No operational enablement follows.
- NO_VALUE: sufficient valid evidence and either primary upper bound<=0.
- INCONCLUSIVE: every other case, including inadequate sample, unstable sensitivity,
  clock/rights/quality gaps preventing gates or uncertain statistical support.
- Material security/correctness/source-identity failure: STOPPED_REVIEW_REQUIRED,
  not a fabricated empirical verdict or authority to fix data.

No thresholds/windows/models/metrics/horizons change after inspection. Pre-START
amendments require a newly reviewed hash. After evaluation inspection any new study
requires genuinely future unconsumed data and preserves earlier trials/consumption.
No renaming studies to reuse holdouts. Safety monitoring may stop collection but never
earns replacement dates or selects a better confirmation window. No favourable interim
primary-result inspection to decide stopping/extension.

## Limitations and later gates

Even90days/1500pairs may lack regimes/effective independent sample; independent review
must accept adequacy before START and assess limits before any claim. This surrogate
cannot establish incremental trading value or original strategy promotion criteria.
Later value ablation/source/security/operational/financial gates remain separate.
Failed/inconclusive evidence leaves the module DISABLED. No broader DS04 expansion,
candidate/champion, commissioning, broker/money/runtime AI or rights upgrade follows.
