# Requirements register

Phase 1 preserves all parent IDs below and refines implemented behavior through
[15 stable child acceptance IDs](phase1/ACCEPTANCE_TESTS.md), defined before implementation.
Actual code/test evidence is in [Phase 1 verification](phase1/VERIFICATION.md).

Status: FROZEN Phase 0 traceability baseline. Source: [archived brief](reference/PHASE_0_BRIEF.txt),
SHA-256 `1a3ffff5ed19d09ea48e80d4591ccaddfb09e9da64bde1ce3ce31fbd69b70fb2`.
The user requested completion of Phase 0; the brief supplies its scope and acceptance
criteria. Its suggested implementer name does not override the actual execution environment.

Priority P0 = safety/scope/architecture mandatory; P1 = required eventual capability;
P2 = optional extension. IDs are permanent and never renumbered. All rows are DESIGNED in
Phase 0, not implemented; future proof gates are listed. Document owner is the phase
implementer, independent acceptance owner is the reviewer; financial approval stays founder-only.

| ID / brief section | Priority | Requirement / acceptance evidence | Canonical document | Future proof gate |
| --- | --- | --- | --- | --- |
| R-000 / 0 | P0 | Authoritative blueprint and permanent rules; no money traded | [Handoff](PHASE_0_HANDOFF.md) | Phase 0 file/check/review evidence |
| R-001 / 1 | P0 | Private first Auvexo system, BTC/ETH/XAU, NO TRADE and no assumed profit | [Constitution](PRODUCT_CONSTITUTION.md) | Phase 3 baseline/edge verdict |
| R-002 / 2 | P0 | Agentic outside; typed deterministic risk/execution authority | [Risk](RISK_AND_CAPITAL_POLICY.md) | Phase 4 bypass negatives |
| R-003 / 3 | P0 | One shared production path, explicit seven modes, independent real gates | [Execution](EXECUTION_AND_VENUE_POLICY.md) | Phase 5 mode/account mismatch; Phase 8 permit |
| R-004 / 4 | P0 | Explicit venue/product policy, Binance derivatives blocked, no withdrawals | [Execution](EXECUTION_AND_VENUE_POLICY.md) | Phase 4 matrix negatives; Phase 8 eligibility |
| R-005 / 5 | P0 | Reproducible hypotheses/splits/leakage/costs/stress/baselines and full metrics | [Research](RESEARCH_AND_VALIDATION.md) | Phase 3 replay and OOS report |
| R-006 / 6 | P0 | Champion/challenger lifecycle, no agent live promotion | [Research](RESEARCH_AND_VALIDATION.md) | Phase 4 registry; Phase 8 release |
| R-007 / 7 | P0 | Rejected-candidate book, forward outcomes and filter ablations | [Research](RESEARCH_AND_VALIDATION.md) | Phase 3/6 paired portfolio replay |
| R-008 / 8 | P1 | NORMAL/WATCH/REDUCE/SUSPEND/INVESTIGATE decay, no silent self-edit | [Research](RESEARCH_AND_VALIDATION.md) | Phase 4/6 drift/false-alarm tests |
| R-009 / 9 | P1 | Role-by-role implementation, capabilities/budgets/evidence | [Agents](AGENT_ARCHITECTURE.md) | Phase 6 tool-permission and value ablation |
| R-010 / 10 | P0 | Ten event loops with deadlines, retries, state, verifier and escalation | [Agents](AGENT_ARCHITECTURE.md) | Phase 5/6 failure/timeout proof |
| R-011 / 11 | P1 | Prioritized crypto/gold/macro intelligence without early full universe | [Sources](DATA_SOURCE_REGISTER.md) | Phase 6 incremental-value report |
| R-012 / 12 | P0 | Trust, event times/hash/novelty/confirmation/dedup/expiry | [Data](DATA_ARCHITECTURE.md) | Phase 6 recycled/rumor/revision tests |
| R-013 / 13 | P0 | Sandboxed research browser, APIs first, no browser execution | [Agents](AGENT_ARCHITECTURE.md) | Phase 6 egress/permissions tests |
| R-014 / 14 | P0 | Point-in-time truth, separate revisions and decision lineage | [Data](DATA_ARCHITECTURE.md) | Phase 2/3 availability replay |
| R-015 / 15 | P0 | 16 GB laptop, bounded retention/quotas, no GPU requirement | [Data](DATA_ARCHITECTURE.md) | Phase 2 storage; Phase 5 stress |
| R-016 / 16 | P0 | Zero mandatory paid data/cloud/LLM; purchases prohibited now | [Constitution](PRODUCT_CONSTITUTION.md) | Phase 1/5 free local path |
| R-017 / 17 | P0 | Model-provider port, all-provider outage safe, no frontier training | [Agents](AGENT_ARCHITECTURE.md) | Phase 6 outage and schema tests |
| R-018 / 18 | P0 | Mature supported stack, evaluate alternatives, versions pinned in Phase 1 | [Architecture](ARCHITECTURE.md) | Phase 1 install/compatibility matrix |
| R-019 / 19 | P0 | Replaceable UI over typed contracts; no domain or broker coupling | [Architecture](ARCHITECTURE.md) | Phase 1 boundary and Phase 7 contract tests |
| R-020 / 20 | P1 | Small typed extension ports and separate Auvexo identities/APIs | [Architecture](ARCHITECTURE.md) | Phase 6 new adapter contract; later ecosystem gate |
| R-021 / 21 | P0 | Compare Python/EA/hybrid; broker truth; unknown never blind retry | [Execution](EXECUTION_AND_VENUE_POLICY.md) | Phase 5 actual terminal failure matrix |
| R-022 / 22 | P0 | Hard execution/risk invariants, kill levels and recovery | [Risk](RISK_AND_CAPITAL_POLICY.md) | Phase 4/5 adversarial gates |
| R-023 / 23 | P0 | Single-owner strong auth, step-up, secrets, least privilege and backup | [Security](SECURITY_BASELINE.md) | Phase 1/5 negatives; Phase 8 independent review |
| R-024 / 24 | P0 | Profiled budgets, bounded queues/research, no busy loops | [Performance](PERFORMANCE_AND_RELIABILITY.md) | Phase 5 measured concurrent load |
| R-025 / 25 | P0 | Strict quality/migrations/dependencies/errors/debt rules | [Engineering](engineering/ENGINEERING_RULES.md) | Phase 1 checks; every future handoff |
| R-026 / 26 | P0 | Layered negative/adversarial tests and real-environment proofs | [Engineering](engineering/ENGINEERING_RULES.md) | Each roadmap test/proof gate |
| R-027 / 27 | P0 | Auditable decisions, health/metrics/logs/traces, no sensitive logs | [Performance](PERFORMANCE_AND_RELIABILITY.md) | Phase 5 incident reconstruction |
| R-028 / 28 | P1 | One backend for clients/voice; dangerous voice step-up | [Clients](CLIENT_AND_UX_DIRECTION.md) | Phase 7 replay/confirmation negatives |
| R-029 / 29 | P0 | Local/private/remote/live stages, no fragile-tier safety dependency | [Operations](OPERATIONS_AND_RECOVERY.md) | Phase 8 uptime/restore drill |
| R-030 / 30 | P0 | New repo, inspect mature projects, licenses/notices, no root fork/copies | [Reuse](OPEN_SOURCE_REUSE_REVIEW.md) | Phase 0 review; adoption-time scan |
| R-031 / 31 | P0 | Private founder-owned repo/identity, clean commits, no AI trailers | [Handoff](PHASE_0_HANDOFF.md) | Phase 0 Git metadata and remote verification |
| R-032 / 32 | P0 | Aligned concise AGENTS/CLAUDE plus canonical engineering rules | [Engineering](engineering/ENGINEERING_RULES.md) | Phase 0 byte equality check |
| R-033 / 33 | P0 | All canonical docs, stable IDs, explicit decision statuses | [Index](README.md) | Phase 0 completeness/link check |
| R-034 / 34 | P1 | Professional accessible dark-first terminal direction, no Phase 0 UI | [Clients](CLIENT_AND_UX_DIRECTION.md) | Phase 7 accessibility/contract proof |
| R-035 / 35 | P0 | Practical phases each with scope/deps/output/test/proof/exit/recovery | [Roadmap](ROADMAP.md) | Independent gate at every phase |
| R-036 / 36 | P0 | Documentation-only phase; no trades/code/models/purchases/future phase | [Constitution](PRODUCT_CONSTITUTION.md) | Phase 0 file/action audit |
| R-037 / 37 | P0 | Main baseline, required branch, checks/commit/push, no merge | [Handoff](PHASE_0_HANDOFF.md) | Remote refs and clean local status |
| R-038 / 38 | P0 | Internal consistency review and every deferral has decision point | [Review](PHASE_0_SELF_REVIEW.md) | Findings resolved and gate register |
| R-039 / 39 | P0 | Full honest handoff and exact Phase 1 prerequisites | [Handoff](PHASE_0_HANDOFF.md) | Independent review of exact final commit |

