# Current Phase 2 daily public-data schedule

Owner explicitly authorized this retiming in the [baseline brief](../reference/BASELINE_CORRECTION_BRIEF.txt)
on 2026-10-17. It supersedes the clock in the dated
[morning proposal](../phase2/closure/SCHEDULER_PROPOSAL.md) and
[old registration receipt](../phase2/closure/evidence/scheduler.json); those remain unchanged
historical facts. The generic brief verification line about no scheduler mutation is resolved
in favor of its specific retiming authorization. All other constraints must remain identical.

Daily warm-up: **22:57 Pakistan Standard Time (UTC+05:00) / 17:57 UTC**.
Qualification: **23:00-23:12 Pakistan / [18:00,18:12) UTC**.
Canonical schedule ID: `public-data-2300-pkt-v1` in
[`application/data_schedule.py`](../../src/auvexo_alpha/application/data_schedule.py).
First eligible date **2026-10-18**: October 17's start was already past at entry.
No manual scheduled run, backdating, rush or late catch-up is used.

The wrapper permits its existing bounded four-minute prewindow tolerance, normally starts
three minutes early, uses two warm-up cycles with a 150-second deadline, waits until 18:00
and refuses a collection start more than 15 seconds late. Collection remains twelve cycles
with a 780-second child deadline. Qualification closes at 18:12, independently of child exit.
Warm-up or postwindow output cannot qualify. One MiB/log and 20 MiB directory budgets,
14-day rotation of wrapper logs only, preserved summaries/data, and owned-child termination
on deadline/output overflow remain unchanged.

Qualification requires actual verified manifests/artifacts, DS-02 REST source/1m/symbol
identity, complete PASS coverage, receipt/processing order and <=120-second receipt lag;
>=11 distinct observations per symbol, >=600-second span and no >120-second heartbeat gap.
Duplicate events/dataset versions fail. Seven genuine consecutive dates are required;
archive coverage, fixtures, daytime pilots, morning observations and future dates never count.
The actual count at amendment entry is **[] (0)**. A new observation report and actual task
inspection are linked from the [consolidated handoff](BASELINE_CORRECTION_HANDOFF.md).

Actual [retiming receipt](evidence/scheduler-2300.json): inspected 2026-10-17 at 18:15:55 UTC,
task **Ready**, next run **2026-10-18 22:57 Pakistan / 17:57 UTC**. Exported XML comparison
confirmed only StartBoundary and description changed. Local-only preflight passed; no scheduled
run was started. [Current qualification](evidence/observation-2300.json) is OPEN with zero events.

Task remains `AuvexoAlpha-PublicData-Daily`, Limited interactive owner identity, no stored
password/elevation, IgnoreNew, no retries or late catch-up, network+AC required, stop on battery,
wake requested and 20-minute outer limit. Exact action, arguments, working directory, next run
and log ACL must be read from the actual registered-task receipt after retiming. Ready/configured
is not successful collection. No unrelated task, service, runner or power policy is changed.

Owner prerequisite: laptop logged in and awake, online, on AC, and Auvexo PostgreSQL already
running. ChatGPT/Astra/Claude need not be open; this Windows-local task runs independently of
model usage limits. Wake is a request, not reliable recovery of a sleeping/offline laptop.

This twelve-minute/day check is bounded collector reliability qualification, never 24/7 uptime
or live-trading readiness. After independent ADR-013 acceptance and a new scoped prompt, it
may run alongside non-money engineering on accepted inputs. Full Phase 2 operational status
and all activation/source gates stay OPEN until applicable genuine evidence is complete.
