# Project document index

[STATUS](STATUS.md) is the only document that states current status. Everything else is
either standing content, a runbook, or a dated record that describes the state on its
own date. Dated status text that used to head this and other files is preserved in the
[history log](history/README.md).

## Canonical documents

| Document | Authority and purpose |
| --- | --- |
| [Status](STATUS.md) | What is true now: phases, runtimes, evidence, obligations, owner gates |
| [Constitution](PRODUCT_CONSTITUTION.md) | Product boundaries and decision meanings |
| [Requirements](REQUIREMENTS_REGISTER.md) | Stable IDs and all 40 source sections |
| [Architecture](ARCHITECTURE.md) | Hierarchy, authority, runtimes, modules, contracts and stack |
| [Agent architecture](AGENT_ARCHITECTURE.md) | Roles, permissions, models and event loops |
| [Research and validation](RESEARCH_AND_VALIDATION.md) | Alpha proof, counterfactuals, promotion and decay |
| [Risk and capital](RISK_AND_CAPITAL_POLICY.md) | Kernel, invariants, loss and exposure policy, kill levels |
| [Execution and venues](EXECUTION_AND_VENUE_POLICY.md) | Modes, MT5 comparison, protocol and live interlocks |
| [Data architecture](DATA_ARCHITECTURE.md) | Point-in-time truth, event schema, retention and sizing |
| [Data source register](DATA_SOURCE_REGISTER.md) | Free-first sources, optional coverage and access gates |
| [Security](SECURITY_BASELINE.md) | Identity, secrets, threats and release protection |
| [Engineering rules](engineering/ENGINEERING_RULES.md) | Permanent coding and testing constraints |
| [Performance and reliability](PERFORMANCE_AND_RELIABILITY.md) | Resource and latency targets, observability |
| [Operations and recovery](OPERATIONS_AND_RECOVERY.md) | Startup, deployment, incidents, restore and rollback policy |
| [Client and UX direction](CLIENT_AND_UX_DIRECTION.md) | Terminal, mobile, desktop and voice boundaries |
| [Roadmap](ROADMAP.md) | Phases 0-9 and their proof and exit gates |
| [Decisions and gates](OPEN_DECISIONS.md) | Every open decision and external gate, with owner |
| [ADR index](adr/README.md) | Architecture decision records 001-031 |
| [Runbooks](runbooks/README.md) | How to verify, operate, recover and release |

Root [AGENTS.md](../AGENTS.md) and [CLAUDE.md](../CLAUDE.md) carry identical standing
rules for agents. The [documentation checker](../tools/check-docs.mjs) enforces structure,
links and the byte pins on frozen files.

## Independent reviews and acceptance records

Each record states what was reviewed, at which commit, and what it does not establish.

| Record | Scope |
| --- | --- |
| [Rebaseline audit, 2026-11-12](reviews/AUVEXO_FULL_A_TO_Z_REBASELINE_2026-11-12.md) | Independent A-to-Z audit of product, code, evidence and documents |
| [DS-03 actual adapter review](reviews/PHASE_2_DS03_ACTUAL_ADAPTER_INDEPENDENT_REVIEW.md) | PR #12 re-audit and corrections |
| [DS-03 synthetic acceptance](reviews/PHASE_2_DS03_SYNTHETIC_READONLY_INDEPENDENT_ACCEPTANCE.md) | Synthetic read-only connector |
| [Phase 7 read-only foundation](reviews/PHASE_7_READ_ONLY_FOUNDATION_INDEPENDENT_ACCEPTANCE.md) | Operator terminal |
| [Phase 6A1 implementation](reviews/PHASE_6A1_OI_IMPLEMENTATION_INDEPENDENT_ACCEPTANCE.md) and [proposal](reviews/PHASE_6A1_OI_PROPOSAL_INDEPENDENT_ACCEPTANCE.md) | Open-interest collector and study design |
| [Phase 5 offline foundation](reviews/PHASE_5_OFFLINE_FOUNDATION_INDEPENDENT_ACCEPTANCE.md) | Synthetic gateway and protocol |
| [Phase 4 Checkpoint B](reviews/PHASE_4_CHECKPOINT_B_INDEPENDENT_ACCEPTANCE.md) and [Checkpoint A](reviews/PHASE_4_CHECKPOINT_A_INDEPENDENT_ACCEPTANCE.md) | Observation harness; risk and PAPER core |
| [Phase 3](reviews/PHASE_3_INDEPENDENT_ACCEPTANCE.md) | Backtest correctness and research outcomes |
| [Phase 2 research acceptance](reviews/PHASE_2_RESEARCH_ACCEPTANCE.md) | Source-specific public spot data |
| [Phase 1](reviews/PHASE_1_INDEPENDENT_ACCEPTANCE.md) and [Phase 0](reviews/PHASE_0_INDEPENDENT_ACCEPTANCE.md) | Foundation; constitution and architecture |

## Phase records

These are dated. A status line inside one of them describes the day it was written.

