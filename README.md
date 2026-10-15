# Auvexo Alpha

Private, personal alpha research and trading-system project owned by haseeb1229.

Phase 0 was independently accepted and merged through PR #1. This branch implements the
Phase 1 engineering foundation: strict contracts, real PostgreSQL migrations and authenticated
loopback diagnostics. Execution remains disabled in every mode, including DEMO.
Phase 1 is submitted for independent review; Phase 2 is not authorized.

Start with the [Phase 1 handoff](docs/phase1/HANDOFF.md), [Windows setup](docs/phase1/SETUP.md),
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
Independent review of the exact Phase 1 commit/CI and a new prompt are required before Phase 2.
