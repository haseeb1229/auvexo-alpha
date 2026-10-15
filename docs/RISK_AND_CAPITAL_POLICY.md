# Risk and capital policy

Status: FROZEN authority/invariants. Live financial limits EXTERNAL; current permitted
real capital and live order count are both **zero**. Demo values below are PROVISIONAL
engineering test profiles, not personal investment advice or approved live limits.

Risk is a pure, typed decision over a validated intent, immutable policy, market snapshot,
instrument specification, reconciled account snapshot and outstanding reservations.
Output is DENIED(reason codes) or a narrowly bound RiskAuthorization. Missing, invalid,
non-finite, stale, conflicting or unpriceable inputs deny new exposure. Confidence never
increases a hard limit. Portfolio proposals and owner commands also pass the kernel.

## Required deterministic checks

1. Validate mode, account/server attestation, release/permit, venue/product policy and strategy state.
2. Check snapshot/quote/FX freshness, event/session gates, spread, available balance, margin
   and broker connectivity; unresolved orders or position mismatches deny new exposure.
3. Quantize price and size to current instrument steps using Decimal/integer units; round
   size down, then revalidate minimum lot, stop distances, commission and margin. Unknown
   contract multiplier, conversion rate, short/hedge semantics or unsupported fill mode denies.
4. Compute conservative stop loss plus fee/slippage/gap stress. Loss estimate for a linear
   product is quantity * multiplier * abs(entry-stop) * FX + costs, using adverse conversion.
   Nonlinear products require a separately validated loss model. Broker margin/profit estimates
   are cross-checks, never a substitute for policy. Stops do not guarantee capped loss.
5. Apply per-intent, per-asset, correlated bucket, gross/net exposure, aggregate open-risk,
   leverage/margin, daily-loss, drawdown and order-rate caps including pending orders/reservations.
6. Atomically reserve capacity under account lock. Concurrent candidates cannot spend the same
   capacity. Partial fills consume actual exposure and keep residual reservation until terminal
   reconciliation; UNKNOWN holds the full worst-case reservation. Reauthorize amendments.

Provisional demo fixture: per-trade modeled risk <=0.25% equity; aggregate stop risk <=1%;
BTC+ETH bucket <=0.5%; daily marked loss <=1%; high-water drawdown <=5%; <=3 simultaneous
positions; gross notional <=1x equity; margin utilization <=20%; <=5 new intents/minute.
The strictest cap wins; tiny demo balances/minimum lots may force NO TRADE. Baselines must
also be tested with lower limits, zero limits and currency rounding. Values live in a
versioned policy, never magic constants. No recovery sizing, martingale or loss-chasing.

Daily loss uses equity marked to executable prices including unrealized P&L, costs and
pending risk; day boundary is 00:00 UTC. Adjust equity/high-water accounting for deposits
and withdrawals without resetting loss history. Session-boundary, daylight-saving and
unavailable FX tests are mandatory. Withdrawal observation is allowed; initiation is not.

Live owner decisions at Phase 8: absolute capital allocation; absolute and percentage
loss caps; leverage/margin policy; gap tolerance; acceptable instruments/venues and any
financial/religious eligibility review. Missing values cannot inherit demo defaults.

## Non-negotiable invariants and kill levels

No money change without typed intent, deterministic authorization and durable audit intent.
No duplicate logical intent; no stale-data live opening; no unknown-account opening; no
blocked instrument; no real account in DEMO; no credential-only live activation; no
arbitrary LLM payload; no unbounded retries or silent failures. Broker facts are authoritative.

| Level | Trigger/effect | Recovery |
| --- | --- | --- |
| K0 normal | All readiness gates green; limits still apply | Continuous verification |
| K1 pause-new | Data stale, edge WATCH/REDUCE as configured, resource pressure or owner pause; deny new/increased exposure | Cause cleared and explicit recorded resume; no automatic loss-limit reset |
| K2 cancel-pending | Loss/drawdown cap or severe health degradation; cancel only identified pending exposure under authorization; retain broker protective orders | Reconcile orders/positions, investigate, owner approval |
| K3 controlled-flatten | Preapproved emergency rule or step-up owner command; typed position-bound reduce-only intents with current executable quote and known positions | Verify all fills/residuals, revoke permit, incident review |
| K4 lockdown | Suspected compromise, corrupted journal, account mismatch; revoke capabilities and isolate gateway | Manual broker supervision, credential rotation, restore/reconcile and fresh release |

Fail closed does not mean abandon open positions. Risk-reducing cancels/closes have a
separate deterministic action policy, not an unconditional bypass. Broad market-state
staleness may block opening while a fresh broker quote and known position permit a close.
Unknown broker state, missing durable journal, invalid identity or stale close quote blocks
automated money changes and escalates to the owner at the broker terminal. If shutdown or
isolation prevents automated exits, retain verified broker-side protection and disclose
residual risk. Cancel/close timeouts enter UNKNOWN and reconcile before any repeat.

Only an owner-authenticated activation may relax limits; agents can request investigation
or a pause. A system can tighten/suspend via preapproved deterministic rules. Edge-decay
rules cannot auto-resume suspended capital. See [recovery](OPERATIONS_AND_RECOVERY.md).