| Phase | Requirements | Implementation and verification | Operating |
| --- | --- | --- | --- |
| 0 | [Brief](reference/PHASE_0_BRIEF.txt) | [Handoff](PHASE_0_HANDOFF.md), [self-review](PHASE_0_SELF_REVIEW.md), [checks](validation/PHASE_0_CHECKS.md), [open-source review](OPEN_SOURCE_REUSE_REVIEW.md) | [Handoff template](HANDOFF_TEMPLATE.md) |
| 1 | [Acceptance](phase1/ACCEPTANCE_TESTS.md) | [Implementation](phase1/IMPLEMENTATION.md), [verification](phase1/VERIFICATION.md), [handoff](phase1/HANDOFF.md) | [Setup](phase1/SETUP.md), [toolchain](phase1/TOOLCHAIN.md) |
| 2 public data | [Acceptance](phase2/ACCEPTANCE_TESTS.md), [rights](phase2/SOURCES_AND_RIGHTS.md) | [Implementation](phase2/IMPLEMENTATION.md), [coverage](phase2/QUALITY_AND_COVERAGE.md), [verification](phase2/VERIFICATION.md), [handoff](phase2/HANDOFF.md), [closure](phase2/closure/HANDOFF.md) | [Setup and recovery](phase2/SETUP_AND_RECOVERY.md), [schedule](amendments/SCHEDULER_2300.md) |
| 2 DS-03 synthetic | [Acceptance](phase2/DS03_ACCEPTANCE.md), [provider review](phase2/DS03_PROVIDER_REVIEW.md) | [Implementation](phase2/DS03_IMPLEMENTATION.md) | [Runbook](phase2/DS03_RUNBOOK.md) |
| 2 DS-03 actual adapter | [Requirements](phase2/DS03_ACTUAL_ADAPTER_REQUIREMENTS.md), [provider review](phase2/DS03_ACTUAL_ADAPTER_PROVIDER_REVIEW.md) | [Implementation](phase2/DS03_ACTUAL_ADAPTER_IMPLEMENTATION.md) | [Runbook](phase2/DS03_ACTUAL_ADAPTER_RUNBOOK.md) |
| 3 | [Acceptance](phase3/ACCEPTANCE_TESTS.md), [plan](phase3/DATA_PLAN.md), [plan V2](phase3/DATA_PLAN_V2.md) | [Implementation](phase3/IMPLEMENTATION.md), [verification](phase3/VERIFICATION.md), [handoff](phase3/HANDOFF.md) | |
| 4 | [Acceptance](phase4/ACCEPTANCE_TESTS.md), [observation acceptance](phase4/OBSERVATION_ACCEPTANCE.md) | [Design and review](phase4/DESIGN_AND_REVIEW.md), [observation implementation](phase4/OBSERVATION_IMPLEMENTATION.md), [handoff](phase4/HANDOFF.md) | [Setup and recovery](phase4/SETUP_AND_RECOVERY.md), [observation runbook](phase4/OBSERVATION_RUNBOOK.md) |
| 5 offline | [Acceptance](phase5/OFFLINE_ACCEPTANCE.md) | [Implementation](phase5/OFFLINE_IMPLEMENTATION.md) | [Runbook](phase5/OFFLINE_RUNBOOK.md) |
| 6 open interest | [Acceptance](phase6/OPEN_INTEREST_ACCEPTANCE.md), [rights](phase6/SOURCES_AND_RIGHTS.md), [preregistration](phase6/EXPERIMENT_PREREGISTRATION.md), [value ablation](phase6/VALUE_ABLATION_PREREGISTRATION.md) | [Implementation](phase6/OPEN_INTEREST_IMPLEMENTATION.md), [security remediation](phase6/ENGINEERING_SECURITY_REMEDIATION.md), [commissioning readiness](phase6/OI_COMMISSIONING_READINESS.md) | [Runbook](phase6/OPEN_INTEREST_RUNBOOK.md), [runtime deployment](phase6/OI_RUNTIME_DEPLOYMENT.md), [rights continuity](phase6/RIGHTS_REVIEW_CONTINUITY.md) |
| 7 read-only terminal | [Acceptance](phase7/READ_ONLY_ACCEPTANCE.md) | [Implementation](phase7/READ_ONLY_IMPLEMENTATION.md) | [Runbook](phase7/READ_ONLY_RUNBOOK.md) |

## Amendments, notices and archived briefs

- [Baseline correction handoff](amendments/BASELINE_CORRECTION_HANDOFF.md) and
  [dependency maturity exception](amendments/DEPENDENCY_MATURITY.md).
- Third-party notices for [Python dependencies](phase2/THIRD_PARTY_NOTICES.md) and the
  [operator terminal](../web/operator-terminal/THIRD_PARTY_NOTICES.md).
- Archived owner briefs are kept unchanged under `docs/reference/`, including the
  [Phase 1 brief](reference/PHASE_1_BRIEF.txt). They record what was asked at the time and
  carry no current authority.
