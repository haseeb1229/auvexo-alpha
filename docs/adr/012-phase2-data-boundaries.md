# ADR-012: bounded data ingestion and research-only provenance

Status: ACCEPTED for Phase 2 implementation; independent review pending
Date: 2026-10-16
Requirements: R-014, R-015, R-018, R-023, R-024, R-025

## Context

The accepted foundation has no collector. The revised brief requires evidence-driven
history without conflating operational retention with a maximum research horizon.
Current Binance Vision terms restrict datasets to noncommercial research.

## Decision

Use one synchronous bounded worker, public GET-only market endpoints and explicit
operator opt-in. Adopt daily/monthly 1m/1h spot archives and REST closed candles;
defer tick/quote/websocket capture because minute/hour integrity is the present need.
PostgreSQL serializes publication and stores append-only manifests/events; Parquet
holds exact decimal strings and normalized UTC data. A separate ingestion role has
no foundation-policy write authority. Files are staged, verified, renamed and then
referenced in a DB transaction. Orphan files are never treated as published.

Backfills retain actual retrieval time; original publication/first-seen stay unknown.
Strict as-of availability is actual receipt, with a separate clearly marked historical
close-bound assumption for future research. No strategy is implemented here.

Use a candidate spec separate from the unchanged validated InstrumentSpec. Exness
has only disabled contracts/preflight negatives until owner-side prerequisites exist.
No terminal SDK or credentials are installed/loaded.

The five-year warm retention default remains an operational planning default, not a
research cap. This ADR selects indefinite retained accepted Phase 2 hourly pilot
artifacts within explicit byte quotas until an evidence/rights review authorizes
retirement; 1m expansions require a purpose and budget. No automatic age deletion.
Raw ticks are not adopted. Permanent provenance is never evicted for quota relief.

## Alternatives

Websocket fan-out, duplicated resolutions, a message bus, full tick history, SQLite
production metadata and fixed multi-year downloads add cost without current evidence.
Polars provides typed Parquet I/O without a second dataframe implementation.

## Consequences

The small worker's batch limits bound memory; repeated batches support years of
selected history. Cross-filesystem/DB atomicity is recovered by manifest verification,
not claimed transactional filesystem magic. Local administrator tampering remains a
limitation. Data licensing never confers future live-use permission.

## Validation

[Stable requirements](../phase2/ACCEPTANCE_TESTS.md), real PostgreSQL races/crash tests,
checksums, deterministic Parquet replay, corruption/restore and genuine provider pilots.
Measure native Windows resources. Preserve every existing safety test.

## Review point

Independent Phase 2 review; seven-day observation and Exness external gates remain
separate. Phase 3 must qualify the rights and history needed by each experiment.
