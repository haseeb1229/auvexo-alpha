# Project document index

Read the [Phase 1 handoff](phase1/HANDOFF.md), [setup](phase1/SETUP.md),
[implementation](phase1/IMPLEMENTATION.md), [toolchain](phase1/TOOLCHAIN.md) and
[verification](phase1/VERIFICATION.md), then constitution/requirements and policies.
Phase 0 documents remain the accepted design baseline; Phase 1 adds a disabled foundation.

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
| [ADR index](adr/README.md) | Original ten decisions plus Phase 1 ADR-011 |
| [Self-review](PHASE_0_SELF_REVIEW.md) | Consistency findings and resolutions |
| [Verification evidence](validation/PHASE_0_CHECKS.md) | Commands, results and limitations |
| [Handoff template](HANDOFF_TEMPLATE.md) | Required future phase delivery fields |
| [Archived brief](reference/PHASE_0_BRIEF.txt) | Original request scope, checksum in requirements |

Root [AGENTS.md](../AGENTS.md) and [CLAUDE.md](../CLAUDE.md) carry identical concise
instructions. [Documentation checker](../tools/check-docs.mjs) enforces structural checks
without installing application tooling. There are no package lockfiles because Phase 0
installs no runtime dependencies; exact supported versions are a Phase 1 deliverable.

## Phase 2 data engineering

[Acceptance](phase2/ACCEPTANCE_TESTS.md), [implementation](phase2/IMPLEMENTATION.md),
[rights](phase2/SOURCES_AND_RIGHTS.md), [coverage](phase2/QUALITY_AND_COVERAGE.md),
[setup/recovery](phase2/SETUP_AND_RECOVERY.md), [verification](phase2/VERIFICATION.md),
and [handoff](phase2/HANDOFF.md).
