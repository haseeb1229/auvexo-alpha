# Phase 2 setup, collection and recovery

Use the existing native Windows bootstrap and PostgreSQL installation from
[Phase 1 setup](../phase1/SETUP.md). No Docker, GPU, paid service, account signup,
broker terminal or network-facing server is required. Run from the repository root
under the owner account. Never put passwords in command arguments or chat.

```powershell
.venv/Scripts/python.exe tools/local_db.py start
.venv/Scripts/python.exe tools/local_db.py migrate
.venv/Scripts/python.exe tools/data_local.py provision
.venv/Scripts/python.exe tools/data_local.py verify
```

Provision creates a separate random local development data-writer password in an
owner ACL-protected ignored file. This is a PostgreSQL development credential only;
it is not an encrypted broker secret store or a claim of service isolation. The role
inherits only ingestion metadata rights and cannot change execution policy or schema.
The runner passes it through the child environment, never stdout or argv. Do not
grant that role membership in the migrator or diagnostic identity.

Collection is explicitly opt-in and bounded per invocation:

```powershell
.venv/Scripts/python.exe tools/data_local.py history --enable-public-data --symbol BTCUSDT --interval 1h --period 2024-12-31 --period 2025-01-01 --output .local/btc-boundary.json
.venv/Scripts/python.exe tools/data_local.py specs --enable-public-data --output .local/spot-specs.json
.venv/Scripts/python.exe tools/data_local.py collect --enable-public-data --cycles 12 --output .local/public-window.json
.venv/Scripts/python.exe tools/data_local.py coverage --output .local/coverage.json
.venv/Scripts/python.exe tools/data_local.py evidence --output .local/dataset-evidence.json
.venv/Scripts/python.exe tools/data_local.py qualification --start-day 2026-10-18 --output .local/qualification.json
```

Choose a new output filename for each invocation: receipts are never overwritten.
History supports at most twelve explicit daily/monthly periods per invocation; it does
not choose an arbitrary age horizon. The live loop stops after its cycle budget or
Ctrl+C. A network/DB/quota failure returns nonzero and cannot imply healthy collection.
Read durable data events for source failure reasons. Provider rate/access restrictions
stop the collector and persist a cooldown; do not evade this with alternate hosts/IPs.

## Seven scheduled collection days

Current schedule supersedes the dated morning proposal/receipt: daily **22:57 Pakistan
warm-up / 17:57 UTC**, qualifying **23:00-23:12 Pakistan / 18:00-18:12 UTC**.
Use the [current schedule and inspected registration](../amendments/SCHEDULER_2300.md),
not direct collection as a Task Scheduler action. The shared `application/data_schedule.py`
defines the window and first eligible date, **2026-10-18**. October 17's new start was already
past at entry; no rush, backdating or late catch-up. Old 04:57/05:00 receipts remain historical.

At least eleven genuine verified fresh observations per symbol must span >=600 seconds with
no heartbeat gap >120 seconds, within [18:00,18:12) UTC. Final manifest/hash/artifact/source/
quality/receipt checks and duplicate refusal remain mandatory. Report only seven actual
consecutive calendar dates, never retrospective archives, daytime pilots or fixtures.

The existing `AuvexoAlpha-PublicData-Daily` task uses `.venv/Scripts/python.exe` with
`tools/run_daily_window.py --scheduled`, this repository as working directory, Limited
interactive owner identity, IgnoreNew, no retry/late catch-up, network+AC, requested wake
and a 20-minute cap. The wrapper retains bounded warm-up/child/output limits and owner-only
logs/summaries. Inspect actual registration rather than assuming settings from this prose.

Owner prerequisite: logged in and awake, online/on AC, Auvexo PostgreSQL already running.
ChatGPT/Astra/Claude need not be open; the local Windows task runs independently of model
usage limits. Ready/configured is not observation. The twelve-minute/day check qualifies
bounded collector reliability, never 24/7 uptime or live-trading readiness. Missing days
remain gaps. After seven actual windows, select the genuine first date and inspect evidence.
Full Phase 2 operational status remains OPEN. After ADR-013 independent acceptance and a
new scoped prompt, non-money engineering may overlap evidence collection on accepted inputs.

For the independent Gitleaks 8.30.1 source/history scan, use the root `.gitleaks.toml`
configuration. Export tracked/untracked nonignored source to an isolated directory,
then scan that export and Git history. Runtime credentials belong in ignored owner
storage and are not part of the source export. The narrow public-identifier exception
and detection controls are documented in [verification](VERIFICATION.md).

The actual scheduled count remains zero as of this amendment. Monotonic cadence is unchanged;
slow processing or late startup can still leave a window incomplete. Preserve that result.

## Recovery and rollback

Stop collection before backup. Run:

```powershell
.venv/Scripts/python.exe tools/verify_data_recovery.py
.venv/Scripts/python.exe tools/verify_recovery.py
```

The data recovery tool locks writers, snapshots the metadata and referenced raw/Parquet
artifacts, restores into a new isolated database, compares eight tables, verifies all
hashes and restored immutable triggers, then removes only that newly created restore
database. Its local backup remains in `.local/data-recovery-*`. Never treat that same-disk
DEV copy as encrypted/off-device disaster recovery. No money can be enabled on restore.

An interrupted publication can leave an unreferenced file. `verify` counts orphans but
never adopts them. Re-import the exact source to publish consistently. Missing/corrupt
accepted data blocks verification; restore the matching hash from backup or retain the
failure and re-acquire the exact source. Do not overwrite an accepted manifest or change
its checksum. Provider replacement bytes are a correction, not recovery of old bytes.

Only `.stage` files are regenerable cleanup candidates; the store's cleanup method holds
the publisher lock, checks containment and never deletes accepted files or provenance.
At storage pressure stop backfills/optional collection first. The 120/135/150 GB managed
thresholds and 60/40/20 GB free-space thresholds are enforced conservatively. No automatic
age deletion or secret quota bypass is available.

Rollback means stop collection, preserve new forward schema and evidence, restore into
an isolated instance or forward-fix. `alembic downgrade` is deliberately refused. Do not
run Phase 1 code against a newer schema and call readiness green.

Exness remains disabled. To revisit it, the owner must provision a dedicated DEMO
terminal/profile and explicitly authorize read-only source onboarding on this machine.
The implementation must first establish encrypted OS storage, process/service isolation,
current terms/compatibility and genuine terminal-reported DEMO attestation. A filename,
label, booleans, or imported vendor SDK is insufficient. No passwords in chat, no real
account and no order transport are authorized in this phase.
