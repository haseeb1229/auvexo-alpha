# Phase 6A1 proposed open-interest acceptance requirements

Status: ACCEPTED/FROZEN for Phase 6A1 source/feature-foundation engineering design at
887b6ac38636e07ff922d2ba2d0ec7b2063edd4f; independent GPT-5.6 Sol acceptance.
Implementation requires the owner-authorized verified PR #9 merge sequence; NO COLLECTION / ACTIVATION AUTHORITY. Date:2026-10-27.
See [ADR026](../adr/026-ds04-open-interest-intelligence.md), [rights](SOURCES_AND_RIGHTS.md),
[runbook](OPEN_INTEREST_RUNBOOK.md) and [preregistration](EXPERIMENT_PREREGISTRATION.md).
These are accepted/frozen engineering requirements, not executed test claims or collection authority.

| ID | Proposed invariant and future evidence |
| --- | --- |
| OI-01 | PRIVATE; separate Development clone; pinned9b9038b runtime/tasks/config/activation unchanged; no development calendar credit. |
| OI-02 | Exact DS04-A1 current OI, two symbols/USDⓈ-M, source/right version/hash/use/expiry; personal nonproduction only; expired/revoked/unknown/contrary rights block. |
| OI-03 | Only exact GET/fapi/v1/openInterest host/symbols; no arbitrary URL/query, redirect, auth/key/cookie/account/MCP/trade/testnet, alternate venue or third-party fields. |
| OI-04 | Finite deadlines/body/requests, one request at a time, bounded retry; 429/418/access restrictions stop/persist cooldown. Wrong host/redirect/timeout/oversize/content/JSON/redaction negatives. |
| OI-05 | Strict exact openInterest/symbol/time, Decimal not float; duplicate keys/extra/missing/nonfinite/negative/wrong scope/invalid time refuse; no silent field dropping. |
| OI-06 | Provider milliseconds distinct from first_seen/receipt/process/availability; causal admission; future/recycled/out-of-order/stale/clock errors refuse; retry cannot freshen facts. |
| OI-07 | Raw/normalized/parser/schema/doc/rights/code/manifest hashes; idempotent duplicate, immutable conflict/revision lineage, corruption refusal; spot consumers reject OI manifests. |
| OI-08 | Shared quota/immutable-publication architecture, private/local artifacts; no OI-as-Candle or active observation DB; no migration presumed. |
| OI-09 | Native units unspecified; no conversion/cross-symbol level/helper prices; fixed causal formulas, gap/zero/history/unit-drift/truncation negatives. |
| OI-10 | Fixed persistence/one clipped hourly-change predictor; no Phase3 outcome selection/consumed OOS reuse, fitted search, alternative thresholds or results before preregistration. |
| OI-11 | Identical paired future samples, >=30genuine days plus stronger sample gates; joint dependence-aware/multiplicity rules, null calendar days retained; insufficient/unstable evidence INCONCLUSIVE, no enablement. |
| OI-12 | ClockZERO until proposal acceptance, separate accepted implementation and owner START. No task/XML/setup/collector/receipt now; future single-instance no-catch-up/protected-window exclusion. |
| OI-13 | No broker/MT5/Exness/DS03/orders/money/permit issuer/runtime AI/macro/news, no Phase5 commissioning/candidate/champion. Binance live derivatives blocked; spendUSD0. |
| OI-14 | Later explicit implementation scope requires focused/property/network/causality/lineage/ledger/boundary and affected isolated PG, full inherited checks/audits/scans/exact-source clone/CI; no weakened tests. |
| OI-15 | Authorized docs/navigation only, frozen bytes unchanged, safe checks/founder identity/one OPEN-UNMERGED PR/PRIVATE proof/exactSHA/honest CI; independent review before code. |
| OI-16 | SOURCE/FEATURE PREDICTABILITY FOUNDATION only. PASS_RESEARCH_PREDICTABILITY proves no price alpha, trading/filter/promotion/safety value or canonical Phase 6 incremental-value exit; no operational OI, strategy/candidate promotion, module enablement or progression to macro/news/agents on OI-value grounds. Require a separate preregistered paired baseline-vs-OI augmented future/unconsumed, causally correct, cost/latency-aware where applicable, dependence-aware, no-retune incremental-value ablation under current rights/accepted dependencies first. No baseline selection from Phase 3 consumed OOS performance; both consumed holdouts permanently unavailable for selection/reuse. That study is neither designed nor authorized here. |

No future test above was run by this checkpoint. Phase2 seven genuine consecutive dates,
Phase4 >=14distinct genuine dates AND span>=14calendar days/replay/zero mismatch,
Phase5 commissioning and all Phase8/9 financial gates remain unchanged.
