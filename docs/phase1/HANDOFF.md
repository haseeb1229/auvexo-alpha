# Phase 1 engineering foundation handoff

Scope: Phase 1 only, after independently accepted Phase 0. Submission remains subject to
independent review; this document does not approve or merge its own PR. Phase 2 is not started.
Disposition: **PASS-WITH-OPEN-GATES for Phase 1 engineering delivery**. Local implementation,
145 tests, real PostgreSQL recovery, audits, clean Windows clone and hosted CI pass.
The earlier hosted-runner billing blocker was resolved for verification by the owner's
explicit temporary public-visibility change. Independent acceptance remains pending; this
implementation handoff does not grant permission to merge or begin Phase 2.
See the exact [verification receipts](VERIFICATION.md).

## Delivered foundation

Strict Pydantic contract shapes and canonical serialization, all seven validated modes,
deny-only money boundary, authenticated loopback API and CLI, real PostgreSQL/Alembic metadata
migration, ACL-protected local synthetic credentials, locked toolchain, developer commands,
tests/property checks, source/dependency scans, license inventory/SBOM and least-privilege CI.
See [source/test inventory and diagram](IMPLEMENTATION.md), [toolchain](TOOLCHAIN.md),
[Windows commands/recovery](SETUP.md), [stable child requirements](ACCEPTANCE_TESTS.md).

Phase 0 [PR #1](https://github.com/haseeb1229/auvexo-alpha/pull/1) is merged at
`eafec07ee7c7a98c9cca17b5f8665494bd650751`. Phase 1 branch is
`phase-1/engineering-foundation`, based on that accepted main. Exact final SHA and matching
CI/clone receipts are recorded in the PR body and delivery report. Main remains unchanged.

[Phase 1 PR #2](https://github.com/haseeb1229/auvexo-alpha/pull/2) remains OPEN and unmerged,
submitted for independent review after validation; it has not been self-approved.
The implementation/evidence checkpoint is `feddb1b5e3f6e757be1d3e816ad97b115d84a455`;
subsequent handoff-only commits do not change runtime behavior. The final exact HEAD and
matching clean-clone/CI receipts are recorded in the PR body and delivery report, avoiding
a document that purports to contain its own commit hash.

## Limits and tracked follow-up

| ID / owner | Limitation and consequence | Review/remediation point |
| --- | --- | --- |
| P1-L01 / platform maintainer | Measurements cover idle diagnostics only; no ingestion/research/execution load qualification | Measure actual workload in Phase 2, concurrent failure/load matrix in Phase 5 |
| P1-L02 / security maintainer | Local dev bearer/ACL file is not encrypted OS secret storage, WebAuthn or owner activation | Before credential-bearing Phase 2 work, define OS store/service boundary; Phase 7/8 full owner auth |
| P1-L03 / operations maintainer | SQL triggers cannot stop a malicious DB superuser; local backup proof is not off-device encrypted recovery | Separate admin/service identities and signed audit/recovery policy before live eligibility |
| P1-L04 / platform maintainer | PostgreSQL time/size log rotation is not an OS disk quota; error floods need disk-budget supervision | Keep Phase 0 caps; inspect logs during local tests and add workload-specific alert/cleanup proof before Phase 2 ingestion |
| P1-L05 / maintainer | Strict mypy targets production and migrations; tooling/tests use dynamic fixtures and are linted/executed | Reassess when tooling becomes runtime automation; do not move it into production without typing |
| P1-L06 / release maintainer | EDB archive hash is locally observed from official HTTPS, not a verified detached vendor signature | Recheck provenance at upgrade; never bypass fixed hash on mismatch |

No known unresolved runtime test defect is accepted. Future incomplete features are scope gates,
not permission to enable capabilities. Original R-000..R-039 are preserved; 15 stable Phase 1
child invariants are mapped to tests. ADR-011 narrows the implemented foundation without
changing financial authority or inventing unused queue/outbox infrastructure.

Resolved CI blocker: the original runs failed before runner assignment because of account
billing/spending-limit status. The owner temporarily made the repository public and requested
completion. [Run 38798883220, attempt 2](https://github.com/haseeb1229/auvexo-alpha/actions/runs/38798883220/attempts/2)
then executed every step and passed, including 145 tests in 4.00 seconds. No payment, plan/limit
increase, token-scope change, self-hosted runner registration or protection change was performed.
The private-repository design remains in force; final visibility and final-head CI receipts
are verified in the delivery report. Private Actions allowance is still unverified for future
changes; a successful historical public run does not promise future private-runner availability.

## Closed capabilities and future gates

No broker/exchange connectivity, trading SDK, market-data ingestion, terminal, real/demo order,
withdrawal, successful fake fill, live permit, numeric risk kernel or UI exists. Binance live
derivatives remain BLOCKED_BY_POLICY; Exness real remains disabled; all allocations/capabilities
remain zero. No purchase, paid inference, premium feed or commercial runtime was introduced.

OD-02 gateway, OD-03 real demo/spec/source rights, OD-04 capital/numeric limits, OD-05 financial/
religious/jurisdiction eligibility, OD-06 off-device recovery, OD-07 full identity/signing,
OD-08 workload budgets, OD-09+ later platform/research/client choices remain unresolved at their
original gates. No financial/legal/religious approval is inferred from engineering tests.

## Exact Phase 2 prerequisites

1. Independent reviewer accepts the exact Phase 1 commit, CI, clean Windows install and real
   database recovery evidence; resolve any blocking findings in new commits.
2. Founder supplies an explicit Phase 2 prompt and authorizes its scope. A roadmap row or
   selectable mode cannot authorize work.
3. Merge Phase 1 normally only when separately authorized and review/protection requirements
   are met; begin Phase 2 from the accepted main, preserving history.
4. Resolve each selected data source's rights/access, availability-time semantics, symbol/spec
   provenance and storage/resource plan before connecting it. No credentials are requested now.
5. If read-only demo attestation is authorized, establish secure credential/service identity
   handling first. No demo order transport until Phase 5, risk kernel until Phase 4, or live
   activation until its separate external and numerical gates.
