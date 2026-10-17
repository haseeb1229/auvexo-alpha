# Phase 2 evidence closure — 2026-10-17

Verdict: **PHASE_2_CLOSURE_IN_PROGRESS**. Retrospective seven-day coverage passed.
Genuine scheduled collection has **zero completed qualifying dates**; Exness DEMO
and independent exit/governance review remain open. PR #3 stays OPEN and UNMERGED.
No Phase 3 or trading is authorized.

## Authority, refs and owner decisions

Current instruction: [October 17 evidence-closure brief](../../reference/PHASE_2_EVIDENCE_CLOSURE_BRIEF.txt).
The earlier alternative closure file was not followed. Preserve the original
[engineering handoff](../HANDOFF.md), [verification](../VERIFICATION.md) and JSON
receipts as dated snapshots, including their then-PRIVATE and blocked-CI facts.

- Repository `haseeb1229/auvexo-alpha` is currently **PUBLIC**, deliberately changed
  by its owner before this sprint. The implementer did not change visibility.
- Main remains `16e63aeb9e7e1a97082d4a004142e0af163a4571`; Phase 1 accepted head
  `295ded25afdd5a95ee0585b41da9966e45812bcf`.
- Entry branch `phase-2/trustworthy-data`, exact head
  `32ada1f35836246486fb1379c808d9119bbe9ce4`; original implementation
  `aa96a69983332d2dafe149a12430d9d3deb3de86`.
- Tested closure implementation: **`8eb92ea0a41cc0f43ec9003dcd63a6537262e156`**.
  The following evidence/handoff commit changes review documents only. Its exact
  final-tip validation is retained in the local final delivery record.
