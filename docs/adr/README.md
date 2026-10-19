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

| [ADR-015](015-paper-risk-core.md) | FROZEN checkpoint design; implementation review pending | Isolated deterministic PAPER risk/lifecycle/durable core |

| [ADR-016](016-paper-direct-login.md) | FROZEN; local proof, independent review pending | Direct least-privilege PAPER LOGIN binding, no admin pool |

| [ADR-017](017-paper-risk-state-corrections.md) | FROZEN; local proof, independent review pending | New-position OPEN identity, contradictory truth and latched marked loss |

| [ADR-018](018-paper-observed-mark-freshness.md) | FROZEN; local proof, independent review pending | Retained observed valuation with separate current freshness |

| [ADR-019](019-paper-lifecycle-filesystem.md) | FROZEN; local proof, independent review pending | Production initial history and isolated pytest cache permissions |
