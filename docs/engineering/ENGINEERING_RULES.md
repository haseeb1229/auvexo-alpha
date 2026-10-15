# Engineering rules

Status: FROZEN. These rules apply to all future phases; Phase 0 contains no runtime code.

| Rule | Required behavior and verification |
| --- | --- |
| ER-01 scope | Read constitution, requirements and ADRs before implementation. No future phase without its gate and prompt. Record requirement changes explicitly. |
| ER-02 types | Strict Python typing and explicit schemas; unknown enums/fields rejected at money-changing boundaries. Validate finite Decimal quantities and instrument precision. |
| ER-03 time | UTC internally, explicit timezone/precision, injected clocks and deterministic seeds. Monotonic time for timeouts; point-in-time joins for research. |
| ER-04 authority | Risk kernel exclusive authorizer; typed immutable intent; adapter bound to account/mode/permit; no frontend/agent bypass. |
| ER-05 delivery | Durable idempotency/reservations/outbox; bounded backoff/timeouts; unknown broker outcome reconciled, never blindly retried. |
| ER-06 errors | Structured errors with reason/correlation and safe context. No broad silent catch, swallowed exception, unbounded polling or success on ambiguous state. |
| ER-07 simplicity | Inspect existing code. No duplicate implementation, dead/abandoned path, unused dependency, unexplained TODO/FIXME or speculative infrastructure. |
| ER-08 configuration | Validated versioned configuration; no magic risk constants outside policy; no temporary auth/live bypass or production mock data. Test fixtures cannot enter runtime registry. |
| ER-09 dependencies | Justify purpose, license, maintenance, footprint and alternatives; pin supported versions/lockfiles; review transitive dependencies and preserve notices. |
| ER-10 migrations | Never edit merged migration history. Expand/migrate/contract where compatibility is required; backup/restore and rollback plan before changes. |
| ER-11 tests | Required checks before commit; no weakened assertions/skipped tests to pass CI. Negative tests for financially critical behavior, not vanity coverage. |
| ER-12 boundaries | Domain imports no UI/venue SDK/LLM framework; contract tests independent of UI E2E. A redesign must not change execution semantics. |
| ER-13 privacy | No secrets/private content in source, logs, prompts, fixtures or frontend. Use keychain and redaction; scan tracked and staged changes. |
| ER-14 Git | Founder configured identity; no AI co-author trailers/banners. Preserve third-party attribution. No destructive reviewed history rewriting. |
| ER-15 handoff | Exact commits, commands/results, evidence, limitations, migration/recovery steps and outstanding gates. Never claim implemented controls based on documentation. |

Phase 1 quality stack direction: Ruff formatting/lint, mypy strict, pytest with selected
Hypothesis properties, dependency lock/audit and secret scanner. Add a tested dependency
boundary check, schema compatibility check and mutation-sensitive risk negatives. CI and
local commands must agree. Each code change states requirement IDs, test evidence and
rollback implications. Suppressions require local reason and bounded review, not global ignores.

Test layers: unit calculations and state transitions; property tests for quantization and
exposure conservation; integration/real PostgreSQL transaction races; DB migration/restore;
venue contract fixtures then real demo contract proofs; deterministic replay; hand-calculated
backtest correctness; truncation/lookahead and label leakage; failure injection; reconnect;
stale data; duplicate command/fill; clock/DST/precision; risk/environment boundaries; auth;
frontend contract generation; E2E owner activation/pause/explanation/recovery when clients exist.

Mandatory adversarial examples: simultaneous intents exceed combined cap; stale authorization
after policy revocation; credential swap to real under DEMO; partial fill followed by timeout;
crash after broker acceptance before persistence; duplicate callbacks; cancel/fill race; lost
gateway lease; incorrect lot multiplier/FX; NaN/Infinity/negative size; missing stop; disk full;
out-of-order macro revisions; malicious retrieved instruction; all LLM providers unavailable.

Phase 0 applicable checks are document structure, required deliverables, brief coverage,
local links, aligned instruction files, scope (no runtime), placeholder/secret review and
Git state. [Check script](../../tools/check-docs.mjs) is repository QA tooling, not a trading
foundation. It does not prove architecture safety or validate future runtime behavior.

Accepted technical debt requires ID, owner, reason, impact and expiry/review point. Current
accepted implementation debt: none (there is no implementation). Provisional designs and
external gates are tracked separately in [open decisions](../OPEN_DECISIONS.md). Future debt
records must include remediation and tests; security bypasses cannot be reclassified as debt.
