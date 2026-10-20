# Auvexo Alpha

PR #7 is normally merged at `1d6b08fc36884f1bc4845ac54111776d80df056b` after both
administrative CI events/jobs/logs passed1594tests at `14254170de2fa3b7acd0f7edcd6e2a0211de5144`.
Its executable tree equals the accepted source. Development is now on the separate Phase7 branch.
The [read-only foundation design](docs/adr/025-read-only-private-operator-terminal.md),
[requirements](docs/phase7/READ_ONLY_ACCEPTANCE.md) and [runbook](docs/phase7/READ_ONLY_RUNBOOK.md)
are FROZEN before implementation with the explicit data-free static-shell exception; all APIs remain protected.
The active operational checkout remains clean/pinned9b9038b; no broker/money/commissioning authority.

Phase 5 offline foundation is independently ACCEPTED/PASS at `82601fa80a711ce3de66b4b8289ac0f9b679b298`;
see the [independent acceptance](docs/reviews/PHASE_5_OFFLINE_FOUNDATION_INDEPENDENT_ACCEPTANCE.md).
ADR-024 is ACCEPTED/FROZEN for offline engineering; its original document bytes remain retained.
Actual Phase 5 commissioning NOT STARTED; sustained-demo clock zero and execution disabled.
Owner-selected long-term repository disposition is PRIVATE; verified entry remains PUBLIC,
so the temporary exception and 2026-10-24 governance gate remain active. No settings change.
Current authority is docs-only PR #7 acceptance, exact-head CI, then verified NORMAL merge;
only afterward may separate-clone Phase 7 read-only foundation begin under its new frozen ADR.
The active Phase 4 operational release remains separately pinned to `9b9038b` and untouched.

Phase4 engineering is independently accepted; actual-feed observation is ACTIVE on the
separate pinned operational checkout at `9b9038b6966843805c99f15e1c37cdba7c026679`.
Full Phase4 remains OPEN pending genuine dates/span/replay/zero mismatch. The separate
development clone is authorized only for Phase5 OFFLINE/PRE-COMMISSIONING engineering
under [ADR-024](docs/adr/024-parallel-operational-release-and-engineering.md) and [offline requirements](docs/phase5/OFFLINE_ACCEPTANCE.md).
Actual Phase5 commissioning and sustained-demo evidence are NOT STARTED. Broker
SDK/session/order capability is absent; no credentials or money authority. Phase2 full
operational OPEN/DS03 BLOCKED; Phase3 four INCONCLUSIVE outcomes, both OOS consumed,
no candidate/champion. PUBLIC governance review due2026-10-24 and DS02 rights review
due2026-11-16 remain unwaived. Never alter/repoint the operational checkout/task/config/
activation from this development lane. Dated handoffs retain their original historical facts.

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
is ACTIVE on the pinned operational checkout; development earns no qualifying dates. PR #5 merged normally at
`dbe3cd6f47bf5a48c044df2f36cba5ea7081ca09` after exact-head acceptance CI.
Checkpoint B engineering is independently ACCEPTED/PASS at
`527bd23ce434fee557f6f1414bf5b43d7c3c3f21`; see its
[acceptance record](docs/reviews/PHASE_4_CHECKPOINT_B_INDEPENDENT_ACCEPTANCE.md).
ADR-023 and its requirements/runbook are ACCEPTED/FROZEN, with original bytes retained.
PR #6 merged normally at `9b9038b6966843805c99f15e1c37cdba7c026679`.
Preparation and separate owner START have completed; the operational campaign and
registered task remain pinned there. The [historical pre-start brief](docs/reference/PHASE_4_CHECKPOINT_B_PRESTART_BRIEF.txt)
records the earlier preparation-only gate. Frozen [ADR-023](docs/adr/023-paper-observation-qualification.md)
and [requirements](docs/phase4/OBSERVATION_ACCEPTANCE.md) retain their original bytes.
ADR-024 permits only separate-clone offline engineering; actual Phase 5 commissioning,
broker capability and money authority remain blocked.
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
The reviewed operational merge and separately authorized owner START are recorded
locally. Future commissioning still requires its own review and authorization. Offline
engineering stays separate from the active campaign.
