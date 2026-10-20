# Offline gateway foundation implementation

Status: ENGINEERING_ONLY, offline implementation pending exact-source independent review.
Actual Phase5 commissioning and its sustained-demo clock have not started. This document
maps the implementation to the frozen [ADR024](../adr/024-parallel-operational-release-and-engineering.md),
[acceptance requirements](OFFLINE_ACCEPTANCE.md) and [operations runbook](OFFLINE_RUNBOOK.md).

## Implemented boundaries

The domain [gateway contracts](../../src/auvexo_alpha/domain/gateway.py) provide immutable,
strict versioned envelopes, discriminated payloads, canonical hashes, bounded financial
Decimal strings and UTC times. Account attestation compares separately pinned synthetic
identity, account kind, server, currency, account mode and capability metadata. The offline
DEMO permit is inert design validation. No permit issuer, signer or operational authority
is implemented, and a credential or successful validation cannot enable execution.

The application [ports](../../src/auvexo_alpha/application/gateway_ports.py) define narrow
synthetic PAPER and truth operations alongside an unimplemented future transport shape.
The [coordinator](../../src/auvexo_alpha/application/offline_execution.py) starts without
readiness, requires explicit attestation and reconciliation, and binds readiness to the
account and writer epoch. It delegates financial decisions and durable delivery state to
the accepted core. Its [thin adapters](../../src/auvexo_alpha/infrastructure/offline_paper.py)
call existing PaperStore and PaperTruth methods. Existing financial core files, accepted
PAPER risk rules and migration history remain unchanged; there is no new financial state
machine or migration.

The [fake transport](../../src/auvexo_alpha/infrastructure/fake_execution.py) records only
synthetic authoritative facts through those accepted truth methods. The committed accepted
claim precedes its first effect. Timeout or process-crash simulations preserve attempted
state and reservation capacity. Reconstructed coordinators query and reconcile; they do
not use an in-memory sent list as restart authority or blindly resend. Unexpected failures
propagate while the durable attempted command remains recoverable. Partial/late fills,
rejection, cancel/fill races, external synthetic positions, fencing, protection and kill
states continue through the same accepted PAPER reconciliation and pause rules.

The separate [inspection process](../../tools/offline_gateway.py) uses the
[authenticated pipe adapter](../../src/auvexo_alpha/infrastructure/gateway_ipc.py).
It accepts inherited anonymous stdin/stdout only, with a per-launch ephemeral fake IPC
key delivered through the inherited pipe. Entire envelopes, session identity and sequence
are HMAC authenticated with constant-time comparison. Size limits, duplicate command
checks, expiry and context binding checks fail closed with stable redacted errors.
The process returns hello, health, synthetic account/spec metadata and empty inspection
snapshots. Health stays RECONCILE_ONLY and every dispatch is UNSUPPORTED. The in-process
durable PAPER coordinator is the sole synthetic dispatch path; this inspection process
has neither financial state nor an operational transport.

## Requirement and evidence map

The linked tests specify concrete proof. Final run receipts, exact-source checks and
review disposition are reported in the handoff; this document does not predeclare them.

