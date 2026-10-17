# Roadmap and proof gates

Status: canonical phases 0-9 retained. [ADR-013](adr/013-source-specific-acceptance.md)
defines the superseding acceptance model independently accepted at exact `bdae1a1` by the
owner-supplied Phase 3 prompt; [acceptance record](reviews/PHASE_2_RESEARCH_ACCEPTANCE.md). Each phase still needs an authorized prompt and reviewer-accepted concrete dependencies.
A later row is not permission to start it. Financial gates and numeric evidence targets remain hard.

Current evidence: Phase 0 independently accepted and normally merged via PR #1 at
`eafec07ee7c7a98c9cca17b5f8665494bd650751`. Phase 1 independently accepted at
`295ded25afdd5a95ee0585b41da9966e45812bcf` and normally merged via PR #2 at
`16e63aeb9e7e1a97082d4a004142e0af163a4571`. Phase 2 data-only work is authorized by
the revised V2 brief; see [acceptance](reviews/PHASE_1_INDEPENDENT_ACCEPTANCE.md) and
[engineering snapshot](phase2/HANDOFF.md). The October 17
[evidence-closure handoff](phase2/closure/HANDOFF.md) records that delivery: retrospective seven-day
coverage passed; genuine scheduled days remain OPEN and Exness DEMO is blocked.
PUBLIC hosted CI has now run successfully; private allocation is not proven resolved.
The owner approved a temporary public-source exception, review due October 24 with
independent governance review still required. PR #3 remains unmerged; macro-exit is
not PASS. The owner-supplied Phase 3 prompt authorizes entry only after administrative recording
and a normal exact-head PR #3 merge; no Phase 3 implementation occurs in this status commit. The [baseline amendment](amendments/BASELINE_CORRECTION_HANDOFF.md)
is the dated amendment delivery package; historical snapshots retain their original facts.

## Two acceptance dispositions

**ENGINEERING / RESEARCH-UNBLOCKING ACCEPTANCE** permits only later NON-MONEY engineering
whose concrete source/instrument/product/range, rights, versions, availability policy and contracts
are independently accepted at an exact SHA. A reviewer must record the admitted scope, evidence,
excluded sources/ranges, still-open operational gates and permitted next work. A new owner phase
prompt is required. This is not full phase closure, promotion or account activation.

**FULL OPERATIONAL / ACTIVATION ACCEPTANCE** requires every applicable original real-environment,
calendar/source/security/rights/promotion gate. An engineering pass cannot satisfy it. Evidence
must name each gate and scope; unknown eligibility denies promotion. No cross-source inference.

Independently accepted Phase 2 source-specific disposition (full operational status OPEN):

| Concern | Current evidence | Acceptance consequence |
| --- | --- | --- |
| A: historical/public engineering and replay | Strong DS-01/02 selected BTC/ETH spot evidence; gaps/rights/receipt limits retained | Research-unblocking PASS for complete, rights-valid, hash-verified, lineage-preserved DS-01/02 BTC/ETH SPOT inputs only; not sufficient for every experiment |
| B: scheduled reliability | OPEN; zero qualified dates; new daily 22:57 warm-up, 23:00-23:12 Pakistan / 17:57, 18:00-18:12 UTC | Seven actual consecutive dates still required for full operational status; archives/pilots cannot substitute |
| C: Exness DEMO read-only DS-03 | BLOCKED; broker symbols/specs/history/attestation UNKNOWN | All Exness-dependent BTC/ETH/XAU research unavailable until source-specific qualification and secure authorized onboarding |

After independent acceptance of this model, B/C may continue while explicitly authorized
Phase 3 engineering uses accepted public spot inputs. Full Phase 2 operational status stays OPEN.
Binance spot results never qualify Exness CFDs, XAU, an execution feed or production data rights.
See the [current schedule](amendments/SCHEDULER_2300.md); the old morning receipt is historical.

The same dependency rule permits Phase 4 >=14-day paper observation alongside unrelated later
UI/research engineering, and Phase 5 >=30 days / >=20 sessions / >=100 DEMO lifecycle observations
alongside non-money Phase 6/7 engineering on already accepted inputs/contracts. Each overlap needs
an explicit scoped prompt and independent dependency review. It cannot enable incomplete filters,
strategy promotion, DEMO commissioning or live activation. Preserve Phase 6 >=30 days per new
material filter and Phase 9 >=90 days with adequate sample; none is shortened by engineering progress.

