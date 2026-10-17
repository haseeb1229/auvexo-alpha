# Phase 2 verification

Executed evidence as of 2026-10-17; independent acceptance is not claimed.
Entry: accepted Phase 1 295ded25afdd5a95ee0585b41da9966e45812bcf, normal
merge 16e63aeb9e7e1a97082d4a004142e0af163a4571; repository PRIVATE.
See the [acceptance record](../reviews/PHASE_1_INDEPENDENT_ACCEPTANCE.md).

## Local checks

The full suite passed: **225 passed in 277.06 seconds**, retaining all 145 Phase 1
cases. After the quota scanner optimization, its 15 gate cases passed in 3.58 seconds,
including a newly added unreadable-storage test. The committed clean clone passed all
226 cases in 164.21 seconds. Ruff format/check and strict mypy passed (28 source files).
The document/scope checker passed. The pinned lock synced successfully.

Final full working-tree run after the deterministic backfill-test refinement:
**226 passed in 154.26 seconds**, no skips or failures. The
[final local receipt](evidence/local-checks.json) records source/test/log hashes and
confirms production source, migrations and dependency pins match the clean-clone commit.

The [dependency audit](evidence/dependency-audit.json) has no known vulnerabilities
across 69 installed distributions. See [inventory](DEPENDENCIES.json), [SBOM](SBOM.json)
and [added dependency notices](THIRD_PARTY_NOTICES.md). Audit results are dated evidence,
not proof of absence of undiscovered vulnerabilities.

[Gitleaks evidence](evidence/secrets.json): pinned 8.30.1, official release checksum
verified, zero source/history leaks; high-signal source scan also passed. Secrets remain
in ignored owner-ACL-protected local files, never the source export or evidence.

