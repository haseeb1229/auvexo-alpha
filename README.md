# Auvexo Alpha

Private, personal alpha research and trading-system project owned by haseeb1229.

Phase 0 is a documentation-only architecture freeze on
`phase-0/product-architecture-freeze`. The main branch retains its minimal baseline.
No execution is authorized by this repository, and Phase 1 has not begun.

Start with the [Phase 0 handoff](docs/PHASE_0_HANDOFF.md),
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
Independent review of the exact handoff commit and a new prompt are required before Phase 1.
