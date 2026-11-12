# Evidence campaigns

Two campaigns earn genuine operational evidence from scheduled runs in the Operational
checkout: Phase 2 public-data collection (seven consecutive qualifying dates) and Phase 4
PAPER observation (fourteen qualifying dates spanning at least fourteen days). The
qualification rules are frozen in [ADR-013](../adr/013-source-specific-acceptance.md),
the [23:00 schedule](../amendments/SCHEDULER_2300.md) and
[ADR-023](../adr/023-paper-observation-qualification.md).

Evidence is earned only by a scheduled run that starts on time and completes. Nothing
else counts: not a manual run, not a late run, not a catch-up, not a fixture.

## See evidence health without touching it

From the Development checkout, pointing at the Operational checkout:

```text
.venv\Scripts\python.exe tools\evidence_status.py --root "C:\Users\<owner>\Desktop\Auvexo Alpha"
```

The tool only reads files and process state. It never connects to a database, never
writes, and never infers qualification. It reports, per night since the first eligible
date, whether the public-data wrapper completed, failed, missed its start, was refused or
left no summary, and whether the PostgreSQL cluster process is alive.

The authoritative counts come from the database and need the cluster running:

```text
.venv\Scripts\python.exe tools\data_local.py qualification --start-day YYYY-MM-DD
.venv\Scripts\python.exe tools\run_paper_observation.py --config <campaign envelope>
```

Both issue SELECT statements only. Run them in the Operational checkout only as the
owner, outside 20:45-23:20 PKT, because the first takes the collector lease. Do not pass
`--output`.

## When a night fails

1. Do not rerun it. A missed night stays missed.
2. Read the wrapper summary and log in `.local\scheduled-data` in the Operational
   checkout. In the pinned release a collection that ends in a few seconds with
   `DATA_OPERATION_FAILED` usually means the database is not running. From the corrected
   release on ([ADR-031](../adr/031-evidence-semantics-corrections-and-campaign-restart.md))
   every summary carries a `reason`, for example `DATABASE_UNAVAILABLE`,
   `LOCAL_CLOCK_SKEW` or `PROVIDER_FINALITY_DENIED`, and a start outside the pre-window
   leaves a `REFUSED_OUTSIDE_PREWINDOW` summary instead of nothing.
3. Check the cluster: is a `postgres.exe` process running from the Operational data
   directory, and what is the last line in `.local\postgres-data\log`?
4. Check the task's last run time and result in Task Scheduler. A start outside the
   four-minute pre-window is refused by design.
5. Check power and session: AC power, awake, owner signed in, network up.
6. From the corrected release on, check the clock first: collection refuses to run while
   the local clock is more than two seconds away from the provider's.

## Known state on 2026-11-12

See [STATUS](../STATUS.md). The Operational cluster has been down since 2026-10-23,
nothing restarts it after a reboot, and neither campaign is accruing.

## Restarting, which only the owner can authorize

Recorded credit is zero for Phase 2 and at most one date for Phase 4, and the pinned
release cannot complete either campaign: its public-data rights review expires on
2026-11-16, and its PAPER campaign has design limits described in the rebaseline audit.
Restarting on a corrected release therefore costs almost nothing. It needs, in order:

1. the public-data rights review renewed ([rights review](RIGHTS_REVIEW.md));
2. the clock synchronised ([clock trust](CLOCK_TRUST.md));
3. a reviewed release containing the collector and observation corrections, and a
   superseding preregistration for the PAPER campaign;
4. the Operational database started with the canonical tool, and a way to keep it running
   across reboots;
5. the laptop available every evening as described in
   [checkouts and tasks](CHECKOUTS_AND_TASKS.md).

Until then, treat both counters as not accruing. Never backfill, retime or relabel.