Safety acceptance details (permanent subrequirements of R-022):

| ID | Invariant | Required negative proof |
| --- | --- | --- |
| R-022-A | Valid immutable intent + bound risk authorization + durable audit before send | Missing/altered/expired authorization denied |
| R-022-B | Atomic capacity and logical deduplication | Two concurrent individually valid intents exceed aggregate cap; only admissible reservation succeeds |
| R-022-C | Unknown broker/account or stale quote denies opening | Accepted-but-response-lost crash, history lag and stale data; no blind resend |
| R-022-D | Mode/account/venue/permit agreement | DEMO with real credentials, blocked derivatives, wrong server/hash/revoked permit all denied |
| R-022-E | Typed risk-reducing action retains safeguards | Cancel/fill race, over-close/reverse and stale-position close rejected |
| R-022-F | No agent/GUI/voice arbitrary order or withdrawal | Malicious tool payload/direct endpoint/voice replay lacks capability |
| R-022-G | Failure observable, bounded and fail-closed | DB/disk/provider/terminal failure produces explicit status and safe readiness |

Acceptance scope: a Phase 0 row passes when a coherent design and future proof are
documented. It does not imply an implemented safety test passed. Requirements are only
retired by explicit recorded owner/reviewer decision; priority does not authorize omission.

Phase 2 refines the same parents through [stable child requirements](phase2/ACCEPTANCE_TESTS.md).
No original ID or Phase 1 acceptance assertion is retired.

