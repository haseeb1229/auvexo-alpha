# Phase 4 Checkpoint A implementation handoff

Disposition: **Checkpoint A engineering independently ACCEPTED/PASS** at exact source
`e3f39e0397e1846c37febcebc246ea91c9f2eb78` by GPT-5.6 Sol; see the
[acceptance record](../reviews/PHASE_4_CHECKPOINT_A_INDEPENDENT_ACCEPTANCE.md).
ADR-015 through ADR-022 are ACCEPTED/FROZEN for this scope. The accepted
[ADR-022 amendment](../adr/022-paper-performance-slo.md) retains the 272.4386 ms
concurrent stress tail as THROTTLE_REQUIRED evidence; no benchmark rerun.
Full canonical Phase 4 remains OPEN pending >=14 actual-feed PAPER calendar days,
replay evidence and zero unexplained ledger mismatches. Observation has NOT started;
its counter is zero. Acceptance commit e39d590caa008608d0dbd543418021f0e6fcd10b passed
both administrative CI events. PR #5 merged normally at
dbe3cd6f47bf5a48c044df2f36cba5ea7081ca09 with its required parents verified.
Checkpoint B engineering is independently ACCEPTED/PASS at
`527bd23ce434fee557f6f1414bf5b43d7c3c3f21`; its
[acceptance record](../reviews/PHASE_4_CHECKPOINT_B_INDEPENDENT_ACCEPTANCE.md) records
the supplied GPT-5.6 Sol review and exact source/CI evidence. ADR-023 and the requirements/
runbook are ACCEPTED/FROZEN with original bytes unchanged. Current authority is docs-only
PR #6 acceptance, exact-head administrative CI, verified normal merge, then local
PREPARATION only on merged main under the
[pre-start brief](../reference/PHASE_4_CHECKPOINT_B_PRESTART_BRIEF.txt),
[ADR-023](../adr/023-paper-observation-qualification.md), frozen
[requirements](OBSERVATION_ACCEPTANCE.md) and [future runbook](OBSERVATION_RUNBOOK.md).
Merged-SHA/prepared-hash review and separate owner START remain pending; no activation
or task registration. Activation, scheduled runs, qualifying receipts and genuine dates stay zero.
See the Checkpoint B [implementation map](OBSERVATION_IMPLEMENTATION.md) for the
current observation-harness components and non-counting verification scope.
The Checkpoint A delivery and its original transition sequence below remain historical.

## Implemented scope and preserved safety

The [requirements](ACCEPTANCE_TESTS.md), including their dated performance amendment,
govern deterministic PAPER-only typed intents, conservative Decimal risk, serialized
reservations/outbox, fenced dispatch, independent virtual truth, reconciliation,
immutable audit and lifecycle metadata. The [design map](DESIGN_AND_REVIEW.md) and
[runbook](SETUP_AND_RECOVERY.md) explain the engineering boundaries.

[ADR-016](../adr/016-paper-direct-login.md),
[ADR-017](../adr/017-paper-risk-state-corrections.md) and
[ADR-018](../adr/018-paper-observed-mark-freshness.md) preserve dedicated least-privilege
LOGINs, new-position OPEN identity, rejection/fill quarantine, latched loss across UTC
days and historical valuation independently of current freshness. Financial guards remain intact.

[ADR-019](../adr/019-paper-lifecycle-filesystem.md) closes the initial production
lifecycle bypass. Production identities start once in RESEARCH, then require legal
transitions bound to the latest durable snapshot. Per-identity locking, atomic history
writes and a validated derived current projection reject stale/forked/cross-identity
updates. Early suspension cannot bypass promotion history. Fixture PAPER remains
physically separate and non-promotable; production metadata tests use isolated synthetic DBs.

The exact old pytest cache was proven to be project-created synthetic state before
granting owner read/list/traverse access on that cache tree alone. DataStore quota
traversal is unchanged and still fails closed on unreadable paths. The canonical
`tools/run_tests.py` keeps future cache state in unique disposable temporary storage;
CI and Windows clean-clone verification use it, including failure cleanup.

[ADR-020](../adr/020-paper-transaction-performance.md) documents transaction-local
verified journal reuse and consolidated per-checkout catalog attestation. Journal
reuse is limited to the exact locked Connection/root transaction/account; every
checkout still validates the complete identity/privilege boundary, without cached results.
[ADR-021](../adr/021-paper-monotonic-safety-projection.md) requires every later safety
transition to use the latest transaction-local account projection. Pending truth plus
loss denial must retain K2 and reconciled=False, with the cursor unchanged until actual
reconciliation. Owner resume and a second authorization remain blocked before consumption.
Consuming truth does not clear K2; an eligible explicit audited owner command is still required.

