# ADR-026: proposed DS-04-A1 open-interest intelligence

Status: PROPOSED — PENDING INDEPENDENT EXACT-SHA REVIEW.
NO IMPLEMENTATION / COLLECTION / ACTIVATION AUTHORITY.
Date: 2026-10-27.
Requirements: R-003, R-005, R-006, R-014, R-015, R-018, R-022, R-023, R-025, R-029, R-030, R-031, R-035; proposed OI-01 through OI-16.

## Context

This owner-authorized proposal starts from clean main94b7d66d3c7531a513759bab202a13bf3c2500b0
in the separate Development clone after authenticated PRIVATE verification2026-10-27.
Phase7 foundation is accepted/merged; full Phase7 remains OPEN. ADR013 permits scoped
non-money engineering beside incomplete calendar qualification. Canonical Phase6 order
is derivatives intelligence, official macro vintages, trusted news, then bounded agents.
The earlier broad DS04 RIGHTS_UNRESOLVED stop is preserved. New derivatives-specific
OI evidence is considered here; spot rights do not transfer. This is not self-acceptance.

## Decision

Propose only DS-04-A1: Binance RIE / Binance USDⓈ-M Futures current OI snapshots for
BTCUSDT/ETHUSDT via GET https://fapi.binance.com/fapi/v1/openInterest. The
[rights record](../phase6/SOURCES_AND_RIGHTS.md) separates provider statements from
project interpretation. Status is PROVISIONAL_SOURCE_SPECIFIC_RESEARCH_UNBLOCKING_CANDIDATE /
PENDING_INDEPENDENT_EXACT_SHA_ACCEPTANCE: personal noncommercial NONPRODUCTION only,
no redistribution or execution/live-promotion entitlement, raw/normalized artifacts
private/local. Necessary reproducibility retention is a conservative PROJECT interpretation,
not an express provider grant enumerating retention scenarios. Review due2026-11-27 or
earlier relevant change/revocation/uncertainty. Unknown/expired rights fail closed.

The [runbook](../phase6/OPEN_INTEREST_RUNBOOK.md) defines distinct provider/first-seen/
receipt/process/availability timestamps, raw/normalized hashes, schema/parser/code/source/
rights/manifest versions, immutable correction lineage and explicit gaps/staleness.
No future information, backdating, silent substitution/forward-fill or LLM source truth.
OI unit is PROVIDER_NATIVE_OI_UNSPECIFIED; no currency/contracts/notional conversion or
cross-symbol absolute-level comparison. Within-symbol changes require stable semantics.

Proposed transport is fixed GET-only/no credentials/cookies/redirects/proxy inheritance,
finite deadlines/budgets/retries/cooldown, one request at a time and safe typed failures.
Reuse Phase2 network/publication/quota/ledger PATTERNS. Existing PublicHTTP rejects this
host; SourceIdentity/Candle/manifest/store/research admission are spot-specific and do
NOT already support OI. Later reviewed contracts/discriminators/source policy must not
coerce OI to Candle or silently widen spot allowlists. No spot PRICE_CLOSE_PLUS_CAUSAL_LAG
assumption applies to observed OI. Generic SQL metadata may suffice: no migration need
is established. If proven necessary later, require MIGRATION_REQUIRED_PROPOSAL with
compatibility/isolated verification/forward recovery before code. Never use active Phase4 DB.

Initial deterministic family: native level/absolute hourly change and within-symbol
fractional hourly change only. No helper price/index/funding/basis, fitted scaler,
normalization/acceleration variants or feature zoo. The outcome-blind
[preregistration](../phase6/EXPERIMENT_PREREGISTRATION.md) fixes persistence versus one
clipped OI-change predictor, forecasting OI only. No consumed Phase3 OOS/data/results
are opened, compared or reused. Predictability does not demonstrate trading value.
The proposed48h warm-up/90day forward evaluation has sample, dependence and no-retune
gates, in addition to canonical>=30genuine days per material filter. No sample exists now.

