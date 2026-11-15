# Operational campaign restart candidate, 2026-11-13

> Dated record. The current state is in [STATUS](../STATUS.md). This is a candidate plan
> for the owner. It authorizes nothing: no re-pin, no database start, no task change, no
> START. A machine-readable copy is in the
> [JSON file](OPERATIONAL_CAMPAIGN_RESTART_CANDIDATE_2026-11-13.json).

## Where things stand

| Item | State on 2026-11-13 |
| --- | --- |
| Operational checkout | Pinned at `9b9038b`, clean. Unchanged by this run. |
| Operational PostgreSQL | Down since 2026-10-23 11:58 PKT. Nothing restarts it. |
| Phase 2 genuine dates | Zero. |
| Phase 4 PAPER dates | At most one; exact count unreadable while the database is down. |
| Pinned release | Cannot complete either campaign ([ADR-031](../adr/031-evidence-semantics-corrections-and-campaign-restart.md), [ADR-032](../adr/032-paper-evidence-campaign-v2.md)). Its DS-01/DS-02 rights expire 2026-11-16 00:00 UTC. |
| Rights | Owner renewed DS-01/DS-02 on 2026-11-14 until 2027-02-16 ([record](BINANCE_DS01_DS02_RIGHTS_RENEWAL_2026-11-14.md)), in code after the pinned release. |
| Clock | Configured by the owner on 2026-11-14 (automatic, 900 s, `time.windows.com`). Still leap 3 and never synced since on 2026-11-15 01:51 PKT: NTP replies mostly lost on this network, about 4 s fast. |
| Task Scheduler history log | Disabled. |
| OI Runtime checkout | Pinned at `f47770d`, unchanged. Not part of this restart. |

## Target release

The release to pin is `d90e70b5e096cfd6daf83c436b6ed071d625ed14`, the `main` merge
commit of the OD-23 closure pull request #15 (2026-11-15). It contains the engineering
corrections, the ADR-032 campaign v2 implementation, the DS-01/DS-02 renewal and the
independent review in [the review record](OD23_INDEPENDENT_REVIEW_2026-11-15.md). Later
documentation-only commits on `main` do not change it. Do not re-pin to anything else
without a new reviewed candidate.

## Owner steps, in order

Every step is an owner action. Do them outside 20:45-23:20 PKT unless noted.

1. **Rights**: done on 2026-11-14
   ([record](BINANCE_DS01_DS02_RIGHTS_RENEWAL_2026-11-14.md)).
2. **Clock**: configuration done on 2026-11-14. Remaining: a network path on which NTP
   (UDP port 123) gets replies, then `w32tm /resync` in an elevated prompt. Confirm with
   `tools\oi_clock_status.py` from Development that leap, stratum, sync age and bound pass.
3. **Enable the Task Scheduler history log** (elevated), which both v2 campaigns need to
   prove a scheduled rather than manual start:
   `wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true`
4. **Start the Operational database once and read what v1 earned**, with the pinned
   release, before anything changes:
   `.local\toolchains\postgres\pgsql\bin\pg_ctl.exe -D .local\postgres-data -l .local\postgres-start.log -w start`
   in the Operational checkout, then the read-only PAPER count from
   [evidence campaigns](../runbooks/EVIDENCE_CAMPAIGNS.md). Record the number. It is
   final for v1 and does not transfer.
5. **Back up** following [backup and restore](../runbooks/BACKUP_AND_RESTORE.md): every
   database with `pg_dump -Fc`, roles with `pg_dumpall --globals-only`, the artifact
   directories and summaries; encrypt with a key not stored on the laptop; store off the
   device; record hashes. The research ledger holds the only record that both Phase 3
   holdouts are consumed.
6. **Re-pin** the Operational checkout to the target commit: fetch, detached checkout of
   the exact SHA, confirm a clean tree, rebuild its environment with
   `uv sync --locked --group provider` in copy mode.
7. **Migrate** the main chain from `0005_paper_core` to `0007_paper_state_guards` with
   the release's own tool. Neither `0006` nor `0007` rewrites a row. `0007` adds a unique
   index on (account, logical key) and a check that a reservation is active exactly when
   not released; PostgreSQL validates both against the existing v1 PAPER rows. Rehearse
   the migration first on a throwaway cluster restored from the step 5 backup. If either
   fails there, stop: it means v1 state the kernel did not expect, and it needs review
   before anything else. Then run the recovery drills on that throwaway cluster, not on
   the Operational one.
8. **Install the database autostart task** and do its one-time check
   ([autostart candidate](../runbooks/POSTGRES_AUTOSTART.md)). Remove it if the cluster
   does not stay running.
9. **Prepare campaign v2**: a new PAPER observation database at `obs0002_campaign_v2`
   and campaign identity under ADR-032, with specifications pinned from the provider's
   current terms; a new Phase 2 campaign identity
   ([v2 semantics](../phase2/PUBLIC_DATA_CAMPAIGN_V2.md)); and regenerated task
   definitions (`paper.observation.task.v2`) with a first eligible date no earlier than
   the day after START. The old v1 observation database stays as it is, as v1 evidence;
   v1 can no longer prepare or begin a run.
10. **Scheduler dry run.** With the log enabled, let each task fire once from its trigger
    outside a counting date and confirm that the log shows the time-trigger, process
    creation and instance identifiers the provenance check reads. If a field is missing
    the night is UNVERIFIABLE, never a pass, so this must be confirmed before START.
11. **Independent review** of the pinned commit, the prepared campaign hashes and the task
    definitions.
12. **START**, as a separate explicit owner act. The START record binds one audited owner
    resume that leaves the account flat, reconciled and at K0, and the standing resume
    authority of ADR-032 OBV2-01 (campaign hash, reviewed commit, valid-through date). From
    then on: laptop on AC, awake, online and signed in from 20:45 to 23:20 PKT every
    evening. A missed night stays missed.

## What restarting costs

Nothing earned is lost: Phase 2 has zero dates and the pinned release cannot add any;
Phase 4 has at most one, which does not transfer under any option, because evidence
earned under different semantics cannot be merged.

## Risks the owner should know

- With the clock about 4 s fast and no working NTP path, the 2 s collection bound and
  the per-run clock gate both refuse every night until step 2 is complete.
- Round trips to Binance from this host measured 0.3 to 4.8 s. Slow polls can miss bars;
  the gap and receipt rules record that instead of hiding it.
- The autostart task's behaviour under Task Scheduler is unproven until step 8's check.
- One Windows user holds every database role's secret (ADR-032, P-15). Acceptable for
  PAPER; to be revisited before any broker credential.
