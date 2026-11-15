# Phase 2 public-data campaign v2: semantics

Status: PROPOSED on 2026-11-13. Takes effect only on a release the owner re-pins and a
separate owner START. Dates earned under v2: zero.

The Phase 2 operational gate is seven genuine consecutive qualifying dates
([ADR-013](../adr/013-source-specific-acceptance.md),
[23:00 schedule](../amendments/SCHEDULER_2300.md)). Under the pinned release the count is
zero and cannot grow: no scheduled run has completed, and the rights compiled into it
expire on 2026-11-16. This page says what a date means on a corrected release. It edits
none of the frozen documents above.

## Unchanged

- Schedule `public-data-2300-pkt-v1`: warm-up 22:57, qualification window 23:00-23:12
  Asia/Karachi ([18:00, 18:12) UTC), the same task principal and limits.
- Per-day thresholds: DS-02 REST, 1-minute, both symbols, complete PASS coverage,
  receipt lag at most 120 s, at least 11 observations per symbol over at least 600 s, no
  heartbeat gap over 120 s, no duplicates.
- Seven genuine consecutive dates. Nothing earlier transfers; no catch-up, backfill,
  retime or relabel.

## What v2 adds

Each rule makes a date harder to earn, never easier.

| Rule | Source | Effect on a date |
| --- | --- | --- |
| Provider-time finality, local clock within 2 s of provider time | ADR-031 rule 1 | Polls that cannot prove both are refused with a reason; the window may then fail coverage. |
| Exactly one completed scheduled wrapper summary from the pre-window | ADR-031 rule 2 | Manual or extra runs cannot make a date. |
| Every invocation leaves a summary with a reason | ADR-031 rule 3 | Failures are visible, not silent. |
| Catch-up only in the warm-up | ADR-031 rule 4 | An outage does not poison later windows. |
| Reviewed provider gap inside the day | [ADR-033](../adr/033-data-and-research-integrity.md) | The day can never qualify. |
| Cooldown on any host touching the day | ADR-033 | The day can never qualify. A failed day stays failed. |
| Archive/REST conflict for a bar of the day | ADR-033 | Recorded and visible; research reads of the conflicting version refuse. Qualification of the live window is about collector reliability and is not changed by a later archive. |
| Trusted clock at run start | [clock trust](../runbooks/CLOCK_TRUST.md) | Recommended START precondition (see below). |

## START preconditions

1. DS-01/DS-02 rights renewed by the owner
   ([packet](../reviews/BINANCE_DS01_DS02_RIGHTS_OWNER_PACKET_2026-11-13.md)), in a
   reviewed release.
2. The owner re-pins the Operational checkout to that release and migrates its database
   from `0005_paper_core` to the release head, after a backup.
3. Windows Time configured so that it stays synchronised (exact commands in the
   [restart candidate](../reviews/OPERATIONAL_CAMPAIGN_RESTART_CANDIDATE_2026-11-13.md)).
4. The database kept running across reboots
   ([autostart candidate](../runbooks/POSTGRES_AUTOSTART.md)) and the laptop on AC, awake,
   online and signed in at 22:57 each night.
5. A new first eligible date, chosen at START, no earlier than the day after it.

## Residual

The wrapper binds a date to one scheduled summary, but cannot prove that Task Scheduler,
not a person, launched it inside the pre-window. ADR-031 states that residual. The PAPER
campaign v2 closes the same gap with the Task Scheduler log
([ADR-032](../adr/032-paper-evidence-campaign-v2.md), OBV2-06); extending that check to
this wrapper is recommended before START and tracked in the restart candidate.
