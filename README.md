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
INCONCLUSIVE; no champion. Phase 4 Checkpoint A engineering is independently
ACCEPTED/PASS at `e3f39e0397e1846c37febcebc246ea91c9f2eb78`; see its
[acceptance record](docs/reviews/PHASE_4_CHECKPOINT_A_INDEPENDENT_ACCEPTANCE.md) and
[handoff](docs/phase4/HANDOFF.md). ADR-015 through ADR-022 are ACCEPTED/FROZEN for
this scope. The 272.4386 ms concurrent stress tail remains THROTTLE_REQUIRED evidence;
no benchmark rerun is authorized.
Full Phase 4 remains OPEN pending >=14 actual-feed PAPER calendar days. Observation
has not started; its counter is zero. PR #5 merged normally at
`dbe3cd6f47bf5a48c044df2f36cba5ea7081ca09` after exact-head acceptance CI.
Checkpoint B harness implementation proceeds from that main in
`phase-4/paper-observation` under frozen
[ADR-023](docs/adr/023-paper-observation-qualification.md) and
[requirements](docs/phase4/OBSERVATION_ACCEPTANCE.md). Persistent task registration,
observation START, Phase 5 and broker/money capability remain unauthorized.
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
The accepted engineering source and documentation-only administrative child follow
the checked merge sequence in the acceptance record. Checkpoint B needs independent
exact-SHA review and separate owner START authorization before observation begins.
