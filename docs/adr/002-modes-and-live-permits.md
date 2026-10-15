# ADR-002: modes and live permits

Status: FROZEN
Date: 2026-10-15
Requirements: R-003, R-004, R-021

## Context

A toy demo implementation would hide integration failures; a credential-only switch to real would create accidental authority.

## Decision

Share strategy/features/risk/intents/reconciliation across typed modes. Only adapters/clocks/data/account profiles vary. Real mode requires separate permit, eligibility, qualification and fresh step-up activation; Binance live derivatives stay blocked.

## Alternatives

Separate demo/live engines duplicate safety behavior; a boolean live flag or account number alone is insufficient.

## Consequences

Test actual terminal account/server/type independently of configuration. PAPER and SHADOW have no broker send capability. Risk-reducing actions retain dedicated safeguards.

## Validation

Phase 5 demo mismatch/unknown-fill tests; Phase 8 signed permit/account/release checks.

## Review point

Execution and venue policy; owner eligibility and numeric capital decisions remain external.
