# ADR-003: modular core and client boundaries

Status: FROZEN
Date: 2026-10-15
Requirements: R-018, R-019, R-020, R-028

## Context

One owner and laptop do not justify distributed infrastructure, while clients and MT5 have different trust/runtime needs.

## Decision

Modular monolith plus bounded research worker and isolated Windows gateway. Domain imports only ports. Versioned APIs/events serve all clients and future separate Auvexo repos.

## Alternatives

Microservice zoo/Kubernetes and a giant multi-product monorepo add operational coupling. UI-to-broker and shared ecosystem DB access violate boundaries.

## Consequences

Maintain typed read models and explicit extension manifests. Later Linux core can use the same secured Windows gateway protocol.

## Validation

Phase 1 import/schema checks; Phase 7 redesign/backend-contract independence; future cross-system identity tests.

## Review point

Architecture; split services only after measured operational need and a superseding ADR.
