# ADR-022: Checkpoint A transaction SLO semantics and research-throttle qualification

Status: FROZEN owner-authorized amendment before evaluator implementation; independent review pending
Date: 2026-10-20
Requirements: R-024-P4-01, R-025-P4-01; parents R-015, R-024/027

## Context

The owner supplied the [performance-governance brief](../reference/PHASE_4_PERFORMANCE_GOVERNANCE_BRIEF.txt)
after the fifth-resume STOP. Reviewed HEAD is c0a470bbf9530ccd89d82df6e96811df2ed20cda;
the preserved corrected source aggregate is
cc17c0d7b2f2e55148bd8e0d683c42027dbdc4639ee505c9bd3609cebb29b69c.
This decision formally supersedes only the hard-MAX performance interpretation in
[ADR-020](020-paper-transaction-performance.md), [ADR-021](021-paper-monotonic-safety-projection.md)
and their resume briefs. Their safety decisions and dated stopped records remain intact.

Exact parent wording read before amendment:

- [Phase 0 handoff](../PHASE_0_HANDOFF.md): "<=100 ms p95 normalization/evaluation/dispatch stages";
  "Backpressure and research throttling protect operational work."
- [Performance and reliability](../PERFORMANCE_AND_RELIABILITY.md), original table:
  strategy evaluation "p95 <=100 ms, p99 <=250 ms"; risk kernel "p95 <=10 ms, p99 <=25 ms";
  "Full transaction <=100 ms target; lock contention defers/denies"; research
  "Throttle/pause before operational latency breaches". Its benchmark paragraph requires
  research concurrent then throttled and reporting p50/p95/p99.
- Original [R-024-P4-01](../phase4/ACCEPTANCE_TESTS.md), frozen 2026-10-18:
  "actual counts/p50/p95/p99/CPU/RAM/disk" and "full transaction<=100ms target".
  It did not specify every sample or MAX <=100 ms.

The parent is distribution based and includes operational protection through research
throttling. Benchmark v1's primary `transaction_max <=100` flag, followed by later
briefs' every-primary/admitted-wave hard maximum, imposed a stricter interpretation.
The child transaction P99 envelope is explicitly established here from the parent's
250 ms tail budget; it was not already stated unambiguously for transactions.

Historical misses remain valid evidence under their then-current interpretation:
the reviewed run had throttled primary max 122.7071 ms and burst max 108.1833 ms;
the single pre-optimization reproduction had concurrent baseline max 163.9569 ms;
the one final fifth-resume benchmark had concurrent baseline P95 135.6211 ms and
P99/MAX 272.4386 ms, plus throttled primary max 113.7271 ms. None is erased or rerun.
This is an evidence-driven amendment before qualification, not a claim that the
earlier STOP was mistaken or a waiver of the unchanged numeric P95 target.

## Decision

Canonical Checkpoint A semantics:

| Measurement | Qualified budget / disposition |
| --- | --- |
| Risk kernel | P95 <=10 ms; P99 <=25 ms in both phases |
| Indexed operational query | P95 <=50 ms; P99 <=200 ms in both phases |
| Full reservation/risk transaction | P95 <=100 ms; P99 <=250 ms under qualified/throttled PAPER engineering load |
| Research-concurrent transactions, primary and admitted waves | Stress characterization; a P95 >100 ms triggers THROTTLE_REQUIRED. A P99 >250 ms also requires throttling/tail investigation; it is never a silent PASS |
| Research-throttled transactions, primary and admitted waves | Each set must have P95 <=100 ms and P99 <=250 ms; otherwise overall FAIL |
| MAX | Always retain, report and investigate. MAX >100 ms alone does not fail a percentile-compliant set; no sample/outlier filtering |
| Queues | Queue bound 32, two DB workers; baseline 32/32 admitted; burst 160 offered, 32 admitted, 128 explicitly backpressured; all admitted work drains, no discard |

Kernel/query failure, missing/malformed samples or metrics, invalid percentile ordering,
or queue/accounting/drain failure produces FAIL. The fixed v1 counts remain 1000 kernel,
120 primary, 360 query and 32 per admitted wave in each phase. A concurrent transaction
trigger is THROTTLE_REQUIRED for that phase. Overall PASS requires that the subsequent
throttled phase meets every operational budget and queue invariant; a missing or failing
throttled phase cannot qualify. Emit explicit phase reasons and retain all reported
P50/P95/P99/MAX values without modifying the input receipt.

The one final benchmark is evaluated, never rerun: concurrent kernel 3.9996/7.8128,
query 22.2984/25.4336, primary 46.1356/54.452 ms (P95/P99) pass; concurrent baseline
135.6211/272.4386 ms is THROTTLE_REQUIRED and remains visible degradation evidence.
Concurrent burst 62.3726/69.3063 ms passes. Throttled kernel 2.6832/5.3042, query
19.0002/23.8062, primary 40.0354/46.6921 (MAX 113.7271), baseline 48.6988/52.4315
and burst 56.5129/76.0036 ms all pass. All queues drain with the fixed admissions.
Therefore performance qualification is PASS under this amendment, with a recorded
concurrent throttle trigger. This is not Checkpoint A independent acceptance.

## Alternatives

Reject silently changing the 100 ms P95 number, erasing old failures, replacing tails
with medians, dropping outliers, rerunning for a favorable sample, changing workload,
or treating the original primary-only boolean as an overall verdict. Reject weakening
locks, transactions, durability, Decimal risk, privileges, reconciliation or deadlines.

## Consequences

Transparently amend R-024-P4-01 with its original freeze history and this dated ADR.
Preserve the original requirement bytes/hash in the recovery package and repository
history; advance the documentation checker's frozen amendment hash explicitly.
The benchmark v1 script/hash, receipt JSON, workload, percentile algorithm, uv.lock
and migrations 0001-0005 stay unchanged. A separate pure deterministic evaluator
interprets the receipt and is not used for runtime money authorization or scheduling.
No dependency is added and no automatic throttle implementation is claimed.

The stress tail's exact cause remains unresolved. The receipt demonstrates qualified
throttled synthetic coexistence on Windows, not HFT, broker latency, real feeds,
continuous uptime or a production resource/deadline qualification. Existing higher-level
deterministic deadline/stale/deny rules remain unchanged. All correctness/security/
atomicity gates remain mandatory. No persistent PAPER observation, Phase 5 or broker work.

## Validation

Freeze this decision before evaluator implementation. Test exact/breached thresholds,
both phases and admitted waves, recovery from concurrent stress, MAX retention,
missing/malformed metrics, immutable input, fixed sample/admission counts and no
discard/outlier filtering. Evaluate the preserved final JSON read-only: expect overall
PASS with concurrent THROTTLE_REQUIRED and the 272.4386 ms tail still reported.
Run all final PG correctness/security, unskipped inherited suite, statics/docs, restores/
replay/immutable migration checks, scans/audit and exact-final Windows clone. Only then
normal same-branch founder commit/push workflow and coherent exact-new-head push/PR
runs AND jobs with passing logs. Do not rerun the acceptance benchmark or merge PR #5.

## Review point

GPT-5.6 Sol exact-new-SHA acceptance review, including the explicit amendment and all
historical degradation evidence. Full Phase 4, persistent observation, Phase 2 seven
genuine dates/DS-03 and public-governance review due 2026-10-24 remain separate gates.
