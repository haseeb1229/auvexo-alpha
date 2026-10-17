# Auvexo Alpha

Personal alpha research and trading-system project owned by haseeb1229. Private-first
baseline; source is temporarily PUBLIC under an owner-approved exception, review due
2026-10-24. Public history cannot be revoked by later returning to PRIVATE.

Phases 0/1 and source-specific Phase 2 research engineering are independently accepted.
PR #3 normally merged at `26b20ca5f0ef18e5300d5213b1cc8d2667bb71d3`; full Phase 2
operational status stays OPEN (scheduled days and DS-03 Exness qualification).
Current Phase 3 builds deterministic nonproduction spot research. No Phase 4 or broker orders.
Execution remains disabled in every mode.

Start with [Phase 3 acceptance requirements](docs/phase3/ACCEPTANCE_TESTS.md),
[original plan](docs/phase3/DATA_PLAN.md),
[frozen V2 availability amendment](docs/phase3/DATA_PLAN_V2.md),
[ADR-014](docs/adr/014-nonproduction-research.md),
[Phase 2 independent acceptance](docs/reviews/PHASE_2_RESEARCH_ACCEPTANCE.md),
[daily schedule](docs/amendments/SCHEDULER_2300.md) and [document index](docs/README.md).

The design is agentic outside and deterministic inside: agents investigate and propose;
typed risk gates and execution adapters retain authority. Exness real execution is locked;
Binance live derivatives remain BLOCKED_BY_POLICY. No paid service is mandatory.

Repository documentation checks (Node.js, no package install):

```text
node tools/check-docs.mjs
git diff --check
```

These checks validate repository documents, not future trading safety or profitability.
Independent exact-head review is required before merge or a new phase prompt.
