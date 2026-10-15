# ADR-008: free first model and data ports

Status: FROZEN
Date: 2026-10-15
Requirements: R-011, R-013, R-016, R-017

## Context

Existing chat subscriptions do not establish API access, and premium feeds cannot be mandatory for demo.

## Decision

Use permitted free source adapters and optional provider-neutral structured LLM port. Default paid budget zero. CPU-only core runs safely when all LLM providers are absent.

## Alternatives

Mandatory paid news/data/LLM, founder-browser scraping and foundation-model training rejected.

## Consequences

Some research questions remain unanswerable with free/vintage-limited data; disclose gaps and defer affected strategies. Optional browser is sandboxed and audited.

## Validation

Phase 1/5 free path; Phase 6 all-provider outage, source rights and value experiment.

## Review point

OD-10 paid/local-heavy options require evidence and explicit owner purchase approval before use.
