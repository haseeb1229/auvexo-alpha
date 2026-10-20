# Architecture decision records

ADRs 001-010 date from 2026-10-15, 011-012 from 2026-10-16 and 013 from 2026-10-17.
Each record states its own status. FROZEN records require a superseding ADR; PROVISIONAL
records require their named proof gate. None is evidence of an implemented control.

| ADR | Status | Decision |
| --- | --- | --- |
| [ADR-001](001-authority-and-risk.md) | FROZEN | authority and risk |
| [ADR-002](002-modes-and-live-permits.md) | FROZEN | modes and live permits |
| [ADR-003](003-modular-core-and-client-boundaries.md) | FROZEN | modular core and client boundaries |
| [ADR-004](004-postgres-and-parquet.md) | FROZEN | postgres and parquet |
| [ADR-005](005-durable-jobs-before-message-bus.md) | FROZEN | durable jobs before message bus |
| [ADR-006](006-mt5-python-first.md) | PROVISIONAL | mt5 python first |
| [ADR-007](007-research-before-promotion.md) | FROZEN | research before promotion |
| [ADR-008](008-free-first-model-and-data-ports.md) | FROZEN | free first model and data ports |
| [ADR-009](009-security-and-local-first.md) | FROZEN | security and local first |
| [ADR-010](010-reuse-without-root-fork.md) | FROZEN | reuse without root fork |
| [ADR-011](011-phase1-foundation.md) | FROZEN | Phase 1 zero-capability foundation; scoped checker evolution |
| [ADR-012](012-phase2-data-boundaries.md) | Accepted for DS-01/02 spot research; operational gates OPEN | Bounded research data, immutable lineage and evidence-driven retention |

| [ADR-013](013-source-specific-acceptance.md) | FROZEN; independently accepted at bdae1a1 | Source-specific engineering acceptance; full operational gates retained; 23:00 Pakistan schedule |

| [ADR-014](014-nonproduction-research.md) | ACCEPTED/FROZEN at bb692208 | Deterministic nonproduction spot research and immutable trial ledger |

Exact versions, capital decisions and deferred triggers live in [open decisions](../OPEN_DECISIONS.md).

| [ADR-015](015-paper-risk-core.md) | ACCEPTED/FROZEN for Checkpoint A at e3f39e0 | Isolated deterministic PAPER risk/lifecycle/durable core |

| [ADR-016](016-paper-direct-login.md) | ACCEPTED/FROZEN for Checkpoint A at e3f39e0 | Direct least-privilege PAPER LOGIN binding, no admin pool |

| [ADR-017](017-paper-risk-state-corrections.md) | ACCEPTED/FROZEN for Checkpoint A at e3f39e0 | New-position OPEN identity, contradictory truth and latched marked loss |

| [ADR-018](018-paper-observed-mark-freshness.md) | ACCEPTED/FROZEN for Checkpoint A at e3f39e0 | Retained observed valuation with separate current freshness |

| [ADR-019](019-paper-lifecycle-filesystem.md) | ACCEPTED/FROZEN for Checkpoint A at e3f39e0 | Production initial history and isolated pytest cache permissions |

| [ADR-020](020-paper-transaction-performance.md) | ACCEPTED/FROZEN for Checkpoint A at e3f39e0 | Same-transaction verified history and bounded checkout roundtrips; performance interpretation superseded by ADR-022 |

| [ADR-021](021-paper-monotonic-safety-projection.md) | ACCEPTED/FROZEN for Checkpoint A at e3f39e0 | Monotonic safety projection across pending truth and loss denial; performance interpretation superseded by ADR-022 |

| [ADR-022](022-paper-performance-slo.md) | ACCEPTED/FROZEN for Checkpoint A at e3f39e0 | Percentile transaction SLO and qualified research-throttle semantics; no benchmark rerun |

| [ADR-023](023-paper-observation-qualification.md) | ACCEPTED/FROZEN for Checkpoint B engineering at 527bd23; original document bytes retained | [Independent acceptance](../reviews/PHASE_4_CHECKPOINT_B_INDEPENDENT_ACCEPTANCE.md); verified normal PR #6 merge permits PREPARATION only; separate owner START pending; zero dates |

| [ADR-024](024-parallel-operational-release-and-engineering.md) | ACCEPTED/FROZEN offline engineering at 82601fa; original bytes retained | [Independent acceptance](../reviews/PHASE_5_OFFLINE_FOUNDATION_INDEPENDENT_ACCEPTANCE.md); pinned release and separate non-money engineering; commissioning NOT STARTED |

| [ADR-025](025-read-only-private-operator-terminal.md) | DRAFT / NOT FROZEN; bootstrap disposition pending | Read-only operator-terminal foundation; no executable implementation yet |
