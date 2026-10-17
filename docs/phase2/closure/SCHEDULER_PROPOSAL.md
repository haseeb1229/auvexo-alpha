# Approved scheduled collection plan

Prepared 2026-10-17 for the evidence-closure brief. No persistent task was found in
the initial Auvexo task-name/working-directory inventory. On 2026-10-17 the owner
explicitly answered **Approve this task after verification** to this exact plan.
Approval is not registration or seven-day proof; see the dated scheduler receipt.

- Name: `AuvexoAlpha-PublicData-Daily`; owner: `DESKTOP-GQ5153T\AR TRADERS`.
- Executable: `C:\Users\AR TRADERS\Desktop\Auvexo Alpha\.venv\Scripts\python.exe`.
- Arguments: `tools/run_daily_window.py --scheduled`.
- Working directory: `C:\Users\AR TRADERS\Desktop\Auvexo Alpha`.
- Schedule: daily **04:57** Pakistan Standard Time (UTC+05:00), first eligible future
  day. Two bounded warm-up cycles run before the unchanged **05:00–05:12** window.
  This starts the task three minutes earlier than the old setup guidance; the evidence
  window and its thresholds are unchanged. A daily restart can otherwise first publish
  an old checkpoint's backfill as STALE during the qualification window.
- Identity: existing owner interactive session, LIMITED privilege, no stored logon
  password, no elevation. Owner must remain logged in; database must already be ready.
- Settings: one instance (IgnoreNew); no retries or late catch-up; request WakeToRun;
  require available network; AC power; stop after 20 minutes and stop process descendants.
  Wake is a request, not a guarantee that a powered-off/offline laptop can collect.
- Wrapper: existing public-data CLI only; warm-up child deadline 150 seconds, wait
  until midnight UTC, then 12 cycles on monotonic cadence with a 13-minute child deadline.
  Late/outside-window starts refuse; no account APIs, secrets in arguments or automatic
  DB provisioning. Warm-up states remain visible outside the qualifying window.
- Output: owner-restricted ignored `.local/scheduled-data` directory; exclusive dated
  run logs and summaries. Maximum 1 MiB per log, 20 MiB directory budget; rotate only
  wrapper logs older than 14 days. Preserve summaries and all accepted DB/data provenance;
  refuse further work if the directory budget cannot be met safely.
- Preflight: `tools/run_daily_window.py --preflight` runs bounded local verification
  without public collection. Default invocation prints the plan without running a child.

The separate explicit owner approval above authorizes registration. Before
registration, verify the wrapper tests and preflight, timezone, identity and exact action.
After approval, inspect actual registered settings and the next run time. Do not report
registration until those checks succeed. Qualification remains zero until real scheduled
observations satisfy the unchanged 00:00–00:12 UTC gate on seven consecutive dates.

Owner action: keep this laptop logged in, awake/online and on AC during each window.
October 17 was missed. If October 18 is missed, select the next actual qualifying start;
never backdate or count the retrospective archive test as scheduled operation.