## Formal performance disposition: existing evidence, no rerun

The [governance brief](../reference/PHASE_4_PERFORMANCE_GOVERNANCE_BRIEF.txt) authorizes
an explicit amendment before qualification. The parent
[Phase 0 handoff](../PHASE_0_HANDOFF.md) specifies <=100 ms P95 stages and protective
research throttling. The parent [performance policy](../PERFORMANCE_AND_RELIABILITY.md)
requires percentile reporting, a <=100 ms full-transaction target, and research
throttle/pause before operational latency breaches. Original R-024-P4-01 did not
require every transaction/MAX <=100 ms. ADR-022 explicitly establishes the transaction
P99 <=250 ms envelope from the parent's tail budget, rather than claiming it was already
unambiguous for transactions.

The fifth-resume hard-MAX STOP remains valid historical evidence. ADR-022 formally
supersedes that interpretation without erasing the STOP or changing safety, workload,
the benchmark script, samples, percentile algorithm or receipt. The preserved one final
benchmark is evaluated; no second acceptance benchmark is authorized.

Qualified/throttled transaction sets require P95 <=100 ms and P99 <=250 ms. Kernel
P95 <=10/P99 <=25 ms and query P95 <=50/P99 <=200 ms remain required in both phases.
Concurrent transaction stress above P95 100 ms or P99 250 ms is THROTTLE_REQUIRED;
qualification requires the subsequent throttled phase to satisfy all operational
budgets. MAX values remain reported and investigated; no outlier filtering is permitted.

All times below are milliseconds from the preserved fifth-resume final receipt:

| Phase | Set | Samples | P50 | P95 | P99 | MAX | ADR-022 disposition |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Research concurrent | Kernel | 1000 | 1.5135 | 3.9996 | 7.8128 | 14.9418 | PASS |
| Research concurrent | Primary transaction | 120 | 31.7141 | 46.1356 | 54.452 | 58.6687 | PASS |
| Research concurrent | Indexed query | 360 | 16.4971 | 22.2984 | 25.4336 | 32.6794 | PASS |
| Research concurrent | Baseline admitted transactions | 32 | 47.1705 | 135.6211 | 272.4386 | 272.4386 | THROTTLE_REQUIRED |
| Research concurrent | 5x burst admitted transactions | 32 | 48.0776 | 62.3726 | 69.3063 | 69.3063 | PASS |
| Research throttled | Kernel | 1000 | 1.459 | 2.6832 | 5.3042 | 8.4293 | PASS |
| Research throttled | Primary transaction | 120 | 25.5605 | 40.0354 | 46.6921 | 113.7271 | PASS |
| Research throttled | Indexed query | 360 | 11.4745 | 19.0002 | 23.8062 | 80.2526 | PASS |
| Research throttled | Baseline admitted transactions | 32 | 38.3659 | 48.6988 | 52.4315 | 52.4315 | PASS |
| Research throttled | 5x burst admitted transactions | 32 | 36.191 | 56.5129 | 76.0036 | 76.0036 | PASS |

Each phase retains queue bound 32 and two DB workers: baseline 32 offered/32 admitted;
5x burst 160 offered/32 admitted/128 explicitly backpressured. All admitted work drained.
Overall performance qualification is PASS under ADR-022, with concurrent
THROTTLE_REQUIRED. The 272.4386 ms stress tail and 113.7271 ms throttled primary MAX
remain visible. Their exact cause is unresolved; no automatic throttle controller or
HFT, broker, live-feed, continuous-uptime or production resource qualification is claimed.

Earlier misses, including 163.9569 ms, and all prior benchmark/profile/STOP receipts
remain historical. Detailed machine resources, hashes, limitations and recovery packages
stay in ignored owner-local evidence and must accompany independent review. The
benchmark's original primary-only `transaction_max` flag is not the amended overall verdict.

## Verification status

The fifth-resume corrected/optimized source remained uncommitted at the preserved
aggregate `cc17c0d7b2f2e55148bd8e0d683c42027dbdc4639ee505c9bd3609cebb29b69c`.
Earlier reviewed committed baseline: `c0a470bbf9530ccd89d82df6e96811df2ed20cda`.
Accepted engineering source: `e3f39e0397e1846c37febcebc246ea91c9f2eb78`.
PR #5 is now authorized for a documentation-only acceptance child, exact-head
administrative CI and checked normal merge; no merge has yet been recorded here.

