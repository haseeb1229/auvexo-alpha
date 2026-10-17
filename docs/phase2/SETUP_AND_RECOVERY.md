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
.venv/Scripts/python.exe tools/data_local.py qualification --start-day 2026-10-17 --output .local/qualification.json
```

Choose a new output filename for each invocation: receipts are never overwritten.
History supports at most twelve explicit daily/monthly periods per invocation; it does
not choose an arbitrary age horizon. The live loop stops after its cycle budget or
Ctrl+C. A network/DB/quota failure returns nonzero and cannot imply healthy collection.
Read durable data events for source failure reasons. Provider rate/access restrictions
stop the collector and persist a cooldown; do not evade this with alternate hosts/IPs.

## Seven scheduled collection days

The qualification command expects a genuine twelve-minute collection window starting
00:00 UTC each day (05:00 Asia/Karachi), for seven consecutive dates selected by the
operator. At least eleven fresh observations per symbol must span ten minutes, with
no heartbeat gap exceeding 120 seconds. The window qualifies scheduled collection,
not 24-hour uptime, quote latency or Exness access. A future event, fixture, compressed
clock, missing day or stale observation cannot count as elapsed proof. The initial
observation gate is OPEN; no task is silently registered or promised asynchronous work.

For an operator-run Windows Task Scheduler task, select the owner identity, start in
this repository, run hidden, one instance only, daily at 05:00 local time, and set a
20-minute execution limit. Use `.venv/Scripts/python.exe` with arguments
`tools/data_local.py collect --enable-public-data --cycles 12`. The database stores
append-only daily receipts without requiring a reused output filename. Keep the
laptop awake and connected during the window. A missed start remains missing; enabling
"run as soon as possible after a missed start" does not make a late receipt qualified.
After seven actual windows, run qualification with the real first date and independently
inspect manifests, events, downtime and source quality. Task registration/identity remains
an explicit operator action; credentials are not embedded in task arguments.

For the independent Gitleaks 8.30.1 source/history scan, use the root `.gitleaks.toml`
configuration. Export tracked/untracked nonignored source to an isolated directory,
then scan that export and Git history. Runtime credentials belong in ignored owner
storage and are not part of the source export. The narrow public-identifier exception
and detection controls are documented in [verification](VERIFICATION.md).

As of 2026-10-17, the proposed October 17 window was missed: zero qualifying windows.
Choose a new real start date (for example October 18 if actually scheduled) instead of
counting the daytime pilot. The implementation uses monotonic cadence rather than adding
a full minute after each processing cycle. Slow processing or late startup can still
leave a window incomplete; the report must retain that result.

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
