# ADR-011: Phase 1 foundation without trading capability

Status: FROZEN
Date: 2026-10-16
Requirements: R-003, R-018, R-019, R-022, R-023, R-025, R-027

## Context

Independent Phase 0 acceptance authorizes a minimal buildable foundation, not future data
or risk/execution functionality. The Phase 0 checker must evolve to admit explicitly scoped
source/tests while preserving historical requirements and safety boundaries.

## Decision

Use a src-layout Python package with domain contracts, application denial/diagnostics ports,
PostgreSQL infrastructure and a loopback-only diagnostic API/CLI. Pydantic is the single
contract/schema definition; domain has no web/DB SDK dependencies. Use uv alone for a
hashed dependency lock and isolated environments. Install only dependencies exercised now.
Database contains immutable foundation/policy identity and append-only developer events;
do not implement a queue/outbox with no current consumer. ADR-005's future durable-job
direction remains unchanged, assigned to its later proof gate.

Every execution boundary returns a typed denial. No broker adapter, actual risk authorizer,
permit issuer, credential field or order endpoint exists. A schema named RiskAuthorization
is an inert shape and cannot authorize anything. Bind settings accept only literal 127.0.0.1.
All diagnostic HTTP routes require a process-local random bearer token supplied securely;
this is local development auth, not owner live activation. No auth UI is built.

## Alternatives

Public bind plus a password, a configurable execution-enable boolean, mocked broker success,
SQLite-only proof and speculative queue tables are rejected. Full passkey/step-up remains
future client work; Windows DPAPI/OS keychain remains the future persistent secret store.

## Consequences

Replace the Phase 0 document-only file allowlist with a scoped source/test/tool allowlist;
keep its source hash, original requirement mappings and aligned instructions. Runtime
checks must prove actual disabled behavior. No claims about trading readiness follow from
foundation health. Use native portable PostgreSQL and managed Python without global PATH,
Windows service, firewall or unrelated-project changes.

## Validation

Stable child IDs in docs/phase1/ACCEPTANCE_TESTS.md; strict lint/type/property/API/security
tests, real PostgreSQL migrations/constraints/restore, locked clean Windows clone, measured
idle resources, dependency/license/secret checks and feature-branch CI.

## Review point

Independent review of the Phase 1 exact commit/CI precedes Phase 2. Reassess authentication
and durable jobs only at the authorized phase; no executable money capability inherited.
