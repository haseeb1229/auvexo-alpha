# Phase 2 consolidated engineering handoff

**PHASE 2 ENGINEERING IMPLEMENTATION COMPLETE, OBSERVATION GATE OPEN.**
Verdict: **ENGINEERING_PASS_WITH_EXTERNAL_SOURCE_GATES**. This is not Phase 2
macro-exit PASS or independent acceptance. Exness and hosted CI remain externally
blocked. No Phase 3 work or Phase 2 merge is authorized.

## Delivery and exact provenance

- Accepted Phase 1: `295ded25afdd5a95ee0585b41da9966e45812bcf`.
- Authorized normal PR #2 merge/main: `16e63aeb9e7e1a97082d4a004142e0af163a4571`.
- Branch: `phase-2/trustworthy-data`, pushed to the private founder repository.
- Implementation: `aa96a69983332d2dafe149a12430d9d3deb3de86`.
- Review: [PR #3](https://github.com/haseeb1229/auvexo-alpha/pull/3), OPEN and UNMERGED.
- Follow-up commits contain measured evidence, this handoff and a deterministic
  backfill-test refinement; production source is unchanged from the implementation SHA.
  Git/PR head identifies this handoff commit without a self-referential hash. The
  delivered local final handoff records the exact final review tip.

[Phase 1 acceptance](../reviews/PHASE_1_INDEPENDENT_ACCEPTANCE.md) records the exact
accepted head and normal merge. [Hosted evidence](evidence/hosted-ci.json) records
PRIVATE visibility, unchanged main and an unmerged branch. No history was rewritten.
Commits use the configured Muhammad Haseeb identity without AI co-author trailers.
No billing, visibility, permissions or runner settings changed.

## Changed-file and module summary

The implementation commit changes 68 files. [Implementation](IMPLEMENTATION.md) and
[stable child acceptance IDs](ACCEPTANCE_TESTS.md) map modules to proofs.

| Area | Delivered changes |
| --- | --- |
| Domain/application | Source/rights/spec/temporal/candle/manifest/event contracts; quality, coverage and calendar gates; deny-only demo prerequisite gate |
| Infrastructure | Bounded ZIP/CSV/REST parser; GET allowlist/retry/cooldown budgets; raw/Parquet publication, immutable correction lineage, checkpoint/reconciliation, quotas, quarantine and exact replay |
| Operator tools | Separate default-off CLI; data-writer provisioning; real pilot/resource evidence; isolated artifact/DB restore; fresh Windows clone |
| Database | Forward 0002/0003 migrations; append-only provenance/spec/event tables and restricted ingestion role |
| Tests/CI | Parser/property/network/gate/real-PostgreSQL failure tests; retained Phase 1 suite; existing least-privilege workflow extended to Phase 2 branch/data role |
| Dependencies | Pinned Polars 2.0.0 CPU writer, lock/audit export, inventory, SBOM and notices |
| Canonical docs | Architecture, data/source register, security, recovery, performance, requirements, roadmap, open decisions, ADR-012/index, docs index and byte-identical AGENTS/CLAUDE |
| Review package | Exact brief, Phase 1 acceptance, Phase 2 implementation/acceptance/source/coverage/setup/verification/handoff and nonsecret receipts |

No frontend, broker SDK, account connection, strategy, risk kernel, order transport,
permit issuer, withdrawal or trading operation was added. Execution remains disabled
in every mode; Binance live derivatives remain BLOCKED_BY_POLICY. Original 0001 migration
and Phase 1 contracts are retained; schema-head expectations advance normally.

## Source status and actual coverage

| Source | Implemented and genuinely observed | Remaining limits |
| --- | --- | --- |
| DS-01 public spot archives | Checksummed BTC/ETH hourly history: two boundary days and four selected months per asset, raw retention and exact replay | Research-only rights; sparse history and two degraded March partitions |
| DS-02 market-data-only REST | BTC/ETH finalized 1m polling, current spot specs, checkpoints and real stopped/restarted backfill | Closed-bar research feed, not executable bid/ask/ticks or guaranteed latency |
| DS-03 Exness BTC/ETH/XAU CFDs | Distinct unknown-spec/coverage rows and unconditional connector refusal | EXTERNALLY BLOCKED: no DEMO access, encrypted broker store, isolated terminal/process, current terms/compatibility or terminal attestation |

[Source rights](SOURCES_AND_RIGHTS.md) records official evidence reviewed October 16,
review expiry November 16 and exact terms hashes. Vision dataset terms are CC BY-NC-SA
with supplementary restrictions; repository MIT does not grant live/commercial dataset
rights. REST uses no API key. No dataset redistribution or broker qualification claimed.

[Coverage matrix](evidence/coverage.json), [manifests/events](evidence/datasets.json),
[spot snapshots](evidence/spot-specs.json) and [analysis](QUALITY_AND_COVERAGE.md) give
exact URLs, source/normalized/Parquet hashes, versions, times, rows and retained sizes.
For each asset: 24 hourly bars on 2024-12-31, 24 on 2025-01-01, 742/744 in March 2020,
and 720/720 in November 2022, June 2024 and September 2026. March 4 has a short 09:00
candle and absent 10:00 candle. Those ranges remain DEGRADED and fail completeness.
The real [unit-boundary receipt](evidence/boundary-provider.json) verifies pre-2025
milliseconds and post-2025 microseconds without magnitude guessing.

Earliest selected data is 2020-03-01 UTC; latest selected month ends 2026-10-01 UTC.
Unselected years/months and pre-2020 availability remain UNKNOWN. There is **no fixed
five-/ten-year cap**, no pre-inception invention and no research sufficiency claim.
ADR-012 separates warm-store planning from byte-budgeted research-history selection.

Initial live proof covers [05:24,05:27) UTC on October 17, three finalized bars per asset.
A separate [clean-commit restart receipt](evidence/committed-live.json) covers the next
six missed minutes per asset without gap or overlap after collection stopped between
invocations. This is real stop/restart/backfill evidence; injected network-fault tests
are separately identified and are not claimed as actual provider outage observations.

The initial sixteen partitions contain 5,906 rows, 338,811 raw bytes and 625,427 Parquet
bytes (Parquet/raw ratio about 1.85; raw ZIPs are already compressed and tiny partitions
retain full provenance). Later genuine live receipts are separate versions. Original
publication/first-seen remains UNKNOWN; strict as-of uses actual receipt/processing time.
Historical manifests retain their dirty working-tree identity and source hash; final-code
replay verifies them. Later live manifests name the exact clean implementation commit.

## Checks, recovery and resources

[Verification](VERIFICATION.md) records commands, negative cases, initial failures/fixes,
licenses, audit and resource limitations. No test was skipped or weakened and no fixture
was used for source qualification.

- Fresh committed-source Windows clone: **226 tests passed**, isolated PostgreSQL migration,
  clean tree; Ruff, strict mypy, docs and source scan passed. [Receipt](evidence/clean-clone.json):
  44.420 seconds clone/install, 290.390 total; tests 164.21 seconds. Verified shared cache/
  local wheel was used, explicitly not a cold-cache network benchmark.
- Earlier full working-tree run: 225 passed; then 15 gate cases and the strengthened
  deterministic five-minute backfill test passed. Final full-suite result is in verification.
- [Data restore](evidence/data-recovery.json): eight tables matched, 16 manifests verified,
  exact source-to-normalized-to-Parquet reconstruction passed and five restored immutable
  triggers refused mutations. [Foundation recovery](evidence/foundation-recovery.json)
  also passed idempotence, destructive-downgrade refusal and schema-drift readiness failure.
- Schema: `0003_source_receipts`. Missing/corrupt artifacts, false completeness, gaps,
  conflicting duplicates, interrupted publication and forbidden role writes fail closed.
- Locked dependencies: no known vulnerabilities in [audit](evidence/dependency-audit.json);
  [SBOM](SBOM.json), [inventory](DEPENDENCIES.json), [notices](THIRD_PARTY_NOTICES.md).
- Gitleaks 8.30.1 source/history and high-signal source scan found no secrets. Bulk data,
  caches and DEV credentials remain ignored. AGENTS and CLAUDE are byte-identical.
  The reviewed [public-identifier exception](evidence/secret-scan-exception.json) is
  constrained to exact fields/formats/paths, retains every default rule and passed
  positive detection controls; review due 2026-11-16.
- Short pilot peak process-tree RSS: about 150 MiB. Two live cycles used 18.984375 CPU
  seconds over 110.419 wall seconds, four requests/1,003 response bytes. A separate
  sustained-run receipt supplements this short measurement. Two CPU threads, bounded
  requests/batches, 2 GB pilot cap and conservative global disk-pressure gates apply.
  No GPU, paid service, unbounded backfill or automatic age deletion.

Final [sustained resource proof](evidence/sustained-resources.json): twelve cycles over
695.510 seconds, 24 fresh observations, 26 added bars, 24 requests/4,323 response bytes,
141.7 MiB peak and 76.3 MiB settled-median RSS, 0.136 CPU cores averaged over the run.
Maximum receipt lag was 35.174232 seconds. Final database size: 8,681,139 bytes.
[Final inventory](evidence/final-datasets.json) contains 42 datasets/5,944 rows and
345,109 raw plus 752,279 Parquet bytes. The [final restore](evidence/final-data-recovery.json)
verified all 42 exact source-to-Parquet replays, eight tables and five immutable triggers.
Final full-suite rerun: **226 passed in 154.26 seconds**, with no failures or skips.

Hosted CI is **EXTERNALLY BLOCKED**, not passing. Both implementation-head jobs had zero
steps. GitHub reported: "The job was not started because recent account payments have
failed or your spending limit needs to be increased. Please check the 'Billing & plans'
section in your settings". [Exact runs/annotations](evidence/hosted-ci.json). Equivalent
safe local checks were run. The owner must decide how to resolve that account block;
no payment, spending-limit increase or repository-setting change was performed.

## Observation and independent-review prerequisites

[Seven-day receipt](evidence/observation.json): **OPEN, zero qualified daily windows**.
October 17 00:00-00:12 UTC was missed; daytime pilots do not count. No actual seven-day
start/end pair exists and no asynchronous continuation is promised. The
[operator runbook](SETUP_AND_RECOVERY.md) specifies genuine daily 05:00 Asia/Karachi
windows, one instance, bounded runtime, retained receipts and qualification against an
actual first date. Missed or late days remain missing.

Remaining gates:

1. Seven genuine consecutive scheduled collection days with acceptable quality and
   independently examined storage/freshness/failure receipts.
2. Owner-authorized secure Exness DEMO onboarding, isolation, current terms/compatibility
   and genuine terminal spec/history attestation, or an explicit canonical scope decision.
   No credentials in chat, REAL terminal, or boolean/label substitution.
3. Hosted private CI qualification after the owner resolves the external account block.
4. Independent review of the exact final PR head, closure of findings, explicit normal
   Phase 2 merge authorization and a new Phase 3 prompt. Self-verification is not review.

Mandatory spend: **$0**. Repository: **PRIVATE**. Trades/account connections/permits: **0**.
Stop at this Phase 2 engineering handoff. Macro-exit, Phase 3 and execution remain gated.
