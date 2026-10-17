# Auvexo Alpha

Personal alpha research and trading-system project owned by haseeb1229. Private-first
baseline; source is temporarily PUBLIC under an owner-approved exception, review due
2026-10-24. Public history cannot be revoked by later returning to PRIVATE.

Phases 0 and 1 were independently accepted and normally merged. Phase 2 provides bounded
historical/public spot data and replay. PR #3 remains OPEN/UNMERGED: seven genuine scheduled
days and Exness DEMO source qualification remain OPEN. Execution is disabled in every mode.

The [baseline amendment](docs/amendments/BASELINE_CORRECTION_HANDOFF.md) and
[ADR-013](docs/adr/013-source-specific-acceptance.md) propose source-specific engineering
acceptance separately from full operational acceptance. Independent review and a new prompt
are required before any later engineering. Phase 3 has NOT begun.

Start with the [current handoff](docs/amendments/BASELINE_CORRECTION_HANDOFF.md),
[current daily schedule](docs/amendments/SCHEDULER_2300.md), [Windows setup](docs/phase2/SETUP_AND_RECOVERY.md),
[document index](docs/README.md), [constitution](docs/PRODUCT_CONSTITUTION.md)
and [requirements](docs/REQUIREMENTS_REGISTER.md).

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