## Phase 0 — constitution and architecture freeze

- Purpose/scope: canonical requirements, design, policies, reuse research and repository baseline.
- Non-scope: runtime code, UI, account connection, trades and purchases.
- Dependencies: supplied brief, founder Git identity and GitHub access where available.
- Outputs: documented baseline, ADRs, aligned agent instructions and exact handoff commits.
- Tests/security: documentation/link/traceability/scope checks, manual consistency/secret review.
- Real-environment proof: actual private repository and separate main/Phase 0 refs, push verification.
- Exit: internal PASS or PASS-WITH-OPEN-GATES, independent reviewer disposition on exact SHA,
  unresolved critical issues closed and explicit Phase 1 prompt. Satisfied by the supplied
  independent acceptance and authorized normal PR #1 merge during Phase 1 entry.
- Rollback/recovery: amend with new commits, preserve review history; no runtime state exists.

## Phase 1 — engineering foundation

- Purpose/scope: install supported pinned toolchain; modular boundaries, schemas, migrations,
  local auth/secret-store foundations, logging and test/CI commands. Execution stays disabled.
- Non-scope: strategy claims, feed integrations, trading connections or UI expansion.
- Dependencies: accepted Phase 0 and explicit prompt; resolve OD-01 version matrix.
- Outputs: minimal buildable repository, reproducible environment, lockfiles, SBOM, contract
  skeleton, configuration validation, no credential-bearing sample files.
- Tests/security: lint/type/unit, real PostgreSQL migration/rollback/restore, import-boundary,
  auth negatives, dependency and secret scans; lock CI action revisions when CI is added.
- Real-environment proof: clean installation and checks on Windows laptop; measured idle RAM;
  free local commands run without any paid entitlement. Capture tool versions and logs.
- Exit: reproducible build, quality checks pass, modes disabled by default, no secret exposure.
- Rollback/recovery: remove only isolated installation artifacts; restore test DB; preserve migrations.

## Phase 2 — trustworthy historical and live data

- Purpose/scope: P0 source contracts, Binance public data and Exness demo read-only data
  onboarding; instrument mapping, quality, timestamp/vintage store, Parquet manifests.
- Non-scope: orders, real-account credentials, full news/on-chain/depth universe.
- Dependencies: Phase 1; owner supplies demo authentication only when integration is ready.
- Outputs: bounded validated datasets/live observations, quality/coverage and terms register.
- Tests/security: gaps/duplicates/revisions/units/as-of joins, disk pressure, credential redaction;
  verify demo account type and absence of execution capability in collector.
- Real-environment proof: seven consecutive scheduled collection days, disconnect/backfill
  drill and measured storage rate; actual broker symbol/spec snapshot. Missing history blocks
  affected research claims, not all independent price research.
- Exit: reproducible manifests, known gaps/limits, no fabricated history, quota/freshness controls.
- Rollback/recovery: quarantine bad dataset versions, retain prior manifest; no destructive overwrite.

## Phase 3 — backtest correctness and simple alpha

- Purpose/scope: common intent/accounting semantics in simulator, preregistered simple hypotheses,
  baselines, walk-forward/OOS, counterfactual book and cost stress.
- Non-scope: many agents, ML complexity, real or demo orders, cosmetic terminal.
- Dependencies: independent source-specific engineering acceptance under ADR-013, qualified
  Phase 2 dataset ranges/rights/availability and Phase 1 schemas, then a new scoped prompt.
  Full Phase 2 B/C remains OPEN while admissible engineering proceeds; DS-03-dependent work stays blocked.
- Outputs: correctness fixtures, reproducible experiment ledger and reports, honest edge verdict;
  typed data-use classification bound to source/rights lineage in every experiment/release manifest.
  Vision-derived results remain nonproduction research regardless of measured alpha.
- Tests/security: hand calculations, truncation/leakage, split/embargo, spread/slippage/partial
  execution simulation, reproducible seed, sandbox job/resource limits. Build correctness before
  alpha claims: deterministic event-driven simulator with shared intent/accounting semantics,
  hand-calculated fixtures and selected independent reference/mature-engine or calculation checks
  (no third-party root fork). Include chronological splits, purge/embargo, walk-forward/OOS,
  full trial ledger, spread/commission/swap/funding/slippage/latency and intrabar ambiguity.
  First prompt must specify the opt-in price-close-plus-causal-lag simulation policy, actual
  receipt retention, no same-close lookahead, no macro/news/on-chain vintage inheritance and
  manifest assumptions; benchmark multi-year 1m audit-first Parquet before optimizing.
  [Research](RESEARCH_AND_VALIDATION.md) and [data](DATA_ARCHITECTURE.md) define the design gates.
