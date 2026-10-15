# ADR-005: durable jobs before message bus

Status: FROZEN
Date: 2026-10-15
Requirements: R-010, R-018, R-024

## Context

Timers and in-memory queues alone lose work on crash; a separate bus is premature for one local owner.

## Decision

Durable PostgreSQL jobs and transactional outbox with bounded queues, idempotent consumers and explicit retry/deadline rules. One writer epoch per account.

## Alternatives

NATS JetStream and Redis deferred; unbounded LLM loops rejected. Adding a bus would not solve broker idempotency.

## Consequences

Backpressure and outbox health must be monitored. Optional data may be coalesced with gap records; execution/audit cannot be dropped.

## Validation

Phase 4 restart/dedup/concurrency tests; Phase 5 queue burst/crash evidence.

## Review point

Agent architecture; revisit OD-09 if independent consumers or throughput justify a bus.