| Requirement | Implementation and verification |
| --- | --- |
| OF-01 | Physically separate development clone; before/after pinned operational checkout, task, activation and configuration checks are retained in the private handoff. No development receipt contributes an observation date. |
| OF-02 | `domain/gateway.py`; [protocol tests](../../tests/test_gateway_protocol.py): `test_protocol_canonical_roundtrip_and_expiry`, `test_protocol_ambiguous_malformed_or_oversized_json`, `test_protocol_unknown_version_mode_type_and_hash_rejected`, `test_arbitrary_bytes_never_produce_untyped_protocol_objects` and exact dispatch-binding negatives. |
| OF-03 | `infrastructure/gateway_ipc.py` and `tools/offline_gateway.py`; [real process tests](../../tests/test_gateway_process.py): `test_real_process_health_and_empty_reconcile`, `test_process_auth_tampering_redacted`, `test_entire_envelope_auth_and_constant_time_compare`, `test_process_duplicate_command_refused`, `test_process_oversize_frame_closes_redacted` and `test_actual_process_restart_rejects_captured_session`. These launch actual child interpreters on inherited pipes. |
| OF-04 | `AccountAttestation`, `require_attestation` and coordinator startup/pre-send attestation; protocol tests `test_account_drift_refused` and `test_real_unknown_account_and_credentials_grant_zero_authority`; [PostgreSQL tests](../../tests/test_offline_execution_postgres.py) `test_offline_identity_drift_revokes_readiness_and_latches_pause`, `test_offline_readiness_is_bound_to_exact_account_and_epoch` and `test_offline_identity_drift_between_startup_and_send_refuses_before_claim`. |
| OF-05 | `OfflineDemoPermit` and `validate_offline_permit` are inert design artifacts; protocol tests `test_inert_permit_fail_closed`, `test_permit_tampering_real_scope_and_binance_derivative_denied` and `test_dispatch_paper_exact_bindings_and_no_demo_authority`. No permit result is wired to a transport authorization path. |
| OF-06 | `application/offline_execution.py` and `infrastructure/offline_paper.py` delegate existing PAPER_NONEXTERNAL authorization, reservation, outbox, claim, truth, reconciliation and kill behavior. PostgreSQL tests exercise unchanged accepted stores; inherited risk/security suites remain required. |
| OF-07 | `test_offline_claim_is_committed_before_first_send_and_duplicate_cannot_send`, `test_offline_ambiguous_attempt_restart_queries_only_and_retains_capacity`, `test_offline_unattempted_reservation_restart_never_dispatches` and `test_offline_unexpected_transport_corruption_propagates_and_restart_never_resends` prove durable recovery with newly reconstructed coordinator/transport objects. |
| OF-08 | PostgreSQL tests `test_offline_rejection_is_authoritative_synthetic_fact_not_new_risk_rule`, `test_offline_partial_duplicate_and_cancel_fill_race_preserve_facts`, `test_offline_reject_with_late_partial_remains_unknown_until_bound_finality`, `test_offline_late_ack_cannot_free_unknown_capacity_or_trigger_resend`, `test_offline_external_position_requires_reconciliation_and_stays_paused` and writer-fence negatives retain accepted accounting semantics. |
| OF-09 | `FutureExecutionTransport` is interface shape only; `FakeExecutionTransport` is synthetic-only. There is no SDK, terminal, provider connection, broker credential loader, withdrawal or transfer interface. `test_real_process_dispatch_always_refused` proves that even a valid PAPER dispatch cannot execute through the child. |
| OF-10 | Runbook and coordinator startup, reconnect, failed protection and shutdown methods; PostgreSQL tests `test_offline_initial_and_reconstructed_coordinator_refuse_before_startup_reconcile`, `test_offline_disconnect_and_failed_protection_require_owner_recovery` and `test_offline_current_dispatch_guards_precede_send` exercise reconciliation-only recovery, disconnect, revocation and kill behavior. |
| OF-11 | Focused protocol/process/PostgreSQL tests plus unchanged [import boundaries](../../tests/test_boundaries.py), inherited real-PG correctness/security, full unskipped suite, Ruff, strict typing, documentation/instruction equality, scans, locked audit, recovery and exact-final Windows clone/hosted CI evidence are required. Final evidence belongs in the handoff. |
| OF-12 | Phase4 observation remains ACTIVE/full OPEN in its pinned checkout; Phase5 commissioning NOT STARTED. Phase2 full operational acceptance remains OPEN and DS03 BLOCKED. Fixtures, restores and development output are NON_COUNTING and confer no source, alpha, strategy-promotion or money authority. PUBLIC October24 governance and DS02 November16 rights reviews remain open gates. |

## Limits and future gates

The inherited-pipe bootstrap assumes a trusted parent exclusively controls inherited
handles. Ephemeral HMAC authenticates that local inspection session; it does not certify
cross-user isolation, Windows ACLs, a credential service or persistent operational IPC.
The launching harness supervises process timeouts and cleanup. Fresh process identity
prevents inspection-frame replay across restart; durable financial replay protection comes
from the accepted PAPER store, not the child's temporary duplicate set.

Synthetic account/spec/fill/failure fixtures do not establish broker realism, actual
Exness behavior, source eligibility, live permissions or qualification days. Empty child
snapshots describe its absence of financial state and cannot reconcile an external account.
Same-disk restore proof is not off-device encrypted disaster recovery. Future transport
protocols are unimplemented and inert permits cannot authorize account access or orders.
Actual commissioning requires the separate roadmap gates, completed applicable Phase4
review, qualified account/spec/terms/source evidence, security review and explicit owner
authority. This foundation enables no DEMO/REAL execution or change to execution settings.
