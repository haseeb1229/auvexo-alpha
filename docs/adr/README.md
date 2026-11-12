# Architecture decision records

Each record states its own status as of the day it was frozen; the status column below is
the index's current reading. FROZEN records are changed only by a superseding ADR, never
by editing their bytes. PROVISIONAL records need their named proof gate. No record is
evidence that a control is implemented or certified.

Each record carries its own date; `git log` gives the commit that froze it.

| ADR | Status | Decision | Supersedes / superseded by |
| --- | --- | --- | --- |
| [ADR-001](001-authority-and-risk.md) | FROZEN | authority and risk |  |
| [ADR-002](002-modes-and-live-permits.md) | FROZEN | modes and live permits |  |
| [ADR-003](003-modular-core-and-client-boundaries.md) | FROZEN | modular core and client boundaries |  |
| [ADR-004](004-postgres-and-parquet.md) | FROZEN | postgres and parquet |  |
| [ADR-005](005-durable-jobs-before-message-bus.md) | FROZEN | durable jobs before message bus |  |
| [ADR-006](006-mt5-python-first.md) | PROVISIONAL | mt5 python first | Read-only scope implemented under 028 and 029 |
| [ADR-007](007-research-before-promotion.md) | FROZEN | research before promotion |  |
| [ADR-008](008-free-first-model-and-data-ports.md) | FROZEN | free first model and data ports |  |
| [ADR-009](009-security-and-local-first.md) | FROZEN | security and local first |  |
| [ADR-010](010-reuse-without-root-fork.md) | FROZEN | reuse without root fork |  |
| [ADR-011](011-phase1-foundation.md) | FROZEN | Phase 1 zero-capability foundation; scoped checker evolution |  |
| [ADR-012](012-phase2-data-boundaries.md) | Accepted for DS-01/02 spot research; operational gates OPEN | Bounded research data, immutable lineage and evidence-driven retention |  |
| [ADR-013](013-source-specific-acceptance.md) | FROZEN; independently accepted at bdae1a1 | Source-specific engineering acceptance; full operational gates retained; 23:00 Pakistan schedule | Visibility clause superseded in part by 027 |
| [ADR-014](014-nonproduction-research.md) | ACCEPTED/FROZEN at bb692208 | Deterministic nonproduction spot research and immutable trial ledger |  |
| [ADR-015](015-paper-risk-core.md) | ACCEPTED/FROZEN for Checkpoint A at e3f39e0 | Isolated deterministic PAPER risk/lifecycle/durable core |  |
| [ADR-016](016-paper-direct-login.md) | ACCEPTED/FROZEN for Checkpoint A at e3f39e0 | Direct least-privilege PAPER LOGIN binding, no admin pool |  |
| [ADR-017](017-paper-risk-state-corrections.md) | ACCEPTED/FROZEN for Checkpoint A at e3f39e0 | New-position OPEN identity, contradictory truth and latched marked loss |  |
| [ADR-018](018-paper-observed-mark-freshness.md) | ACCEPTED/FROZEN for Checkpoint A at e3f39e0 | Retained observed valuation with separate current freshness |  |
| [ADR-019](019-paper-lifecycle-filesystem.md) | ACCEPTED/FROZEN for Checkpoint A at e3f39e0 | Production initial history and isolated pytest cache permissions |  |
| [ADR-020](020-paper-transaction-performance.md) | ACCEPTED/FROZEN for Checkpoint A at e3f39e0 | Same-transaction verified history and bounded checkout roundtrips; performance interpretation superseded by ADR-022 | Performance interpretation superseded by 022 |
| [ADR-021](021-paper-monotonic-safety-projection.md) | ACCEPTED/FROZEN for Checkpoint A at e3f39e0 | Monotonic safety projection across pending truth and loss denial; performance interpretation superseded by ADR-022 | Performance interpretation superseded by 022 |
| [ADR-022](022-paper-performance-slo.md) | ACCEPTED/FROZEN for Checkpoint A at e3f39e0 | Percentile transaction SLO and qualified research-throttle semantics; no benchmark rerun | Supersedes the hard-maximum reading of 020 and 021 |
| [ADR-023](023-paper-observation-qualification.md) | ACCEPTED/FROZEN for Checkpoint B engineering at 527bd23; original document bytes retained | [Independent acceptance](../reviews/PHASE_4_CHECKPOINT_B_INDEPENDENT_ACCEPTANCE.md); PAPER observation qualification rules; the campaign it governs is registered on the pinned release |  |
| [ADR-024](024-parallel-operational-release-and-engineering.md) | ACCEPTED/FROZEN offline engineering at 82601fa; original bytes retained | [Independent acceptance](../reviews/PHASE_5_OFFLINE_FOUNDATION_INDEPENDENT_ACCEPTANCE.md); pinned release and separate non-money engineering; commissioning NOT STARTED |  |
| [ADR-025](025-read-only-private-operator-terminal.md) | ACCEPTED/FROZEN at 4418df0; original bytes retained | [Independent acceptance](../reviews/PHASE_7_READ_ONLY_FOUNDATION_INDEPENDENT_ACCEPTANCE.md); read-only terminal, every API bearer-protected |  |
| [ADR-026](026-ds04-open-interest-intelligence.md) | ACCEPTED/FROZEN source/feature-foundation design at 887b6ac; executable engineering ACCEPTED/PASS at b3e8cc1; no collection authority | DS-04-A1 OI snapshot only; [rights](../phase6/SOURCES_AND_RIGHTS.md) and [preregistration](../phase6/EXPERIMENT_PREREGISTRATION.md) |  |
| [ADR-027](027-temporary-public-ci-and-sanitized-engineering.md) | ACCEPTED / TEMPORARY / OWNER-APPROVED / independently reviewed | Temporary public CI/sanitized engineering; PRIVATE return before actual broker onboarding/confidential alpha | Supersedes the 2026-10-24 public-review gate of 013; amended in scope by 029 for the pinned SDK |
| [ADR-028](028-ds03-synthetic-readonly-foundation.md) | ACCEPTED/FROZEN synthetic engineering at ba66f44; original design bytes retained | Synthetic-only DS-03 read-only boundary; actual account onboarding requires PRIVATE return | Synthetic-only package limit superseded by 029 for the actual adapter |
| [ADR-029](029-ds03-mt5-readonly-adapter.md) | FROZEN before implementation; implemented and independently reviewed with corrections (ADR-030) | Actual MT5 read-only adapter code; no account activation | Amended by 030 |
| [ADR-030](030-ds03-adapter-independent-review-corrections.md) | ACCEPTED amendment to ADR-029; ENGINEERING_ONLY; NO_ACTUAL_ACCOUNT_SESSION | [Independent review](../reviews/PHASE_2_DS03_ACTUAL_ADAPTER_INDEPENDENT_REVIEW.md) corrections: token-derived fixed runtime, complete source binding, static SDK allowlist proof; onboarding preconditions including unresolved source rights | Amends 029 |
| [ADR-031](031-evidence-semantics-corrections-and-campaign-restart.md) | ACCEPTED engineering corrections; campaigns not restarted | Provider-time finality, scheduled provenance, failure evidence, one receipt per night, rights at receipt time; restart preconditions | Tightens evidence handling under 013 and 023 without editing them |

Exact versions, capital decisions, deferred triggers and external gates live in
[decisions and gates](../OPEN_DECISIONS.md). Current status lives in [STATUS](../STATUS.md).
