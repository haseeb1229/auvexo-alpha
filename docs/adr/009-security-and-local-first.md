# ADR-009: security and local first

Status: FROZEN
Date: 2026-10-15
Requirements: R-023, R-027, R-029, R-031

## Context

Private repository and local deployment do not prevent credential theft or accidental live activation.

## Decision

Single owner, least privilege, OS secret store, authenticated local IPC, step-up dangerous actions, independent permit signing, durable audit and encrypted tested backup. Start local; remote access through private identity-aware boundary.

## Alternatives

Public signup, obscurity security, frontend secrets, broad agent capabilities and free-tier capital-safety assumptions rejected.

## Consequences

Local admin compromise remains a threat. Same-disk backups are not disaster recovery. Future live deployment needs uptime/owner-response and independent restore proof.

## Validation

Phase 1 authentication/isolation; Phase 5 demo recovery; Phase 8 external review/off-device restore.

## Review point

OD-06/07; security and operations policies define closure before live.
