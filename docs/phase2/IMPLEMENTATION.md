# Phase 2 implementation inventory

Scope: bounded public data research, all execution disabled. This document describes
implementation; actual passing checks/source receipts are separately recorded in
[verification](VERIFICATION.md). Exness is deliberately unconnected.

| Module | Responsibility | Proof |
| --- | --- | --- |
| `domain/market_data.py` | Versioned source/rights, aliases, unknown candidate spec, raw record, finalized candle, temporal window, coverage, manifest, checkpoint and event | `test_data_parser.py`, `test_data_gates.py` |
| `application/data_quality.py` | Deterministic order/dedup/gap checks and fail-closed complete-data requirement | Parser tests |
| `application/data_reporting.py` | Actual source/venue/timeframe coverage and seven real UTC-day qualification | Gate tests; pilot reports |
| `application/demo_data_gate.py` | Real/unverified refusal and external demo prerequisites; even supplied booleans cannot create a connection | Gate tests; existing no-SDK/no-order tests |
| `infrastructure/spot_parser.py` | Bounded checksum/ZIP/CSV/REST parsing, exact financial values, explicit time units and finalization | Golden/property/corruption/unit/partial/lookahead negatives |
| `infrastructure/public_http.py` | GET-only allowlist, timeout/bytes/request/retry limits and cancellation | `test_data_network.py` |
| `infrastructure/source_registry.py` | Dated research rights and source identities | Rights expiry tests |
| `infrastructure/data_collection.py` | Opt-in archive and closed-bar polling, source specs, checkpoint recovery and durable failures | `test_data_storage.py`; genuine pilot |
| `infrastructure/data_store.py` | Serialized quota checks, raw retention, staged Parquet, immutable manifests/corrections, as-of reads and reconciliation | Real PostgreSQL concurrency/crash/privilege/corruption tests |
| `infrastructure/data_replay.py` | Reconstruct normalized records and exact Parquet from retained provider bytes and original receipt/processing times | Storage tests and real isolated restore |
| `data_cli.py`, `tools/data_local.py` | Local operator interface; explicit enable, one collector lease, separate credential handling | CLI negatives and real commands |
| `0002_market_data`, `0003_source_receipts` | New forward migrations; append-only lineage/spec/source events and distinct ingest role | Migration, privilege and restore evidence |
| `tools/verify_data_pilot.py`, `tools/verify_data_recovery.py` | Opt-in real-source/resource receipts and isolated DB plus artifact restore | Executed receipts |

No frontend, risk kernel, strategy, account connection, order operation or permit issuer
is added. `0001_foundation` and all Phase 1 contract schemas remain unchanged. Its
schema-head expectation moves forward with migrations; assertions are not removed.

Parquet stores exact financial strings and UTC datetimes plus canonical versioned
records, Zstandard level 3, 4,096-row groups, two CPU threads. Polars reconstructs the
same partition bytes from retained canonical records under the pinned toolchain.
Raw source payloads are content-addressed locally, hashes and retrieval context live
in immutable manifests. A corrected provider payload creates a new version, a parent
link and changed-row count; prior files/manifests remain accessible.

Wholly rejected downloaded public inputs are retained by hash under a separate quarantine
directory and referenced from blocked events. They never enter accepted partitions.
Malformed specifications fail closed; provider cooldowns also persist for spec requests.
All retained bytes count toward quotas. Unreadable managed storage blocks collection.
Internal toolchain aliases are counted at their real target; external links are refused.
The live loop uses a monotonic one-minute cadence, accounting for processing time.

PostgreSQL advisory locks serialize publication/quota checks and CLI collector ownership.
An artifact written before a failed DB commit remains unpublished; re-import safely
recovers. Missing/corrupt accepted artifacts fail verification and idempotent import.
Temporary stages can be cleaned only inside the managed root while holding the publisher
lock. Accepted audit/data lineage is never removed to free disk. Local admin compromise
is not prevented by SQL triggers or content hashes.

Backfilled original publication/first-seen is UNKNOWN. Actual receipt is retained and
used as strict as-of availability. The close-bound assumption is separate and does not
claim exact historical publication. No consumer silently uses historical close time
as observed receipt. Final candles alone enter datasets; gaps/rejections yield DEGRADED
or BLOCKED and prevent complete-data acceptance/checkpoint advancement.

Initial storage cap is 2 GB of data; global managed pressure gates are 120/135/150 GB
and 60/40/20 GB disk headroom. The implementation conservatively pauses ingestion at
the first pressure level. PostgreSQL database bytes are included; physical overlap with
the managed directory can conservatively double-count. Diagnostic reports refuse
over 10,000 records instead of silently truncating. Multi-year expansion is performed
in explicit batches; this bound is neither an age limit nor a promise of unlimited scale.
