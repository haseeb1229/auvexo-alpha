# Auvexo Alpha

Personal alpha research and trading-system project owned by haseeb1229. Private-first
baseline; source is temporarily PUBLIC under an owner-approved exception, review due
2026-10-24. Public history cannot be revoked by later returning to PRIVATE.
The October 19 remote recheck and owner confirmation show PUBLIC; the fourth-resume
brief's earlier PRIVATE statement is superseded in [ADR-019](docs/adr/019-paper-lifecycle-filesystem.md).

Phases 0/1 and source-specific Phase 2 research engineering are independently accepted.
PR #3 normally merged at `26b20ca5f0ef18e5300d5213b1cc8d2667bb71d3`; full Phase 2
operational status stays OPEN (scheduled days and DS-03 Exness qualification).
Phase 3 correctness/research independently accepted at `bb692208`; all four outcomes
INCONCLUSIVE; no champion. The owner authorizes Phase 4 Checkpoint A after normal PR #4
merge: virtual PAPER engineering only, no persistent observation or Phase 5.
See [independent acceptance](docs/reviews/PHASE_3_INDEPENDENT_ACCEPTANCE.md).
The [Checkpoint A handoff](docs/phase4/HANDOFF.md) records current local proof and
the formal [ADR-022 performance amendment](docs/adr/022-paper-performance-slo.md).
The preserved benchmark qualifies with an explicit concurrent research-throttle trigger;
its 272.4386 ms stress tail remains visible. No benchmark rerun or phase acceptance is inferred.
Foundation execution remains disabled in every mode; all money actions denied.

Start with [Phase 3 acceptance requirements](docs/phase3/ACCEPTANCE_TESTS.md),
[original plan](docs/phase3/DATA_PLAN.md),
[frozen V2 availability amendment](docs/phase3/DATA_PLAN_V2.md),
[ADR-014](docs/adr/014-nonproduction-research.md),
[review handoff](docs/phase3/HANDOFF.md),
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
