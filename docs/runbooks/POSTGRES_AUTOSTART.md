# PostgreSQL autostart candidate

The Operational cluster stopped on 2026-10-23 and nothing restarted it, which ended both
evidence campaigns without anyone noticing. This page describes a candidate fix. It is
**not installed**. Installing it is an owner action and part of a campaign restart.

## What the candidate does

`tools/pg_autostart_task.py` writes a Task Scheduler definition and nothing else. It
never registers, starts or stops anything.

| Property | Value | Why |
| --- | --- | --- |
| Action | `pg_ctl -D <checkout>\.local\postgres-data -l <checkout>\.local\postgres-start.log -w -t 60 start` | Starts an existing cluster only. No initialisation, no SQL, no Python, no repository code, so it does not depend on which release is pinned. |
| Triggers | At owner logon (2 minute delay), and daily at 20:35 Asia/Karachi | Logon covers reboots; the daily trigger covers a cluster that stopped while the owner stayed signed in. 20:35 is before the 20:45 protected window and the 21:00 PAPER run. |
| Principal | The interactive owner, least privilege, no stored password | Same principal model as the evidence tasks. |
| Already running | pg_ctl exits non-zero and changes nothing | Safe to trigger repeatedly. |
| Port held by another server | The new postmaster fails to bind; the log says so | It never takes another cluster's port. |
| Hard terminate | Disabled | Ending the task must not be able to kill a running cluster. |

Generate it from the Development checkout:

```text
.venv\Scripts\python.exe tools\pg_autostart_task.py --owner <DOMAIN\user> ^
  --checkout "C:\Users\<owner>\Desktop\Auvexo Alpha" --first-day YYYY-MM-DD ^
  --output <scratch folder>\postgres-autostart.xml
```

## The open question, and how the owner settles it

A 2026-11-13 experiment on a scratch cluster showed that a postmaster started by
`pg_ctl` **dies** when a kill-on-close job object holding `pg_ctl` is closed, with or
without breakaway allowed. Whether Task Scheduler closes such a job when the action
exits normally could not be tested without registering a task, which this run was not
authorized to do. So after installation the owner must check, once:

1. Install: `schtasks /Create /XML <file> /TN AuvexoAlpha-PostgreSQL-Autostart`.
2. Sign out and in again, wait three minutes.
3. Run `tools\evidence_status.py --root <Operational checkout>` from Development.
   `postgresql_cluster.process` must be `RUNNING`. Check again ten minutes later.
4. If it reports `NOT_RUNNING`, delete the task (`schtasks /Delete /TN
   AuvexoAlpha-PostgreSQL-Autostart`). Do not keep a task that starts and immediately
   loses the cluster. The fallback is a Windows service registered with `pg_ctl register`,
   which needs an administrator and its own review because it runs under a service
   account and changes data-directory permissions.

## What this does not fix

It does not keep the laptop awake, on AC power or signed in. It does not repair a cluster
that fails to start; the log does that job. It does not back anything up
([backup and restore](BACKUP_AND_RESTORE.md)).
