# Phase 7 read-only foundation independent acceptance

Date: 2026-10-23. Independent reviewer: GPT-5.6 Sol, disposition supplied in the
owner's acceptance/merge/private-gate/operational-diagnostic/Phase6A brief.
This records supplied independent acceptance, not an implementer self-review.
Brief SHA256: 6aae9afbbce5e451f64848607776d6d129d9711172ba474e20c03f3117dbe65a.

Accepted executable source: `4418df01128b08e6ac18a79e9f967f7c5364b1b3`.
Base main: `1d6b08fc36884f1bc4845ac54111776d80df056b`.
[PR #8](https://github.com/haseeb1229/auvexo-alpha/pull/8) entered OPEN/UNMERGED/mergeable.
PHASE 7 READ-ONLY OPERATOR TERMINAL FOUNDATION ENGINEERING = ACCEPTED/PASS.
Full Phase 7 operational acceptance remains OPEN.

## Reviewed history

All seven commits are founder-authored/committed by Muhammad Haseeb
<abdulhaseeb1229@gmail.com>, without AI trailers or history rewrite:

1. `25f7db6e629b767fd2698902658c5d789e597ee6`: draft read-only scope.
2. `0df3784a3e3bb3b39a43cc132bb2859738ea71f9`: freeze with approved static bootstrap.
3. `9052472bca1ec9263bf3dfd4e6d049d43b9775e8`: loopback terminal and contracts.
4. `260f0ce4384391c24366c99522f6ee7eda07552f`: LF frontend checkout policy.
5. `6df5634215057a08503261b1c57e3fcf13e36d09`: actual read identity and CI endpoint.
6. `8c567520a154af69610a4c66909f2528a77d757a`: CI host SCRAM requirement.
7. `4418df01128b08e6ac18a79e9f967f7c5364b1b3`: certifi audit-export synchronization.

## Accepted correction and verification

The prior configured-URL/narrow-ACL check did not establish least privilege. Every
connection now attests actual session_user/current_user, database, 127.0.0.1:55432,
UTC, repeatable-read/read-only and public-only search path. A dedicated LOGIN with
NOINHERIT and no elevated flags, memberships, ownership or CREATE/TEMP is required.
Exactly paper_account, paper_reservation, paper_outbox and paper_journal in public
must have SELECT. Extra relation/column reads, writes/grant options, sequences and
executable application SECURITY DEFINER functions are denied before projection.
Pool reuse reattests. Failure returns UNAVAILABLE. No operational DB integration.

Only the data-free loopback shell/assets omit bearer; every /api/v1 endpoint remains
protected. Tokens are runtime/memory/Authorization-header only. No command, money,
activation, broker or arbitrary SQL/file route exists. Presentation preserves unknown truth.

| Evidence at accepted source | Result |
| --- | --- |
| [Push run 39813071767](https://github.com/haseeb1229/auvexo-alpha/actions/runs/39813071767), job 119944251803 | SUCCESS; 1711 Python passed in 78.34s; 31 frontend passed |
| [PR run 39813079208](https://github.com/haseeb1229/auvexo-alpha/actions/runs/39813079208), job 119944279421 | SUCCESS; 1711 Python passed in 110.67s; 31 frontend passed |
| Focused Windows verification | 151 passed: 58 real-PG (50 new), 59 API/security, 34 boundary/config |
| Exact-final fresh Windows clone | 1711 Python unskipped and 31 frontend passed; clean tree |
| Statics/documentation/security | Ruff, strict mypy 70 sources, docs, aligned instructions, source/history and high-signal scans PASS |
| Dependency audits | Hash-required Python: 69 dependencies, zero reported vulnerabilities; npm: zero |

Certifi 2026.7.22 caused a security STOP. The owner authorized only certifi 2026.10.19
and its lock/audit hashes. The owner separately approved the same pinned CI PostgreSQL
image on the strict loopback endpoint, superseding only the frozen CI-service clause.
Wrong-password tests then exposed host trust; separately approved SCRAM fixed it.
A stale certifi audit export was corrected under the existing certifi-only authority.
All failed CI/clone/audit evidence is retained. No failed hosted job was rerun.
The resource-pressure clone timeout was followed by one explicitly authorized unchanged
fresh clone after measured recovery; no timeout/assertion was weakened or lucky rerun used.

## Frozen originals and administrative authority

Original bytes remain unchanged:

- ADR-025: `3c2978ca5f3b94ee4c0b9952976d841387c6c341517ee819263207893e4586ad`.
- READ_ONLY_ACCEPTANCE: `32a7e81327770b8a5f453fdfcafcdebd34f6c693f5a2fba2034707d9cb8f555a`.
- READ_ONLY_RUNBOOK: `ec075253329197077e5241215124256806bf87fcd8779d513e9447a67fd69242`.
- Static-shell clarification unchanged.

Owner authorizes this documentation/status-only child on PR #8, then requires both
new exact-head push/PR CI jobs and actual logs to pass before NORMAL merge. Ordered
merge parents must be prior main above and the exact administrative head. No squash,
rebase, force or executable/test/frontend/lock/workflow/dependency/migration change.
Actual administrative CI and merge receipts belong in the local consolidated handoff.

## Retained gates

Phase 2 full operational OPEN, seven genuine dates required, DS-03 BLOCKED. Phase 4
full operational OPEN; active release remains separately pinned at
`9b9038b6966843805c99f15e1c37cdba7c026679`, with task/config/activation unchanged.
Phase 5 offline foundation is accepted; actual commissioning NOT STARTED. Phase 6
NOT STARTED. Phase 3 has four INCONCLUSIVE outcomes, both OOS permanently consumed,
no CANDIDATE/CHAMPION. No money, broker, MT5, Exness, demo orders or live permits.
DS-02 review remains due 2026-11-16.

Authenticated entry visibility is PUBLIC; owner-selected long-term state is PRIVATE.
October 24 governance gate remains. No visibility/settings change is authorized.
After merge, diagnose operational lanes read-only, without repair/catch-up/credit.
A material application defect stops affected campaign interpretation and requires
separate remediation. Before creating/publishing any Phase6 branch, independently
verify PRIVATE; if still PUBLIC, stop for owner action. Only then may the separately
scoped DS-04 derivatives-intelligence substep proceed, with design/rights/preregistration
frozen first. No macro/news/LLM, task START, qualification credit or financial authority.
