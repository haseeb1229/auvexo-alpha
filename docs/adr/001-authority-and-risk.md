# ADR-001: authority and risk

Status: FROZEN
Date: 2026-10-15
Requirements: R-002, R-022, R-023

## Context

LLM reasoning is useful for investigation but is neither reproducible financial arithmetic nor execution authorization.

## Decision

Use agentic proposals outside a deterministic typed kernel. RiskAuthorization binds intent hash, account epoch, policy, limits, reservation and expiry. Separate process capabilities keep credentials and policy signing outside agents.

## Alternatives

An LLM risk reviewer alone or agent-held venue API keys would make permission enforcement probabilistic and are rejected.

## Consequences

Implement explicit permissions and negative tests; unknown state blocks exposure. A deterministic executor remains necessary even if no agent is enabled.

## Validation

Phase 4 risk/property/concurrency tests; Phase 5 gateway bypass negatives; Phase 8 independent security review.

## Review point

Risk and capital policy; supersede only with equally strong deterministic authority.
