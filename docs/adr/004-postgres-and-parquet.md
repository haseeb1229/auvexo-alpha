# ADR-004: postgres and parquet

Status: FROZEN
Date: 2026-10-15
Requirements: R-014, R-015, R-018

## Context

Operational reservations need transactions; historical research needs compressed scans within laptop disk limits.

## Decision

Plain PostgreSQL for truth/ledger/job metadata and immutable Parquet archives with point-in-time manifests. Use atomic reservations/outbox and preserve data vintages.

## Alternatives

SQLite-only production concurrency and unlimited raw books rejected. Timescale deferred until measured partition/query bottleneck and license review.

## Consequences

Two storage systems require checksum/manifests and restore consistency. No broker/DB cross-system exactly-once promise. Targets 120 GB managed, hard cap 150 GB.

## Validation

Phase 2 quality/retention/restore tests; Phase 4 concurrency; Phase 5 measured stress.

## Review point

Data architecture; exact supported versions Phase 1, Timescale decision OD-09 Phase 6.
