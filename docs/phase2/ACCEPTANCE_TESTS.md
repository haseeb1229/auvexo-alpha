# Phase 2 stable child acceptance requirements

Defined before implementation under the revised V2 brief. R-000..R-039 and all
Phase 1 child IDs remain intact. Synthetic tests cannot qualify a real source.

| ID | Invariant | Required executable/evidence mapping |
| --- | --- | --- |
| R-014-P2-01 | Explicit source/product/spec identity; unknown broker values | data contracts; Exness negative tests |
| R-014-P2-02 | Documented archive 2025 unit boundary, UTC, finalized/as-of semantics | parser golden/property/temporal tests |
| R-014-P2-03 | Checksummed bounded safe archive input; quality quarantine | archive corruption/path/size/row tests |
| R-014-P2-04 | Idempotence, immutable revisions and correction impact | storage replay/correction/concurrency tests |
| R-014-P2-05 | Actual coverage matrix, gaps and evidence-driven expansions | coverage tests and genuine pilot receipts |
| R-015-P2-01 | Quotas, free-space pressure, bounded resources; no age-only history cap | storage pressure tests and load receipt |
| R-023-P2-01 | Ingestion role cannot mutate foundation or migrate | real PostgreSQL privilege negatives |
| R-025-P2-01 | Forward migration; atomic publication and backup consistency | crash/recovery/restore tests |
| R-024-P2-01 | Default-off public polling; bounded retry, rate, cancellation | network/429/5xx/timeout/restart tests |
| R-027-P2-01 | Durable freshness, outage, checkpoint and daily evidence | collector and seven-day receipt validation |
| R-022-P2-01 | Deny-only execution unchanged; no broker writes; real refusal | retain all Phase 1 tests; Exness gate negatives |
| R-030-P2-01 | Current official source/dependency rights and provenance | source register, lock, audit, notices |
| R-031-P2-01 | Accepted merge, private unmerged PR, honest local/CI evidence | GitHub receipts and clean clone |
| R-035-P2-01 | Seven real scheduled days cannot be accelerated or invented | qualification tests, actual dated receipts |

Runtime tests will live in `tests/test_data_*.py`; source and outcome inventory is
maintained in the Phase 2 implementation and verification documents at handoff.
