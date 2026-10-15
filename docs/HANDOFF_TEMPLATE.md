# Phase handoff template

Complete this template for an authorized phase; never infer permission for the next one.

| Field | Required evidence |
| --- | --- |
| Phase/verdict | PASS, PASS-WITH-OPEN-GATES or FAIL; what the verdict certifies |
| Repository | URL, verified visibility, branch, exact base/content/final SHAs, clean/dirty status, push/main comparison |
| Scope | Authorized purpose, files changed, implementations vs design only, requirement IDs |
| Product/design | Relevant architecture, stack, authority, venue/mode, client and extension boundaries |
| Validation | Commands, tool versions, results, evidence paths, measured vs estimated claims |
| Safety/security | Risk/live gates, permissions, secrets/dependencies/licenses, no-action confirmations where relevant |
| Resources/cost | RAM/disk/latency, free-first impact, actual purchases or none |
| Decisions | Frozen changes, provisional/deferred/external gates with owner and closure point |
| Recovery | Migration/rollback/backup implications, unresolved incidents |
| Next gate | Exact independent evidence required, genuine owner actions, no automatic phase advancement |

Avoid circular commit claims: a handoff commit may identify the preceding content SHA;
record its own final SHA in an external delivery receipt or resolve it through Git. Never
write a guessed self-referential commit hash or claim a push before it succeeds.