- Real-environment proof: rerun from archived real-source datasets on laptop; measured resource
  envelope. Synthetic fixtures are explicitly labeled tests, never live evidence.
- Exit: correctness passes and preregistered hypotheses assessed. NO EDGE is valid; it prevents
  capital promotion. Operational development may continue only under an explicit next prompt.
- Rollback/recovery: invalidate affected experiment lineage and downstream candidates on bug fixes.

## Phase 4 — strategy lifecycle and hard risk

- Purpose/scope: champion/challenger registry, regime baselines, deterministic risk, reservations,
  environment/policy gates and paper execution using common contracts.
- Non-scope: broker orders, auto-promotion, production self-modification.
- Dependencies: Phase 3 correctness; financial demo fixtures are versioned test policy.
- Outputs: risk kernel, durable intent/outbox/reconciliation simulator and edge monitor baseline.
- Tests/security: concurrent exposure races, decimal/FX/contract units, negative limits, policy
  revocation, mode/credential mismatches, unknown fills, writer fencing and adversarial auth.
- Real-environment proof: >=14 calendar days of paper operation on actual feeds, all candidates
  journaled, replay reproduces decisions; zero unexplained ledger mismatches.
- Exit: every hard invariant has a positive and adversarial test; data/LLM outage fail safely.
- Rollback/recovery: pause paper registry, restore code/config while retaining journal and trial history.

## Phase 5 — Exness demo and sustained shadow qualification

- Purpose/scope: Python MT5 gateway, contract/reconciliation tests and controlled demo orders;
  measure Python transport against requirements, add EA only if evidence demands it. Minimal
  health/kill controls are allowed as operational tools, not a rich UI project.
- Non-scope: real credentials/capital, Binance live execution, unrestricted agent actions.
- Dependencies: Phase 4; demo account/specs/terms confirmed, explicit Phase 5 authorization.
- Commissioning preflight: pass offline risk/gateway/auth/unknown-state negatives, attest demo
  identity and approve a bounded demo-only qualification permit before the first demo order.
  This is separate from the sustained-demo exit gate, whose evidence requires actual orders.
- Outputs: actual demo fill/cancel/partial-or-simulated-partial evidence (label which), journal,
  shadow comparison and signed qualification report; protection and restart runbooks.
- Tests/security: crash after send, duplicate delivery, real-account-in-DEMO refusal, reconnect,
  stop failure, cancel/fill race, unsupported fill mode and unknown outcomes; gateway auth/isolation.
- Real-environment proof: >=30 calendar days including >=20 active market sessions of sustained
  demo/shadow, >=100 demo order lifecycle observations (not an alpha sample guarantee), clean
  daily reconciliation, terminal/reboot/network drills and isolated backup restore. If broker
  cannot produce a partial fill, simulator/contract proof is labeled and residual gap reviewed.
- Exit: zero unresolved execution outcomes/mismatches, measured latency/resource budgets met,
  no duplicate logical orders, operational failure proofs accepted. Alpha validity remains separate.
- Rollback/recovery: pause-new, reconcile, cancel/flatten only authorized known exposure, disable
  gateway release; preserve broker facts and reservations across rollback.

## Phase 6 — incremental intelligence and bounded agents

- Purpose/scope: derivatives intelligence -> official macro schedules/vintages -> trusted news
  -> bounded agent investigation; optional richer data only after measurable ablations. Extend
  counterfactual/decay analysis. Each substep must show value before advancing its complexity.
- Non-scope: mandatory paid sources, foundation training, browser trading or policy bypass.
- Dependencies: Phase 3 baseline and accepted source/contracts for each experiment; Phase 5
  reliable desk for operational enablement. Independently scoped non-money engineering may
  overlap sustained DEMO qualification under the two dispositions above.
- Outputs: paired baseline/augmented experiments, cost/latency/coverage report, agent/tool manifests.
- Tests/security: injected malicious text, stale/recycled news, vintage leakage, tool denial,
  provider outages/budgets, unsupported conclusions and default USD 0 spend behavior.
- Real-environment proof: >=30 days forward observation per new material filter plus
  preregistered sufficient sample; insufficient evidence leaves module disabled. Compare
  operational safety with all LLM providers unavailable.
