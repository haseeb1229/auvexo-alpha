# Current-lock dependency maturity exception

Recorded 2026-10-17 under R-018-BA-01 / ADR-013; independent amendment review pending.
Owner preference remains mature/supported software, not novelty. The current exact tested
`pyproject.toml`, `uv.lock`, `requirements-audit.txt`, inventories/SBOM and notices are retained.
FastAPI 0.143.2, Pydantic 2.14.1 and Polars/runtime 2.0.0 are recent releases explicitly
covered by this exception. No dependency pin or build/CI action is changed by the amendment.

Windows native install, real PostgreSQL tests, isolated clean-clone checks, exact Parquet
replay/restore and exact-head hosted CI exist at entry `3190d104a7a05b43645117ea987bee50ad80c200`;
see [closure evidence](../phase2/closure/HANDOFF.md) and the exact-entry final delivery record.
These support retaining the green lock while the amendment's full regression checks run.
They do not prove these versions mature by age, undiscovered-defect-free or suitable for
future broker/financial-critical use. Recentness and age alone are not correctness proof.

No auto-upgrade and no downgrade merely to use an older release. A real defect/security
finding requires scoped evidence, a tested justified pin change and preserved reproducibility.
Re-evaluate maintenance/support, release stability, licenses, advisories, compatibility,
financial semantics and restore/rollback at each adoption phase, especially broker and
financial-critical libraries. No broker SDK is adopted now.

Review owner: implementation/dependency maintainer with independent reviewer acceptance.
Next review: next dependency adoption or 2026-11-16, whichever occurs first; immediate
review on an actual advisory/defect. No automatic renewal. A dated zero-known-vulnerability
audit is evidence for that time only. This exception changes no money/execution authority.
