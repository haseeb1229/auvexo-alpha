# Phase 1 verification evidence

Date: 2026-10-16, owner's Windows host. This is implementation evidence, not independent
approval, live-money certification or profitability proof. Exact Git/CI and clean-clone
receipts are added after committing the source under test; no self-referential commit hash.

Sanitized machine-readable receipts: [resources](evidence/resource-evidence.json),
[database recovery](evidence/recovery-evidence.json),
[initial clean clone](evidence/clean-clone-evidence.json),
[dependency advisory audit](evidence/dependency-audit.json).

## Baseline and review workflow

Independent reviewed Phase 0: `745be5b0779f685f731167c0c981d74caae307cf`.
Post-review acceptance record: `fe35b365a2b297831bf0516ea1c73c76289ac7d0`.
[PR #1](https://github.com/haseeb1229/auvexo-alpha/pull/1) merged normally;
main baseline `eafec07ee7c7a98c9cca17b5f8665494bd650751`.
No force-push, protection changes, review impersonation or bypass. The owner explicitly made
the repository temporarily public to allow hosted CI after its billing block. Private visibility
is the retained project default; the final delivery report verifies its restoration.
Configured author: Muhammad Haseeb, abdulhaseeb1229@gmail.com; no co-author trailers.

## Local checks

Commands use the environment installed by [setup](SETUP.md). Real DB tests are mandatory.

```powershell
.venv\Scripts\ruff.exe format --check src tests tools migrations
.venv\Scripts\ruff.exe check src tests tools migrations
.venv\Scripts\mypy.exe
.venv\Scripts\python.exe -m pytest -q -o cache_dir=.local/pytest-owner
.venv\Scripts\python.exe tools/verify_recovery.py
.venv\Scripts\python.exe tools/measure_foundation.py
.venv\Scripts\python.exe tools/secret_scan.py
node tools/check-docs.mjs
git diff --check
```

Ruff format/lint and strict mypy pass; mypy covers 15 production/migration source files.
The complete real-DB suite passed 145 tests in 23.61 seconds, no skips, including added
CLI/fuzz/config cases. Warnings remain errors; none suppressed.
Hypothesis exercises Decimal context independence and bounded arbitrary JSON denial.

Real PostgreSQL 17.11 clean migration, repeated upgrade, constraints, primary-key duplicate,
transaction rollback, UPDATE/DELETE/TRUNCATE refusal and app privilege negatives pass.
API tests include five authenticated routes, missing/wrong token, remote peer spoof, hostile
Origin/Host, public bind/config elevation, missing DB readiness and nonexistent order paths.
All 35 mode/action combinations deny; Binance LIVE/LIVE_LIMITED perpetuals explicitly block.

Recovery tool creates unique isolated TEST/RESTORE DBs. Initial run passed three-table exact
comparison, one synthetic fixture, rollback refusal and restored trigger enforcement in
20.414 seconds; backup 6,942 bytes. The expanded final recovery also verifies schema-drift
NOT_READY and recovery to READY: PASS in 11.370 seconds, 6,943-byte backup, SHA256
`56d489d0a43fd4fbdc97be2414cefd85d7e0c5ed67fa26e3430e23e43b69feb7`.
No SQLite substitute, committed DB dump, order fixture or account credential is involved.

## Measured environment and resources

Windows reported `Windows-11-10.0.26300-SP0`, Intel Core i5-1145G7 (4 cores/8 threads), 15.73 GiB RAM,
343.94 GiB free disk at measurement. Do not substitute old Windows marketing-version registry
labels for the runtime-reported build. Python 3.13.16 and PostgreSQL 17.11 executed natively.

| Measurement | Observed |
| --- | --- |
| API launch to actual DB READY | 3.899 seconds |
| API full process-tree RSS | 86.15 MiB, 3 processes including Windows launchers |
| PostgreSQL full process-tree RSS | 134.55 MiB, 8 processes |
| Idle CPU, 5-second sample | API 0.0%; PostgreSQL 0.3% of one logical core |
| Fresh working environment disk | 145.61 MiB |
| Managed Python disk | 122.91 MiB |
| Toolchains including archives | 512.17 MiB |
| uv cache | 167.26 MiB |
| DEV/TEST PostgreSQL data | 71.24 MiB |

About 1,019 MiB logical file sizes total; files/caches can be shared at filesystem level.
RSS can double-count shared pages; the sample is short, idle, and not a p95/load benchmark.
Real HTTP without authentication returned 401. Measurement API terminated including children;
the local DB remains available until `stop-db`. No GPU/LLM/telemetry stack is present. The
optional pgAdmin/StackBuilder extraction was stopped and removed; bootstrap excludes it.

## Dependency, license and source evidence

`pip-audit --disable-pip --require-hashes -r requirements-audit.txt`: 67 installed-platform
third-party distributions, zero known vulnerabilities, zero ignored advisories. Build backend
included. [Inventory](DEPENDENCIES.json) has recognized license metadata for all 67;
[CycloneDX SBOM](SBOM.json) supplies package versions/purls. See [license review](TOOLCHAIN.md).

Gitleaks 8.30.1 updated exported-source scan: zero leaks in approximately 554,357 bytes;
full Git history: six commits scanned, zero leaks at the implementation checkpoint.
High-signal scanner covers Git-tracked and untracked nonignored files, reports filenames only,
and runs in CI. Full source/history scans and Git checks are repeated at the final revision.
No scanner baseline, finding allowlist, code/type ignore or skipped test is used.

Initial failures were corrected: current Starlette needs httpx2; incomplete PostgreSQL archive
extraction prevented initdb; Windows pipe inheritance blocked a wrapper; a cross-user pytest
cache required a separate owner cache; Windows psutil requires a string disk path; process-tree
measurement must include the venv child. These failures are not reported as passing runs.
The documented complete bootstrap (idempotent repeat), database stop/start, and `doctor`
also passed under process-only RemoteSigned policy; doctor reported actual READY with execution
disabled. The machine's persistent PowerShell execution policy was not changed.

## Clean Windows clone and CI disposition

`python tools/verify_clean_clone.py` passed for source checkpoint
`62d88873d9b24a7fec1b663b4fb20551f9c2433a`: fresh Git clone with `--no-local --no-hardlinks`,
fresh virtual environment and download cache, shared verified Python executable only, new
isolated TEST database and clone-owned migration, full checks and clean final tree. Install
plus clone 70.646 s; whole verification 183.976 s; pytest 145 passed in 46.24 s. Lock SHA256
`0dc9fcb8d19cdda6ce149ec748e4f5ffc01cfecec9b40c75cfe6b64e333148b1`.
The additional invalid-UUID PostgreSQL assertion passed in the working suite (145 tests,
25.91 s). A final-revision clean-clone receipt is also supplied in the delivery/PR.

[CI run 38797754544](https://github.com/haseeb1229/auvexo-alpha/actions/runs/38797754544),
check/job `116638521904`, source SHA above: **FAIL before any steps, no runner assigned**.
GitHub annotation: account payment failures or spending limit prevent starting the job.
This was an external account blocker; the failed attempt produced no hosted test/audit result.
It was resolved for this verification by the owner's explicit temporary public-visibility
change, followed by the actually executed successful rerun below.

At checkpoint `feddb1b5e3f6e757be1d3e816ad97b115d84a455`,
[push run 38798872354](https://github.com/haseeb1229/auvexo-alpha/actions/runs/38798872354)
and [PR run 38798883220](https://github.com/haseeb1229/auvexo-alpha/actions/runs/38798883220)
also initially failed before steps. At the same exact SHA,
[PR run 38798883220 attempt 2](https://github.com/haseeb1229/auvexo-alpha/actions/runs/38798883220/attempts/2)
**PASSED** on 2026-10-16: real PostgreSQL container/migration, locked installation, formatter,
lint, strict typing (15 files), pytest (145 passed in 4.00 s), docs, high-signal source scan,
hash-locked dependency audit (no known vulnerabilities), and final Git diff check.
[Machine-readable CI receipt](evidence/ci-evidence.json) records all steps and their statuses.
[PR #2](https://github.com/haseeb1229/auvexo-alpha/pull/2) remains open, not approved or merged.
Final-head receipts are in that PR body and the delivery report.
Local working tree and diff checks are clean. `git fsck --full` reports no integrity errors;
unreachable staging blobs are retained, not pruned or rewritten.

CI uses a standard Linux
runner with a real digest-pinned PostgreSQL service, read-only token, pinned actions and a
15-minute timeout. Existing repository Actions permissions are read-only and cannot approve PRs.
The billing API returned 404/missing user scope; remaining private Actions allowance is not
visible to this token. No plan, spending limit, paid runner or purchase is configured by this work.