- [PR #3](https://github.com/haseeb1229/auvexo-alpha/pull/3) is the sole review PR.
  Delivery commits follow entry without history rewriting or AI co-author trailers.
  The final ignored `.local/PHASE_2_FINAL_HANDOFF.md` records the exact final PR head
  and subsequent hosted/clean-clone receipts; a commit cannot embed its own hash.
- Owner explicitly approved the [temporary public-source exception](PUBLIC_VISIBILITY_PROPOSAL.md),
  review due **2026-10-24**, independent governance review still required; and the
  [daily task](SCHEDULER_PROPOSAL.md) after verification. Neither approves Exness onboarding.

[GitHub state](evidence/github-state.json) records observed refs/visibility. Private-first
constitution/R-031 remain frozen; this is a temporary recorded exception, not a permanent
superseding ADR. Public source exposes design/risk policy and copies cannot be undone.
Return to PRIVATE is recommended after allocation is resolved, requiring separate owner
instruction. No application/database was published; billing, visibility, token permissions
and runner settings were unchanged.

## Reviewed scope and confirmed corrections

Reviewed actual constitution, requirements R-014/015/022/029/031 and Phase 2 child
acceptance IDs; roadmap; architecture; data architecture/source register; risk/capital,
execution/venue, security, open decisions, research/validation and engineering rules;
ADR index/006/012; Phase 1 independent acceptance; Phase 2 acceptance/rights/coverage/
setup/recovery/verification/handoff; source, migrations, tests, stored receipts and CI.

| Changed files / reference | Why needed |
| --- | --- |
| `application/data_reporting.py:61`, `data_cli.py:126`, `infrastructure/data_store.py:492` under `src/auvexo_alpha` | FRESH strings previously qualified without artifact evidence. Now require stored hash-verified manifests/artifacts, DS-02 REST identity, matching symbol/feed/1m, complete PASS coverage, valid receipt/processing order and <=120-second receipt lag. Duplicate events/versions fail. Seven dates, >=11 observations per symbol, >=600-second span and <=120-second gaps are unchanged. |
| `tests/test_data_gates.py:162`, `tests/test_data_storage.py:233` | Explicit synthetic calendar tests, eight invalid/mismatched/stale/duplicate cases, and real PostgreSQL corrupt-artifact refusal. No fixture qualifies a real date. |
| `src/auvexo_alpha/cli.py:12`, `tests/test_cli.py:28` | Reproduced cold Windows invalid-config timeouts. Defer HTTP/server/DB imports until validated configuration needs them; new test forbids those stacks on invalid input. Ten-second limits/redaction assertions unchanged. |
| `tools/run_daily_window.py:18`, `tests/test_scheduled_wrapper.py:17` | Approved bounded scheduler wrapper around existing CLI; strict start, child/output/storage bounds, harmless flood/deadline negatives. No second collector/parser. |
| `src/auvexo_alpha/infrastructure/source_registry.py:15` | New current DS-01 editorial terms snapshot/version prospectively; preserve immutable prior rights metadata and November 16 expiry. |
| `docs/DATA_ARCHITECTURE.md`, `docs/adr/012-phase2-data-boundaries.md` | Separate strict observed as-of from a future explicitly named price-only close/lag simulation assumption. No simulator or historical lookahead exception implemented. |
| `AGENTS.md`, `CLAUDE.md`, `docs/README.md`, `docs/ROADMAP.md`, `docs/OPEN_DECISIONS.md` | Current evidence pointers/dated owner exception; agent files byte-identical, ten-phase sequencing and financial/exit rules unchanged. |
| This closure directory and archived new brief | Consolidated report, approved plans and new dated receipts preserve old evidence. |

Parser audit retained explicit 2025-01-01 milliseconds/microseconds boundary, complete
interval validation and ZIP/CSV size/path/row limits. Collector remains bounded,
allowlisted GET-only, default-off opt-in with durable checkpoints/cooldown. Store quotas,
atomic staging, immutable lineage, quarantine and exact replay remain. No migrations,
dependencies, workflows or secret-scan exceptions changed; no broker SDK added.

## Actual retrospective coverage

**RETROSPECTIVE_7_DAY_DATA_COVERAGE = PASS** for **2026-10-10 through 2026-10-16**
inclusive. [Per-range receipts](evidence/retrospective-7-day.json) contain all 14 official
URLs/checksums, source/normalized/Parquet/manifest hashes, versions, actual rows/findings,
receipt/processing timestamps, original rights snapshots and code identities.

| Asset | Source / timeframe | Dates | Verified rows | Quality |
| --- | --- | --- | --- | --- |
| BTCUSDT | DS-01 official spot daily archives / 1m | October 10–16 | 1,440 each; **10,080** | All seven PASS |
| ETHUSDT | DS-01 official spot daily archives / 1m | October 10–16 | 1,440 each; **10,080** | All seven PASS |

Used only existing bounded history CLI, explicit periods; no REST fallback, alternate
host/provider, scraping/IP bypass or unnecessary years. Eleven initial invocations
succeeded. BTC October 12 and ETH October 15/16 first failed with generic failed-operation
results and no durable provider-specific cause; same-CLI retries succeeded after host
load cleanup. Cause remains **UNKNOWN**, not an invented provider outage. Successful
invocations prove **28 requests / 942,267 response-body bytes**. Failed request counts
are unknown, maximum six per failed invocation: overall requests bounded **28–46**.
Counters are cumulative per invocation; aggregate maxima, not every event counter.

The [current coverage matrix](evidence/coverage.json) preserves all source identities,
including degraded originals and three separately blocked/unknown Exness instruments.
Original **42 manifests / 5,944 rows** remain unchanged. Current **56 manifests /
26,104 rows**, **1,286,102 raw + 2,431,856 Parquet bytes**. All 56 replay exactly from
retained source bytes through normalized candles to Parquet. Cached reimport of all 14
actual archives returns the same versions/manifests without additions. Original March
2020 **742/744 DEGRADED** ranges per asset remain short/missing; no candles fabricated.
Unselected history UNKNOWN, no fixed five-/ten-year research horizon.

Actual retrieval is October 17, 2026; original publication/first-seen **UNKNOWN**.
All 14 strict historical `read_as_of` checks refused with `LOOKAHEAD_BLOCKED`.
Future price-only simulation needs Phase 3 authorization and explicit causal close/lag
assumptions; macro/news vintages cannot inherit those assumptions.

[Current rights recheck](evidence/rights-recheck.json), [original review](../SOURCES_AND_RIGHTS.md):
official v1.0/August 26 terms now hash
`99c4921dbe023cd68c1a447775707d621453cc78aec6ac0bfe2e6c06a5114ee0` after editorial
spacing, capitalization, wrapping, punctuation and clause-12 document-name correction.
Research restrictions unchanged. Both full snapshots remain ignored locally; existing
immutable manifests retain original `dcf358...` reviewed snapshot. Next review stays
**2026-11-16**. Attribution: **Binance Vision**. These dataset-derived coverage statistics
are **CC-BY-NC-SA-4.0 plus supplementary Vision terms**, separate from repository MIT.
Personal nonproduction/noncommercial research only; no live proprietary/commercial use
entitlement, paid distribution, full terms or raw candles published.

## Genuine scheduled collection

**SCHEDULED_7_DAY_COLLECTOR_RELIABILITY = OPEN. Actual qualified dates: [] (0).**
October 17 00:00–00:12 UTC was missed. Past archive download/daytime pilots do not
prove Auvexo ran on earlier dates; no future dates counted.

[Inspected registration](evidence/scheduler.json): `AuvexoAlpha-PublicData-Daily`,
Interactive/Limited owner, no stored password/elevation, IgnoreNew, no retry/late catch-up,
network and AC required, wake requested, 20-minute outer cap. Exact action/working
directory and owner/SYSTEM-only log ACL recorded. First trigger **October 18 04:57
Pakistan time**, two bounded warm-up cycles outside unchanged **05:00–05:12 local /
00:00–00:12 UTC** evidence window. Normal twelve cycles have a 13-minute child deadline;
wrapper stops only owned descendants on deadline/output overflow. Log cap 1 MiB,
directory 20 MiB; rotate only own logs older than 14 days, preserve all summaries/data.

Dry-run inspected; local-only `--preflight` passed without collection. Task Ready is
not a successful scheduled run. Initial unsigned registration-file launch was refused
by execution policy; reviewed native commands then ran inline without changing policy.
S0 connected standby/hibernate available, S3 unavailable; wake is not overnight proof.
Owner must stay logged in, native DB running, laptop online/on AC. Missed days remain
missed. This is a daily twelve-minute gate, never 24/7 reliability proof.

## Verification and honest limitations

Committed-source proof at **8eb92ea0a41cc0f43ec9003dcd63a6537262e156**:

- [Fresh Windows clone](evidence/committed-clean-clone.json): **241 passed in 213.27s**,
  no skips/failures; fresh venv, isolated real PostgreSQL migration, Ruff format/check,
  strict mypy, docs/source scan and clean Git tree. Clone/install 76.465s, core checks
  423.388s overall. Shared verified download cache/runtime wheel explicitly reused.
- [Extended cloned-code checks](evidence/committed-extended-checks.json): actual DEV
  artifact/DB backup restored into a fresh isolated database, all eight tables equal,
  **56** exact replays and five immutable triggers; separate foundation recovery,
  schema/downgrade/idempotence negatives, unchanged locked export, no known dependency
  vulnerabilities, zero Gitleaks source/history findings (**11 commits scanned**).
  Application/recovery programs loaded from this clone; only owner-private credentials
  and the existing native PostgreSQL harness were shared. Data restore 125.506s,
  foundation restore 24.613s. These are measured checks, not twelve-minute feed timing.
- [Hosted PR run 39041805713](evidence/committed-hosted-ci.json), job **117422638695**:
  **SUCCESS, 241 tests in 12.61s**; all actual job steps inspected, including migrations,
  lint/types/docs/source scan/audit/diff. [Observed PR/main state](evidence/committed-github-state.json)
  is OPEN/UNMERGED and PUBLIC, main unchanged. Final evidence-only head is checked
  again; its external local receipts avoid a self-referential commit.

- Working-tree full suite **241 passed in 131.18 seconds**, no skips/failures; Ruff
  format/check (53 files) and strict mypy (28 source files) passed. The subsequent
  editorial registry snapshot is covered by committed-clone checks after delivery.
- [Data restore](evidence/data-recovery.json): 56 manifests, eight identical tables,
  exact source-to-Parquet replay, five restored immutable triggers. Real quarantined
  payload count zero; synthetic quarantine/corruption negatives are tests, not live
  malformed-provider evidence. Same-disk DEV backup is not encrypted disaster recovery.
  [Foundation restore](evidence/foundation-recovery.json): three tables, migration
  idempotence, downgrade refusal, trigger/schema-drift guards. Schema `0003_source_receipts`.
- [Locked audit](evidence/dependency-audit.json): no known vulnerabilities; lock,
  inventory/SBOM/notices unchanged, no new dependencies/licenses.
- [Gitleaks source/history](evidence/secrets.json) and [positive controls](evidence/secret-scan-exception.json):
  8.30.1, all default rules, unchanged narrow exact-field/path identifier exception
  (review November 16); wrong field/path still detected. High-signal scan passed.
  Bulk data/credentials/backups remain ignored and local ACL-restricted.
- [Entry CI rerun](evidence/entry-hosted-ci.json): run **39025054731 attempt 2**, job
  **117410642644**, exact `32ada1f...`, SUCCESS: actual PostgreSQL migrations,
  **226 tests**, Ruff/mypy/docs/source scan/locked audit/diff all ran. Original failed
  billing annotation is preserved. PUBLIC success does not prove PRIVATE allocation
  resolved. Existing pinned actions/read-only workflow unchanged. Delivery-tip hosted
  CI and clean Windows clone are inspected after delivery; final exact-tip receipts
  reside in the local final handoff, avoiding a self-referential evidence commit.
- Exact-entry Windows clone first had six failures: four CLI cold-start deadlines and
  two storage lock/contention failures. Targeted storage rechecks passed; CLI timeouts
  reproduced. A loaded intermediate root run had three CLI failures. Lazy imports
  address unnecessary cold work; no timeout/test weakened. Four verified obsolete
  disposable clone venvs inside this workspace were removed, preserving their source,
  receipts and all market data; two additional completed-verification venvs were
  subsequently removed for the same bounded-storage reason. Candidate source and
  receipts remain; recreate its venv from the unchanged lock if needed. No other
  project's files/caches touched. Final root
  suite passed. Verifier tuple parsing and scan-log-count assertions were corrected;
  these were verifier errors, not data defects or suppressed scanner findings.

Free-first CPU-only, Polars two threads, existing bounded HTTP/archive/store quotas and
disk-pressure refusal remain. Prior sustained-resource proof stays dated, not a new
week-long measurement. Native PostgreSQL 17.11, Python 3.13.16, uv 0.13.1 and Polars/runtime
2.0.0 reused. Fresh-clone proof uses committed source, fresh venv and verified shared
cache/wheel; it is explicitly not a cold internet-cache benchmark.
[Dated Windows/storage snapshot](evidence/windows-environment.json): 16.90 GB RAM,
eight logical CPUs, 2.023 GB managed workspace, 338.05 GB free, 8,738,483-byte DEV
database, NORMAL storage pressure; the default 2 GB market-data budget remains.
This is a snapshot, not a fresh peak-load/overnight measurement.

## Exness and remaining exit actions

[DEMO preparation](EXNESS_PREPARATION.md) rechecked OD-03, ADR-006 and source/venue policy.
DS-03 remains **BLOCKED**. For each BTC/ETH/XAU CFD, broker symbol, contract size,
minimum/step lot, tick size/value, spreads, sessions/financing, available history and
genuine DEMO account/server attestation are **UNKNOWN**. No SDK/session/connection;
Binance spot cannot substitute.

1. Owner keeps scheduled-task prerequisites satisfied; examine real daily receipts
   and run existing qualification from the first actual date. If October 18 is missed,
   start with a genuine later date, without changing timestamps.
2. Separately approve DEMO onboarding before connecting. Establish dedicated Windows
   identity/process/profile, encrypted OS-bound secret handling, terms/compatibility
   and capability isolation first, then local GUI login only. Never paste credentials
   into chat/logs/PRs. REAL/unknown/swapped account fails closed; unconditional broker
   refusal remains until authorized proofs. No terminal order tests in Phase 2.
3. Independent governance review of temporary public-source exception by October 24;
   separately decide private visibility. No permanent public or billing resolution inferred.
4. Independent exact-final-SHA exit review must inspect seven actual days, DS-03 proof
   or an explicit reviewed canonical scope disposition, current CI/security/recovery
   and all findings. Later explicit merge approval and new phase prompt are required.
   Self-verification is not independent acceptance.

**Zero DEMO/REAL orders, zero broker credentials used, zero account connections or
permits. Execution disabled all modes; Binance live derivatives BLOCKED_BY_POLICY.
Mandatory spend $0.** No paywall/purchase, self-hosted runner, Phase 3 branch, strategy,
backtester, risk kernel, order transport or frontend. Stop at this honest handoff;
no continuous future agent work promised. The approved local task may collect later.
