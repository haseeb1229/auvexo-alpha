# Break glass

Use this when something may be compromised or is behaving in a way nobody can explain.
The system holds no broker credential and can place no order today, so the damage that
is possible is to evidence, to local secrets and to the public repository.

## Order of actions

1. **Preserve evidence.** Do not delete, reset or rerun. Copy logs and summaries
   somewhere safe before anything else.
2. **Stop new activity.** Disable the two scheduled tasks in Task Scheduler. Disabling is
   reversible; deleting is not. Record the time.
3. **Revoke before replacing.** For a leaked secret, revoke it at its source first, then
   replace it. Rewriting Git history does not repair a leak, and public copies cannot be
   withdrawn.
4. **Use the broker's own terminal by hand** if an account ever exists and it is safe to
   do so. Never through this system.
5. **Reconcile.** Once an account exists: compare every position and order with the
   broker's record. Broker truth wins.
6. **Restore a known-good release** from a reviewed commit into a new location. See
   [backup and restore](BACKUP_AND_RESTORE.md).
7. **Do not re-enable silently.** Re-enabling tasks, and later any trading mode, is a
   separate explicit owner decision after review.

## Specific cases

| Situation | First action |
| --- | --- |
| A secret or account identifier was pushed to the public repository | Revoke it at the source. Then make the repository PRIVATE (owner), record the exposure, and review what else the commit contained. |
| The laptop was used by someone else, or malware is suspected | Disable the tasks. Treat every local secret as exposed: database passwords, API bearer, DPAPI slots. Rotate them after cleaning the machine. |
| A scheduled task behaves unexpectedly | Disable it. Read its summary and log. Do not edit the Operational checkout to investigate. |
| The database will not start or reports corruption | Stop. Copy the data directory before any repair attempt. |
| An unknown execution outcome, once execution exists | Reconcile first. Never resend. |

## Kill levels

The PAPER kernel has kill levels K1 to K4. The runtime role can raise a level and can
never lower it; only the owner role can resume, and K4 has no clear path in code. A model
or agent cannot clear a kill, change a limit or issue a permit.
