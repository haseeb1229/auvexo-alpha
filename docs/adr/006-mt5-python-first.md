# ADR-006: mt5 python first

Status: PROVISIONAL
Date: 2026-10-15
Requirements: R-021, R-022, R-029

## Context

Terminal APIs can lose responses, and execution callbacks do not remove reconciliation needs.

## Decision

Start isolated Python MT5 transport behind ExecutionVenue, with polling and durable journal. Qualify actual demo; add a thin EA notification bridge only if measured constraints require it.

## Alternatives

EA-only adds MQL transport/test complexity; hybrid creates two-channel coordination risks. None provides automatic broker exactly-once behavior.

## Consequences

Windows terminal remains required for initial deployment. Single writer and broker-truth reconciliation are transport-independent. No production transport implemented now.

## Validation

Phase 5 terminal reconnect, timeout, accepted-before-crash, stop, partial/cancel and account-switch matrix.

## Review point

OD-02, execution and venue policy; decide before Phase 5 exit.