- Exit: enable only modules with demonstrated incremental value or explicit safety rationale;
  no new risk authority; no claim of complete event coverage.
- Rollback/recovery: disable optional module, retain evidence and revert to qualified baseline;
  mandatory-input strategies suspend until requalified.

## Phase 7 — professional client surfaces

- Purpose/scope: private web terminal and then justified desktop/Android/voice clients;
  secure owner flows, explanations and operational visibility. Optional full Binance account/
  paper adapter may be separately scoped here; live derivatives policy remains blocked.
- Non-scope: new alpha logic in UI, public signup or client-held broker keys.
- Dependencies: stable accepted typed API/contracts and useful research evidence; scoped non-money
  surfaces may precede completion of Phases 4/5 observations. DEMO-backed operational proof and
  activation flows still require their qualified dependencies and separately authorized phase scope.
- Outputs: accessible terminal, generated clients, signed packaging/secure storage plans.
- Tests/security: contract and accessibility checks, responsive/keyboard flows, auth/CSRF,
  stale state, disconnect/resume, action confirmation and voice replay negatives.
- Real-environment proof: founder can inspect why/no-trade, pause and recover through actual
  demo-backed clients; Android/desktop installed only under that phase's authorization.
- Exit: redesign leaves backend contract tests unchanged, no secret in bundle, dangerous actions
  require step-up. Rich clients can be omitted from live deployment if independent controls suffice.
- Rollback/recovery: roll back client version without changing broker state/API semantics.

## Phase 8 — live certification and tiny controlled capital

- Purpose/scope: independent risk/security/operations review, owner policy decisions and permit;
  then explicitly authorized LIVE_LIMITED Exness activation with tiny absolute capital cap.
- Non-scope: automatic launch because demo passed, Binance derivatives, scaling or guaranteed profit.
- Dependencies: all applicable prior safety/evidence gates, eligible validated champion, OD-04/05/06/07
  closed, current legal/jurisdiction/data-use eligibility and step-up owner activation.
  Protected main/release or equivalent reviewed control, CI-bound release manifest/tag and no
  unreviewed release; off-device encrypted recovery and owner-response/uptime proof are mandatory.
  Tax/statement/recordkeeping responsibility is an EXTERNAL owner/qualified-professional gate,
  not a software conclusion. No edge means no launch.
- Outputs: release evidence manifest, threat/incident review, approved numeric policy and signed permit.
- Tests/security: full adversarial regression, dependency audit, account attestation, tampered/expired
  permit refusal, kill/restore drill and independent credential permission verification.
- Real-environment proof: read-only real account verification only after explicit authorization,
  then separately authorized smallest feasible risk-bounded transactions; verify actual spread,
  slippage/fees/protection and immediate reconciliation. Demo metrics cannot substitute.
- Exit: no unresolved critical finding, restore/owner-response/uptime plans proven, observed
  live exposure within all approved limits; owner can revoke and independently supervise.
- Rollback/recovery: revoke permit, stop entries, safely reduce known exposure, reconcile and
  investigate; live losses never trigger automatic increases.

## Phase 9 — controlled scaling

- Purpose/scope: incremental owner-approved increases only after live evidence and capacity review.
- Non-scope: leverage/venue expansion by an agent, unreviewed assets, policy-blocked derivatives.
- Dependencies: Phase 8 plus >=90 days and preregistered adequate live sample; absence of incidents
  or loss is not proof of edge. Small samples extend observation.
- Outputs: new capped permits, correlation/impact/decay analysis and updated recovery capacity.
- Tests/security: rerun capital-sensitive invariants, stress liquidity/gaps/concentration,
  current dependency/permission audit and rollback rehearsal.
- Real-environment proof: each increment observed under independent loss/health monitoring;
  actual execution-cost drift and operational incidents reported.
- Exit: each increment separately approved on evidence; no blanket unlimited LIVE permission.
- Rollback/recovery: reduce to last qualified limits or suspend, retain journal, investigate decay.

Sequence rationale: risk contracts are designed now and shared with the Phase 3 simulator;
full risk implementation precedes any broker orders. Read-only demo data precedes execution
for claims about that intended product; it need not block independently qualified spot research.
Correctness precedes alpha claims. Useful accepted contracts allow unrelated non-money engineering
to overlap observation without granting activation. Safety monitoring is never deferred for UI work.
