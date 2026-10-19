# Phase 4 Checkpoint A implementation handoff

Disposition: implementation submitted for independent review; Checkpoint A acceptance
remains OPEN. The measured full-transaction target has tail misses. No performance
waiver, phase acceptance, merge or persistent observation follows from this delivery.

## Implemented scope

The [frozen requirements](ACCEPTANCE_TESTS.md) govern deterministic PAPER-only typed
intents, conservative Decimal risk, serialized reservations/outbox, fenced dispatch,
independent virtual truth, reconciliation, immutable audit and lifecycle metadata.
The [design map](DESIGN_AND_REVIEW.md) and [runbook](SETUP_AND_RECOVERY.md) explain
the boundaries and one-shot verification commands.

The security and correctness resumes preserve dedicated least-privilege LOGINs,
new-position OPEN identity, rejection/fill quarantine, latched loss across UTC days,
and retained historical valuation independently of current freshness. Financial guards
remain intact. See [ADR-016](../adr/016-paper-direct-login.md),
[ADR-017](../adr/017-paper-risk-state-corrections.md) and
[ADR-018](../adr/018-paper-observed-mark-freshness.md).

[ADR-019](../adr/019-paper-lifecycle-filesystem.md) closes the initial production
lifecycle bypass. Production identities start once in RESEARCH, then require legal
transitions bound to the latest durable snapshot. Per-identity locking, atomic history
writes and a validated derived current projection reject stale/forked/cross-identity
updates. An early suspension cannot bypass promotion history. Fixture PAPER remains
physically separate and non-promotable; production metadata tests use isolated synthetic
databases only.

The exact old pytest cache was proven to be project-created synthetic state before
granting owner read/list/traverse access on that cache tree alone. DataStore quota
traversal is unchanged and still fails closed on unreadable paths. The canonical
`tools/run_tests.py` keeps future cache state in unique disposable temporary storage;
CI and Windows clean-clone verification use it, including failure cleanup.

## Recorded local verification

| Verification | Result |
| --- | --- |
| Focused lifecycle domain and real PG matrix | 91 passed |
| Focused cache cleanup and quota failure semantics | 3 passed |
| Full PAPER/lifecycle real PG correctness | 157 passed |
| Full direct-LOGIN and immutable-history security rerun | 110 passed |
| Full inherited suite | 661 passed, no skips; 531.15 seconds |
| Ruff format/check and strict mypy | Passed; 90 formatted files, 45 typed sources |
| Foundation, PAPER and data/research isolated restore | Passed; hashes, replay, immutable guards and downgrade refusal |
| Hash-required dependency audit | 69 dependencies, zero known vulnerabilities |
| Synthetic performance | Measured; transaction tail target MISSED, reviewer disposition required |

The benchmark workload and targets were unchanged. Report every primary and two-worker
baseline/burst percentile, sample count and resource limitation to the reviewer; do not
replace tail misses with primary median/p95 results or retry until a pass. Detailed
measurements, hashes, ACL evidence, recovery packages and exact final commit/clone/CI
receipts stay in the ignored owner-local handoff and must accompany independent review.
Same-disk copies are not encrypted off-device disaster recovery.

## Remaining gates and boundaries

Request GPT-5.6 Sol exact-final-SHA review, including explicit performance disposition.
Keep exactly one Phase 4 PR open and unmerged. Exact-final Windows clone and hosted
push/PR CI receipts belong to that source SHA; earlier passes cannot substitute for them.
DEV remains at reviewed 0004; unmerged 0005 is exercised only in isolated verification.
The schema-aware foundation diagnostic therefore remains NOT_READY on unmigrated DEV.

October 18 remains INCOMPLETE/MISSED_START. At the October 19 pre-window read-only
qualification check, October 19 was OPEN and genuine qualified dates remained zero.
Its scheduled outcome can be assessed only after the real window; no catch-up or
manual credit. The daily task is unchanged, with no heavy work 22:45-23:20 Pakistan.
Seven genuine dates and DS-03 remain open Phase 2 operational gates.

The authenticated remote recheck and owner confirmation show PUBLIC, superseding the
fourth brief's earlier PRIVATE statement. No visibility, billing, runner or repository
permission setting was changed. Public-exception governance review remains due
2026-10-24; dated historical records remain intact.

All four Phase 3 outcomes remain INCONCLUSIVE; both OOS holdouts stay consumed.
No production candidate/champion, persistent PAPER task or 14-day counter, Phase 5,
broker SDK/account/session/credentials/transport, DEMO/REAL orders, live permit issuer,
withdrawal, runtime AI, frontend or paid service. All money execution remains denied;
Binance live derivatives remain BLOCKED_BY_POLICY.
