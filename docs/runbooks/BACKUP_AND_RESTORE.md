# Backup and restore

## What exists today

Restore drills exist; a backup routine does not.

- `tools/verify_recovery.py`, `tools/verify_data_recovery.py`,
  `tools/verify_paper_recovery.py` and `tools/verify_observation_recovery.py` dump a
  database, restore it into a freshly generated database, compare, re-test the
  append-only triggers and drop only what they created. They prove that a dump can be
  restored on the same cluster.
- Nothing is scheduled. Dumps are unencrypted, stay on the same disk and do not include
  roles or passwords. No restore into a fresh cluster has been proven.
- Off-device encrypted backup is an open owner gate (OD-06) and is required before
  Phase 8.

So the loss of this disk would lose the research ledger, including the record that both
Phase 3 holdouts are consumed, the collected data and any observation receipts.

## What to protect

| Asset | Where | Why |
| --- | --- | --- |
| Operational PostgreSQL cluster | `.local/postgres-data` in the Operational checkout | Research ledger, data events, PAPER journal, observation receipts |
| Market data artifacts | `.local/market` and `.local/observation` in the Operational checkout | Hash-verified raw and Parquet files referenced by manifests |
| Scheduled-run summaries | `.local/scheduled-data` | Evidence of what ran |
| Local secrets | `.local/*-secrets.json`, `.local/paper-identities`, DPAPI files under the user profile | Needed to read a restored cluster; never back up beside the data unencrypted |
| Campaign envelope | `.local/phase4/checkpoint-b/.../campaign-envelope.json` | Binds the campaign |

## Minimum safe manual backup, owner only

Outside 20:45-23:20 PKT, with no scheduled run active:

1. dump each database with `pg_dump -Fc` and the roles with `pg_dumpall --globals-only`;
2. copy the artifact directories;
3. encrypt the archive with a key that is not stored on the laptop;
4. store it off the device;
5. record the archive hash and date.

Never restore into the Operational cluster. Restore into a new, isolated cluster, verify
hashes and append-only triggers, and reconcile before trusting anything. A restored
copy can never mint observation dates; the qualification schema refuses it.

## After a restore

Recovery never re-enables anything by itself. Start in inspection-only mode, verify the
ledger hash chains, compare manifests with files, and record the event.