The unmodified final Gitleaks scan reported 96 generic-api-key false positives, all in
public logical_key/feed_key identifiers. The root .gitleaks.toml keeps all default rules
and allows only exact public source/asset/interval/date formats in three named evidence
files, using both path and whole-line conditions. [Control evidence](evidence/secret-scan-exception.json)
proves that another field in the same file and the same identifier at another path still
trigger detection. Review due 2026-11-16. The configured source/history rerun passed.
No real secret, whole file, rule or commit was exempted. See the pinned
[Gitleaks configuration documentation](https://github.com/gitleaks/gitleaks/blob/v8.30.1/README.md).

The negative suite covers explicit timestamp units and the 2025 boundary, implausible
and partial times, exact decimals, OHLC/volume/schema errors, archive checksum/member/
path/symlink/encryption/expansion/corruption limits, gaps, ordering and duplicate conflicts,
lookahead, source/config injection, network timeout/5xx bounded recovery, 429/418 cooldown,
403/451 access blocks, cancellation and byte/request quotas, default-off collection,
real/unattested Exness refusal, expired rights, actual-calendar observation checks,
concurrent publication, correction lineage, idempotence, interrupted rename/DB commit,
orphan recovery, missing/corrupt accepted data, forged completeness, checkpoint restart,
quota refusal, staging cleanup, spec quarantine and ingestion-role privilege negatives.
No skips or weakened assertions were used. Schema-head expectations advance normally.

## Real provider and recovery evidence

[Boundary receipt](evidence/boundary-provider.json): four genuine hourly daily archives,
BTC/ETH on 2024-12-31 and 2025-01-01, 24 rows each, checksum verified and no findings.
Pre-transition milliseconds and post-transition microseconds parse without magnitude
heuristics. Collection happened on October 16; historical first-seen remains UNKNOWN.

[Public pilot](evidence/public-pilot.json): all seven commands exited successfully on
October 17. Successful import does not mean every range is complete: both March 2020
partitions are DEGRADED. [Coverage](evidence/coverage.json) and
[full manifests/events](evidence/datasets.json) give exact ranges, URLs, raw/normalized/
Parquet hashes, dataset versions, rights, processing times, code identity and findings.
[Spot specs](evidence/spot-specs.json) are current spot facts only, never CFD substitutes.
Read [coverage analysis](QUALITY_AND_COVERAGE.md) for the short-candle/gap findings.

The initial historical manifests were created from an explicitly marked dirty working
revision with a source-tree hash; no clean commit identity is retroactively invented.
Their final-code replay is independently checked. Bulk raw/Parquet files remain ignored
under .local/market; metadata and small nonsecret receipts are tracked privately.

[Data recovery](evidence/data-recovery.json): eight tables matched after isolated restore,
16 manifests and all raw/Parquet hashes verified; exact source-to-normalized-to-Parquet
replay passed; all five restored append-only triggers refused mutation. Schema is
0003_source_receipts. [Foundation recovery](evidence/foundation-recovery.json) also passed
migration idempotence, destructive downgrade refusal and schema-drift readiness failure.
The retained backup is same-disk DEV evidence, not encrypted/off-device disaster recovery.

## Resources and failures retained

The real pilot measured process-tree peak RSS of 157,405,184 bytes (about 150 MiB).
The two-cycle collector used peak 147,521,536 bytes, 18.984375 CPU seconds over 110.419
wall seconds, four requests and 1,003 response bytes. This is about 0.17 CPU cores
averaged over a short run, not a steady-state or seven-day guarantee. The optimized
ETH history rerun used 19 CPU seconds over 84.846 wall seconds. BTC's earlier loaded
scanner used 73.453125 CPU seconds over 260.771 wall seconds. No GPU or paid service.
Host: Windows, Python 3.13.16, 16,895,107,072 bytes RAM, 362,582,224,896 bytes free disk
at receipt. Managed tree scan measured 2,184,319,670 bytes in 2.979 seconds; full quota
accounting includes PostgreSQL and may conservatively double-count overlapping storage.

The first pilot stopped on an internal Python junction; its [failure receipt](evidence/initial-pilot-failure.json)
is retained. Internal aliases now count at their real target and external aliases are
refused. Subsequent owner-read failures came from sandbox-created pytest caches; only
those caches received owner access. Unreadable storage still blocks ingestion. The first
full integration run had 221 passes/two failures due to PostgreSQL session-timezone
checkpoint values; explicit UTC conversion fixed them without relaxing UTC contracts.

The initial Polars wheel download timed out after 600 seconds. Resumed official bytes
matched locked SHA-256 7da1caf3c7b4f397fb213c984013a0c755557619a2d511899a1ff74392484078
before installation; no unverified partial archive or version substitute was installed.

The [sustained run](evidence/sustained-resources.json) actually ran October 17 from
05:34:54.657166 to 05:46:30.167740 UTC: twelve cycles in 695.510 seconds, 24 requests,
4,323 response-body bytes, 24 fresh events and no stale/blocked events. It retained
26 bars in 24 new partitions. Peak process-tree RSS was 148,586,496 bytes (141.7 MiB),
settled median 80,048,128 bytes (76.3 MiB), total CPU 94.625 seconds (0.136 cores average;
0.124 settled). No sampling races. Maximum receipt lag from the latest closed-bar end
was 35.174232 seconds; processing timestamp lag was 35.174750 seconds. Processing time
is after parsing, before atomic publication, not an end-to-end database commit clock.

This added 116,162 Parquet and 4,323 raw bytes in 695.510 seconds: about 624 KB/hour of
artifact growth if that particular tiny-batch rate continued, not a capacity guarantee
or retention horizon. The final database occupied 8,681,139 bytes; this is total ending
database size, not a measured database growth delta. No global PostgreSQL WAL/log size
is excluded from the managed-tree quota accounting. No 5m resolution is adopted; archive
hourly batch rerun and live minute processing rates are the measured applicable cases.

[Final dataset/event inventory](evidence/final-datasets.json): 42 manifests, 5,944 rows,
345,109 raw bytes, 752,279 Parquet bytes. [Final restore](evidence/final-data-recovery.json)
passed eight-table equality, all 42 raw/normalized/Parquet replays and five immutable
trigger checks in 32.758 seconds. Foundation policy remained execution_enabled=false
and Binance live derivatives BLOCKED_BY_POLICY. The sustained daytime run still supplies
zero qualifying scheduled midnight windows; it is not seven-day uptime evidence.

## Remaining verification and gates

[Clean-clone receipt](evidence/clean-clone.json): implementation commit
aa96a69983332d2dafe149a12430d9d3deb3de86 passed all checks in a fresh Windows checkout,
venv and isolated database, with a clean tree. Clone/install took 44.420 seconds and
the entire run took 290.390 seconds. A shared verified package cache and hash-verified
local runtime wheel were used; it is explicitly not a cold-cache network benchmark.
The later test-only refinement makes restart/backfill independent of the wall-minute
boundary and adds an explicit five-minute missing interval; its targeted run passed.
Production source remains unchanged from the verified implementation commit.

[Hosted CI](evidence/hosted-ci.json) is EXTERNALLY BLOCKED: push run 39007037704 and
PR run 39007043834 failed before any steps. GitHub's exact reason is retained in the
receipt: failed account payments or a spending-limit block. No billing, visibility,
permissions or runners were changed. This is not a hosted test pass. The private
[PR #3](https://github.com/haseeb1229/auvexo-alpha/pull/3) remains open and unmerged.
The October 17 10:26:51 UTC retry after the reported limit reset also failed before any
steps, with the same exact annotation; its check ID is 117373922593.

The [clean-commit live proof](evidence/committed-live.json) also records two real
six-minute restart/backfill partitions from the exact implementation revision.

[Observation report](evidence/observation.json): OPEN, zero qualified windows. October 17
00:00-00:12 UTC was missed; later dates have not supplied evidence. The daytime pilot
cannot count as a scheduled day. Exness remains EXTERNALLY BLOCKED by owner DEMO access,
encrypted credential storage, isolation, terms/compatibility and terminal attestation.
No real account, trade, order transport, strategy, risk kernel or permit was introduced.
Mandatory spend is zero. No Phase 3 or Phase 2 merge is authorized.

Reproduce with the commands in [setup/recovery](SETUP_AND_RECOVERY.md), then run
ruff format --check, ruff check, mypy, pytest, node tools/check-docs.mjs,
tools/secret_scan.py, tools/verify_data_recovery.py, tools/verify_recovery.py and
tools/verify_clean_clone.py under the configured local toolchain.