## Baseline correction impact (2026-10-17; independently accepted at bdae1a1)

The parent rows preserve original Phase 0 traceability, not current implementation status.
[ADR-013](adr/013-source-specific-acceptance.md) supersedes the all-or-nothing sequencing
interpretation after independent acceptance; phase numbers, IDs and financial thresholds stay.

| Stable child ID | Requirement / impact | Proof / disposition |
| --- | --- | --- |
| R-035-BA-01 | Separate reviewed source-specific engineering/research admission from full operational/activation acceptance; Phase 2 A/B/C explicit; later non-money overlap requires accepted dependencies and a new prompt | [Roadmap](ROADMAP.md), ADR-013; independent exact-head review accepted at bdae1a1; source-specific scope in acceptance record |
| R-014-BA-01 | Future typed data-use classification in experiment/release manifests; source/product/instrument/range rights propagate; Vision is nonproduction; DS-03/XAU claims blocked | [Research](RESEARCH_AND_VALIDATION.md); positive/negative tests required when implemented in Phase 3 |
| R-014-BA-02 | Future opt-in price close + positive causal lag simulation policy, actual 2026 receipt retained, no same-close lookahead or macro/news/on-chain inheritance | [Data](DATA_ARCHITECTURE.md); Phase 3 manifest/leakage proofs; no simulator now |
| R-015-BA-01 | Multi-year 1m audit-first Parquet benchmark before any measured derived optimization; exact canonical hash/fixed-point parity, no conflicting truth/history cap | Data/performance requirements; Phase 3 benchmark and future parity tests |
| R-018-BA-01 | Explicit current tested-lock maturity exception, no auto-upgrade; financial-critical adoption review | [Maturity review](amendments/DEPENDENCY_MATURITY.md); lock/pins unchanged; next adoption or 2026-11-16 |
| R-031-BA-01 | Temporary public exception only; no private broker/session/owner data; before broker/proprietary alpha resolve PRIVATE return or independently reviewed owner-approved permanent-public ADR | [Security](SECURITY_BASELINE.md); review 2026-10-24, no settings change |
| R-029-BA-01 | Before Phase 8, release integrity/CI-bound reviewed manifest/tag, current legal/data-use eligibility, external tax/statement/records responsibility, encrypted off-device recovery and owner-response/uptime proof | [Operations](OPERATIONS_AND_RECOVERY.md); EXTERNAL/reviewer gates remain open |

R-027-P2-01 / R-035-P2-01 retain all observation thresholds with the owner-approved new
22:57 warm-up / 23:00-23:12 Pakistan window (17:57 / 18:00-18:12 UTC), first eligible
October 18, 2026. R-031-P2-01 now explicitly records the temporary public exception rather
than falsely requiring a currently private PR. R-005/006/030 gain the first Phase 3 prompt's
correctness/reference/rights requirements; R-023/029 retain hard source/security/live gates.
R-036 remains the historical Phase 0 scope, not a ban on later explicitly authorized work.
No parent/Phase 1 child requirement or financial numerical target is removed.

Phase 3 refines the same parent IDs through [stable child requirements](phase3/ACCEPTANCE_TESTS.md),
under [ADR-014](adr/014-nonproduction-research.md). No Phase 1/2 safety proof is retired.

Phase 4 Checkpoint A refines existing parents through [frozen child requirements](phase4/ACCEPTANCE_TESTS.md) under [ADR-015](adr/015-paper-risk-core.md). No persistent observation or operational acceptance is inferred.

## Parallel offline engineering amendment (2026-10-20)

[ADR-024](adr/024-parallel-operational-release-and-engineering.md) and
[OF-01 through OF-12](phase5/OFFLINE_ACCEPTANCE.md) scope R-003/R-006/R-008/R-018/
R-021/R-022/R-023/R-024/R-029/R-031/R-035 for separate-clone synthetic execution foundations.
No original numeric/calendar/activation gate is relaxed. Actual Phase5 commissioning,
DS03/broker connection and money permission remain blocked; no Phase4 credit from tests.

## Read-only terminal foundation amendment (2026-10-20)

[ADR025](adr/025-read-only-private-operator-terminal.md) and [RO01-15](phase7/READ_ONLY_ACCEPTANCE.md)
refine existing R003/006/018/019/022/023/024/025/027/029/031/035 for separate-clone query-only
presentation. [Implementation checkpoint](phase7/READ_ONLY_IMPLEMENTATION.md) maps concrete
modules/tests and pending full verification. The explicit owner-approved data-free static shell
exception grants no API data access, financial authority or calendar credit. Original phases,
numeric/source/activation gates and all historical accepted evidence remain unchanged.
