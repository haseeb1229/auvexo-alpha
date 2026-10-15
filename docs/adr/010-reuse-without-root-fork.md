# ADR-010: reuse without root fork

Status: FROZEN
Date: 2026-10-15
Requirements: R-030, R-031, R-032, R-033

## Context

Mature projects offer useful implementation evidence but importing a platform would import its assumptions and license/dependency surface.

## Decision

New private haseeb1229/auvexo-alpha repo; reference/benchmark upstream patterns. Prefer narrow pinned libraries, preserve attribution and perform exact-revision adoption review.

## Alternatives

Root forks, vendored full repos, removed attribution and mandatory external engines rejected.

## Consequences

Current upstream licenses may differ from historical reputation; inspect actual version and file headers. No external source/package adopted in Phase 0.

## Validation

Phase 0 selected-code/license evidence; every later dependency addition includes license/security/resource review.

## Review point

OD-13 before adoption; aligned AGENTS/CLAUDE and engineering rules enforce process.
