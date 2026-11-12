# Runbooks

Short, current procedures. [STATUS](../STATUS.md) says what is true now; these say how to
act. Phase-specific runbooks that were frozen with their designs stay where they are and
are linked from here.

| Runbook | Use it when |
| --- | --- |
| [Checkouts and scheduled tasks](CHECKOUTS_AND_TASKS.md) | You need to know which folder does what and what must never be touched |
| [Local verification](LOCAL_VERIFICATION.md) | You changed code or documents and need to prove it |
| [Evidence campaigns](EVIDENCE_CAMPAIGNS.md) | A scheduled night failed, or you need to see evidence health without touching it |
| [Clock trust](CLOCK_TRUST.md) | Time quality matters: observation, qualification, open-interest START |
| [Backup and restore](BACKUP_AND_RESTORE.md) | Before any risky operational change; after loss |
| [Break glass](BREAK_GLASS.md) | Suspected compromise, leaked secret or unexplained behaviour |
| [Release and merge](RELEASE_AND_MERGE.md) | Publishing a branch and merging a pull request |
| [Rights review](RIGHTS_REVIEW.md) | A source rights review is due |
| [Local state](LOCAL_STATE.md) | You need to know what lives under `.local/` and what is safe to delete |

Frozen phase runbooks:

- [Phase 1 setup](../phase1/SETUP.md) and [toolchain](../phase1/TOOLCHAIN.md)
- [Phase 2 setup and recovery](../phase2/SETUP_AND_RECOVERY.md) and the
  [23:00 schedule](../amendments/SCHEDULER_2300.md)
- [Phase 4 setup and recovery](../phase4/SETUP_AND_RECOVERY.md) and
  [observation runbook](../phase4/OBSERVATION_RUNBOOK.md)
- [Phase 5 offline runbook](../phase5/OFFLINE_RUNBOOK.md)
- [Phase 6 open-interest runbook](../phase6/OPEN_INTEREST_RUNBOOK.md),
  [runtime deployment](../phase6/OI_RUNTIME_DEPLOYMENT.md) and
  [rights review continuity](../phase6/RIGHTS_REVIEW_CONTINUITY.md)
- [Phase 7 read-only terminal runbook](../phase7/READ_ONLY_RUNBOOK.md)
- DS-03 [synthetic](../phase2/DS03_RUNBOOK.md) and
  [actual adapter](../phase2/DS03_ACTUAL_ADAPTER_RUNBOOK.md) runbooks