PHASE6_FORWARD_CLOCK=ZERO until independent exact-SHA proposal acceptance, separate
owner implementation authority/accepted implementation, and explicit future collection
START. Proposal acceptance/CI/unit tests cannot start dates or task registration.
Future task design: single instance, exact code/config/source/rights hashes, limited
identity, no stored password/wake/power change/catch-up; exclude protected windows.
No XML/setup code now. CPU-only, one worker, spendUSD0, optional research pauses first.
Preserve Phase4 20:45-22:15 and Phase2 22:45-23:20 Asia/Karachi protection.

Phase2/4 full operational OPEN, current counts/span/replay UNKNOWN; Phase4 runtime stays
9b9038b6966843805c99f15e1c37cdba7c026679 with tasks/config/activation untouched.
Phase3 four INCONCLUSIVE, both OOS consumed, no candidate/champion. Phase5 offline
accepted; commissioning NOTSTARTED/clock0/DS03BLOCKED. Phase8/9 NOTSTARTED.
Binance live derivatives BLOCKED_BY_POLICY. No broker/MT5/Exness/session/order/money,
permit issuer, withdrawals/transfers, account/API key/OAuth/MCP/Agent Native/USER_DATA/
USER_STREAM/TRADE, testnet account, runtime AI, macro/news or later Phase6 scope.
No LLM-to-order path or new risk authority. Broader DS04 exclusions remain unresolved.

## Proposed OI-16: predictability foundation and separate value gate

OI-FWD-v1 is a SOURCE/FEATURE PREDICTABILITY FOUNDATION experiment only.
PASS_RESEARCH_PREDICTABILITY proves neither price alpha, trading value, filter value,
strategy promotion value, safety value nor the canonical Phase 6 incremental-value exit.
A PASS cannot enable OI in operational decision-making, promote a strategy/candidate,
satisfy Phase 6 module enablement or justify progression to macro/news/agents based on
OI's demonstrated value. The canonical incremental-value gate remains OPEN after a PASS.

Before any such claim, enablement or progression, require a SEPARATE preregistered,
paired baseline-vs-OI augmented incremental-value ablation on admissible future/unconsumed
evidence: causally correct, cost/latency aware where applicable, dependence-aware and
no-retune, under then-current source rights and accepted dependencies. Its baseline must
NOT be selected from Phase 3 consumed OOS performance. Both consumed Phase 3 OOS holdouts
remain permanently unavailable for selection/reuse. This correction does NOT design or
authorize that future value study; it adds no empirical thresholds for it. OI-FWD-v1's
existing forecasting protocol, sample, metrics and decision thresholds remain unchanged.

## Alternatives

Reject broad DS04 acceptance, OI history/CMC, funding/mark/index/basis, archives,
authenticated endpoints, outcome-selected baselines, a duplicate storage framework,
spot availability fiction and cross-product substitution. A fixed OI-only forecasting
surrogate is smaller and falsifiable; it grants no trading-value claim.

## Consequences

Only a PRIVATE documentation proposal and one OPEN/UNMERGED PR are delivered. Frozen
accepted bytes/code/tests/workflow/locks/dependencies/migrations stay unchanged. No
endpoint call/dataset/collector/task/receipt/clock is created. Rights/unit/clock and
statistical limitations remain residual risks. Drift disables future admission; retain
restricted evidence pending separately reviewed lawful retention/removal, never rewrite
provider facts. Rollback/disable affects optional research only, never operational ledgers.

## Validation

[Proposed requirements](../phase6/OPEN_INTEREST_ACCEPTANCE.md) define later adversarial,
causality/lineage/research evidence. Current checks are no-install docs/links/requirements/
high-signal scan, instruction equality, diff and path scope only in Development. No
Python tooling/local full suite/DB/provider/benchmark/install. Record exact PRIVATE CI
jobs/logs if triggered or explicit infrastructure limits; never change visibility/gates.

## Review point

Request GPT-5.6 Sol exact-SHA proposal review. Before executable work: accepted proposal/
rights, new owner brief, isolated environment/verification plan and unchanged financial
guards. Before START additionally require accepted implementation, current rights/retention/
product/unit/clock/security proof, reviewed task/config and explicit future owner START.
No later phase or financial authority follows from any single gate.
