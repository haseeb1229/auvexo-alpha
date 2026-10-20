# Project document index

Phase 4 Checkpoint A engineering is independently ACCEPTED/PASS at
`e3f39e0397e1846c37febcebc246ea91c9f2eb78` by GPT-5.6 Sol. See the
[acceptance record](reviews/PHASE_4_CHECKPOINT_A_INDEPENDENT_ACCEPTANCE.md) and
[current handoff](phase4/HANDOFF.md). ADR-015 through ADR-022 are ACCEPTED/FROZEN
for this engineering scope. ADR-022 retains the 272.4386 ms concurrent stress tail
as THROTTLE_REQUIRED evidence; no benchmark rerun is authorized.

Full canonical Phase 4 remains OPEN pending >=14 actual-feed PAPER calendar days,
replay evidence and zero unexplained ledger mismatches. Observation has NOT started;
its counter remains zero. PR #5 merged normally at dbe3cd6f47bf5a48c044df2f36cba5ea7081ca09
after exact-head administrative CI. Checkpoint B engineering is independently
ACCEPTED/PASS at `527bd23ce434fee557f6f1414bf5b43d7c3c3f21`; see its
[acceptance record](reviews/PHASE_4_CHECKPOINT_B_INDEPENDENT_ACCEPTANCE.md).
ADR-023 and its requirements/runbook are ACCEPTED/FROZEN with unchanged original bytes.
Docs-only PR #6 acceptance, exact-head admin CI and verified normal merge authorize
local PREPARATION only under the [pre-start brief](reference/PHASE_4_CHECKPOINT_B_PRESTART_BRIEF.txt)
and frozen
[ADR-023](adr/023-paper-observation-qualification.md),
[requirements](phase4/OBSERVATION_ACCEPTANCE.md) and
[runbook](phase4/OBSERVATION_RUNBOOK.md). No persistent task
registration/START, Phase 5, broker or money authority follows from this acceptance.

Checkpoint B's [implementation map](phase4/OBSERVATION_IMPLEMENTATION.md) links the
source/clock/fixture, persistent ledger, task-definition and recovery boundaries.

Phase 2 B/C remains OPEN: October 18/19 INCOMPLETE, genuine qualified scheduled dates
zero, DS-03/Exness blocked. Phase 3 remains independently accepted at bb692208 with
four INCONCLUSIVE outcomes, both OOS holdouts consumed and no candidate/champion.
PUBLIC exception review remains due 2026-10-24; repository settings are unchanged.
Earlier dated wording below describes historical entry/acceptance transitions.

Read the [current baseline correction handoff](amendments/BASELINE_CORRECTION_HANDOFF.md),
[ADR-013](adr/013-source-specific-acceptance.md), [current schedule](amendments/SCHEDULER_2300.md),
constitution/requirements and policies. Phases 0/1 are independently accepted; Phase 2
engineering has independently accepted DS-01/02 BTC/ETH SPOT research-unblocking scope;
operational/source gates remain OPEN. See [acceptance](reviews/PHASE_2_RESEARCH_ACCEPTANCE.md).
Phase 3 implementation follows the authorized normal merge/new branch, not this status commit. Dated handoffs and receipts remain historical snapshots.

| Document | Authority/purpose |
| --- | --- |
| [Phase 0 handoff](PHASE_0_HANDOFF.md) | Delivery, evidence, repository state and next gate |
| [Constitution](PRODUCT_CONSTITUTION.md) | Product boundaries and decision meanings |
| [Requirements](REQUIREMENTS_REGISTER.md) | Stable IDs and all 40 source sections |
| [Architecture](ARCHITECTURE.md) | Modules, contracts, stack and extension boundaries |
| [Agent architecture](AGENT_ARCHITECTURE.md) | Roles, permissions, models and event loops |
| [Research and validation](RESEARCH_AND_VALIDATION.md) | Alpha proof, counterfactuals, promotion and decay |
| [Risk and capital](RISK_AND_CAPITAL_POLICY.md) | Kernel, invariants, loss/exposure policy and kill levels |
| [Execution and venues](EXECUTION_AND_VENUE_POLICY.md) | Modes, MT5 comparison, protocol and live interlocks |
| [Data architecture](DATA_ARCHITECTURE.md) | Point-in-time truth, event schema, retention and sizing |
| [Data source register](DATA_SOURCE_REGISTER.md) | Free-first sources, optional coverage and access gates |
| [Security](SECURITY_BASELINE.md) | Identity, secrets, threats and release protection |
| [Engineering rules](engineering/ENGINEERING_RULES.md) | Permanent coding and testing constraints |
| [Performance and reliability](PERFORMANCE_AND_RELIABILITY.md) | Resource/latency targets and observability |
| [Operations and recovery](OPERATIONS_AND_RECOVERY.md) | Startup, deployment, incidents, restore and rollback |
| [Open-source review](OPEN_SOURCE_REUSE_REVIEW.md) | Inspected upstream evidence and reuse dispositions |
| [Client and UX direction](CLIENT_AND_UX_DIRECTION.md) | Future terminal, mobile, desktop and voice boundaries |
| [Roadmap](ROADMAP.md) | Phases 0-9 and explicit proof/exit gates |
| [Open decisions](OPEN_DECISIONS.md) | Status, owner and closure point for every open gate |
| [ADR index](adr/README.md) | Decisions 001-023 with individual dates/statuses |
| [Self-review](PHASE_0_SELF_REVIEW.md) | Consistency findings and resolutions |
| [Verification evidence](validation/PHASE_0_CHECKS.md) | Commands, results and limitations |
| [Handoff template](HANDOFF_TEMPLATE.md) | Required future phase delivery fields |
| [Archived brief](reference/PHASE_0_BRIEF.txt) | Original request scope, checksum in requirements |

Root [AGENTS.md](../AGENTS.md) and [CLAUDE.md](../CLAUDE.md) carry identical concise
instructions. [Documentation checker](../tools/check-docs.mjs) enforces structural checks
without installing application tooling. The current `uv.lock` pins the tested Phase 1/2
environment; see the [maturity exception](amendments/DEPENDENCY_MATURITY.md).

## Phase 2 data engineering

[Acceptance](phase2/ACCEPTANCE_TESTS.md), [implementation](phase2/IMPLEMENTATION.md),
[rights](phase2/SOURCES_AND_RIGHTS.md), [coverage](phase2/QUALITY_AND_COVERAGE.md),
[setup/recovery](phase2/SETUP_AND_RECOVERY.md), [verification](phase2/VERIFICATION.md),
and [handoff](phase2/HANDOFF.md).

The dated October 17 [evidence-closure handoff](phase2/closure/HANDOFF.md) supersedes
earlier status snapshots for that delivery, preserving their original receipts. The
baseline amendment above now provides current navigation. Closure records the originally
approved [daily task](phase2/closure/SCHEDULER_PROPOSAL.md), temporary
[public-source exception](phase2/closure/PUBLIC_VISIBILITY_PROPOSAL.md), actual
retrospective coverage and remaining exit gates. It is not Phase 2 acceptance.