| Historical verification | Recorded result | Limit |
| --- | --- | --- |
| Fifth-resume reconciliation correction | 13 passed | Targeted proof before the governance/evaluator changes |
| Fifth-resume performance regression matrix | 10 passed | Targeted proof, not a new timing sample |
| Fifth-resume full real-PG correctness | 180 passed | Historical changed-source safety proof; final rerun required |
| Fifth-resume direct-LOGIN security | 111 passed | Historical changed-source security proof; final rerun required |
| Earlier c0 full suite | 661 passed, no skips | Reviewed baseline only; not current-source final proof |
| Earlier c0 foundation/PAPER/data-research restores and audit | Passed | Historical; applicable final checks remain required |

Governance-resume local verification on the combined corrected source:

| Verification | Result |
| --- | --- |
| Pure offline evaluator (`domain/paper_performance.py`) | 589 timing-independent tests passed; all ten metric sets retained, concurrent THROTTLE_REQUIRED and overall PASS on the preserved receipt |
| Full real-PG correctness, lifecycle and new regressions | 180 passed; includes the 13 reconciliation and 10 performance cases |
| Full direct-LOGIN security | 111 passed; cleanup boundaries unchanged |
| Full inherited suite | 1,273 passed, no skips; 411.60 seconds |
| Ruff format/check and strict mypy | Passed; 94 formatted files and 46 typed sources |
| Foundation restore | Three tables matched; idempotence, destructive downgrade refusal, restored trigger and schema-drift refusal passed |
| PAPER restore | 15 tables and 11 triggers matched; UNKNOWN reservations, K4 and virtual financial totals retained; no blind retry |
| Data/research restore | 11 tables, 176 manifests, 118 trials and 96 artifacts verified; exact source-to-Parquet replay passed |
| Hash-required advisory audit | 69 locked dependencies; zero reported vulnerabilities |
| High-signal secret scan and diff check | Passed; final documentation/requirements and equal instruction bytes checked again before commit |

The evaluator is an offline evidence interpreter, not a runtime authority or an automatic
throttle controller. The original benchmark JSON/hash is unchanged and no acceptance
benchmark ran in this resume. The corrected runtime and its reconciliation/performance
regressions are byte-identical to the fifth-resume stopped source before Git text normalization.
Final source/history redacted Gitleaks, exact-commit Windows clone and hosted push/PR
receipts are bound to the reviewed source in the owner-local handoff and PR review request.
Do not substitute historical receipts or this summary for those exact-source checks.
Same-disk restores do not establish encrypted off-device disaster recovery.

## Remaining gates and boundaries

The supplied independent review inspected exact-head push run 39318662478/job
118286676477 (1273 passed in 81.69 s) and PR run 39318668094/job 118286698079
(1273 passed in 82.86 s), both completed/success. Source/hosted-CI inspections are
independent evidence; owner-machine Windows clone, recovery, ACL and timing receipts
were supporting evidence and were not all independently re-enacted. This limitation
and the complete accepted scope are recorded in the acceptance document.

The next authorized steps are a documentation-only acceptance commit and exact-head
push/PR administrative CI, then normal PR #5 merge with verified parents. Only after
that merge may `phase-4/paper-observation` implement the Checkpoint B harness from
resulting main under the owner brief, freezing its ADR and requirements first.
Its new PR remains unmerged for independent exact-SHA review. No persistent task
registration, observation START or >=14-day counter start is authorized. Full Phase 4
operational acceptance remains OPEN; the implementing agent does not award it.

DEV remains at reviewed 0004; unmerged 0005 is exercised only in isolated verification.
The schema-aware foundation diagnostic remains NOT_READY on unmigrated DEV.
October 18 remains INCOMPLETE/MISSED_START. October 19 is INCOMPLETE: 24 events,
22 verified; two initial stale BTC/ETH events were correctly excluded. Genuine qualified
scheduled dates remain zero. No catch-up, backfill, manual credit or scheduler change.
No heavy work 22:45-23:20 Pakistan. Seven genuine dates and DS-03 remain open Phase 2 gates.

The authenticated remote recheck and owner confirmation show PUBLIC, superseding the
fourth brief's earlier PRIVATE statement. No visibility, billing, runner or repository
permission setting was changed. Public-exception review remains due 2026-10-24;
dated historical records remain intact. Before broker sessions/credentials or proprietary
alpha work, PRIVATE return or an independently reviewed owner-approved superseding
public ADR remains required; this amendment grants no such capability.

All four Phase 3 outcomes remain INCONCLUSIVE; both OOS holdouts stay consumed.
No production candidate/champion, persistent PAPER task or 14-day counter, Phase 5,
broker SDK/account/session/credentials/transport, DEMO/REAL orders, live permit issuer,
withdrawal, runtime AI, frontend or paid service. All money execution remains denied;
Binance live derivatives remain BLOCKED_BY_POLICY.
