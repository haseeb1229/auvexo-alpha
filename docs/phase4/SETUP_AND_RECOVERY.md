# Phase 4 Checkpoint A one-shot verification and recovery

Use the existing hash-locked Windows environment and owner-protected local PostgreSQL
credentials. Isolated databases receive temporary least-privilege local LOGIN credentials
under ADR-016. No new dependency, external account, broker transport, persistent PAPER
task or paid resource is needed. These are isolated synthetic
engineering commands, not the future >=14-day observation procedure.

## Source and database boundary

Requirements froze at `037afa282daf03eb1d03a1d9a272e5c40bf094a7` before executable
implementation. Migrations 0001-0004 remain unchanged. Forward 0005 adds PAPER-only
tables, immutable histories, separate production/fixture registries and service roles.
One-shot tests create uniquely named isolated TEST/RESTORE databases; they never replace
DEV or the collector's data. Under [ADR-016](../adr/016-paper-direct-login.md), dedicated
least-privilege LOGIN identities inherit separate runtime/owner/truth NOLOGIN groups.
No PAPER pool authenticates as admin or depends on SET ROLE. Private credentials stay in
owner-protected ignored manifests; provisioning and generated-role cleanup are bounded.
Every service connection requests and attests UTC session time, including pooled reuse.
The [second resume clarification](../adr/017-paper-risk-state-corrections.md) binds OPEN to
new positions, quarantines rejection/fill contradictions and latches marked loss across
UTC accounting rollover. Its regressions supplement the frozen acceptance requirements.
The [third resume clarification](../adr/018-paper-observed-mark-freshness.md) preserves the
last observed valuation when a quote or FX becomes stale. The truth writer requires an
independent ORDER or EXTERNAL_POSITION observation to establish instrument scope before a
MARKET_MARK; an initialization-only position does not broaden that writer's read privileges.

The schema-aware foundation diagnostic expects the new head. Unmigrated DEV consequently
reports NOT_READY; this is not permission to deploy an unreviewed migration or enable
execution. The scheduled data collector uses its existing data-only path. Checkpoint
verification does not require applying 0005 to DEV. Do not run the broad DEV/TEST migrate
helper merely to make diagnostics green before independent review.

Preserve the existing `AuvexoAlpha-PublicData-Daily` XML/configuration and genuine receipts.
Do not migrate, restore, run destructive DEV operations or heavy benchmarks during
22:45-23:20 Pakistan. One-shot PAPER tools reject starts in that window; operators must
also budget enough time to finish beforehand. Collector/PostgreSQL availability has priority.

## Verification commands

Run from the repository using the existing environment, with local owner permission to
read its protected development credentials. Never print credentials or copy them to a command.
CI uses its existing synthetic injected PostgreSQL configuration.

```text
python -m ruff format --check src tests tools migrations
python -m ruff check src tests tools migrations
python -m mypy
python -m pytest -q -x tests/test_paper_identity.py
python -m pytest -q tests/test_paper_risk.py tests/test_paper_lifecycle.py
python -m pytest -q tests/test_paper_postgres.py
python tools/verify_recovery.py
python tools/verify_paper_recovery.py
python tools/benchmark_paper.py
node tools/check-docs.mjs
python tools/secret_scan.py
python tools/verify_clean_clone.py
git diff --check
```

For current verification use `python tools/run_tests.py` with the same pytest arguments.
The canonical wrapper uses a unique disposable temporary cache outside managed `.local`
and removes it on success or failure. CI and the clean-clone harness use this wrapper.
Do not override pytest cache paths into managed quota storage: pytest's atomic private
cache directory can retain a creator-only Windows ACL across its rename. The exact
historical project cache remains counted after a narrowly authorized owner read grant;
unexpected unreadable managed paths still fail closed. See [ADR-019](../adr/019-paper-lifecycle-filesystem.md).

The full inherited suite needs a fresh isolated migrated TEST database and its existing
app/data-writer connection configuration; the clean-clone harness provisions that isolation.
For the third resume, follow ADR-018's superseding order: run the originally failing
stale-mark PostgreSQL case first, all hard PostgreSQL correctness cases next, and then
the full direct-LOGIN identity matrix and original cross-foundation/research/schema and
immutable-history attacks. Only then continue the remaining recovery and performance
gates. The command list above is an inventory, not an alternative gate sequence.
A material failure stops verification and requires an evidence handoff.
The [fourth resume](../reference/PHASE_4_FOURTH_RESUME_BRIEF.txt) now supersedes that
sequence: focused lifecycle, filesystem/quota and data/research recovery, all real PG
correctness, full direct-LOGIN security, full inherited suite, then final checkpoint gates.
Missing setup fails rather than skips a test. Do not weaken an assertion to obtain a pass.
Record actual exit codes, sample counts, source SHA, lock hash and any unresolved failure.
Full source/history redacted Gitleaks and a hash-required advisory audit remain mandatory.

## Recovery and reconciliation

Acquire a new writer epoch on process startup, which persists pause-new. Reconcile independent
virtual orders/fills/positions/history before an explicit owner PAPER resume. A new process,
UTC day, loss budget reset or elapsed timeout never clears UNKNOWN, kill state or suspension.
UNKNOWN cannot be dispatched again; its full worst-case reservation stays held. Proven
terminal truth can release only residual capacity; late fills append corrections.

`verify_paper_recovery.py` creates isolated source/restore databases, seeds synthetic partial
and crash/UNKNOWN facts, backs up to ignored local storage and restores without replacing
any existing database. It compares PAPER table hashes/counts and guards, then exercises
restart/reconciliation and retained kill state. The destructive down migration is refused.
Never restore a stale ledger over current virtual truth and assume positions match.

Stop new dispatch before rollback; preserve all journal/truth/reservation/policy/release/
kill records. Prefer a tested forward correction or isolated restore. Same-disk DEV copies
provide no theft/disk-loss or encrypted off-device disaster-recovery proof. No backup medium
is purchased. Raw dumps, private receipts and experiment artifacts remain ignored/local.

## Release and next gate

Keep one Phase 4 PR open and unmerged. The exact-final-SHA owner-local handoff and PR
identify checks, measured misses and remaining gates. Request GPT-5.6 Sol review before
merge or any later owner authorization for persistent observation. No Phase 4 real-environment
day or Phase 5 work follows from these commands. Public exception review remains due
2026-10-24; visibility, billing, runners and permissions are unchanged.
