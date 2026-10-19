# ADR-016: direct least-privilege PAPER database identity

Status: ACCEPTED/FROZEN for Checkpoint A engineering at e3f39e0397e1846c37febcebc246ea91c9f2eb78; full Phase 4 OPEN
Date: 2026-10-18
Requirements: R-002, R-022-D, R-022-G, R-023, R-025, R-026

## Context

Checkpoint A stopped after a real PostgreSQL security probe showed an admin-authenticated
verification pool losing its SET ROLE binding after rollback. The stopped source inventory
SHA256 is `f5e69f9f18ba2ef2f85ca4663d2ef00971c64c25f7c0cda3955748228bfde2f0`,
on documentation freeze `037afa282daf03eb1d03a1d9a272e5c40bf094a7` with dirty runtime work.
The owner explicitly adopted the [security-resume brief](../reference/PHASE_4_SECURITY_RESUME_BRIEF.txt).
The ignored recovery package preserves the exact tracked patch, untracked files and diagnostics.
This is permission to correct the binding and rerun gates, not Phase 4 acceptance.

## Decision

PAPER runtime, virtual truth and owner provisioning each authenticate directly through a
different least-privilege LOGIN that inherits only its one scoped NOLOGIN group. No admin
pool, SET ROLE callback, admin credential fallback or reusable approval token is permitted
at the PAPER Engine boundary. Admin is restricted to bounded migration/fixture provisioning.

Unique isolated TEST/RESTORE databases receive dedicated temporary LOGIN names and random
protected local credentials, never passwords in migrations, argv, source or logs. Provisioning
is idempotent, verifies attributes/memberships/grants and refuses drift. Cleanup owns only
the generated isolated database, its three generated LOGIN identities and private manifest.
Existing global NOLOGIN groups are inspected; merged migrations 0001-0004 remain unchanged.
The unmerged 0005 owner trigger checks actual scoped membership for the dedicated LOGIN.

The shared infrastructure validator and factory require loopback port 55432, a named isolated
database and the corresponding dedicated LOGIN. They attest current_user/session_user,
privilege flags, role expiry, exact membership and nondelegable membership options, required
PAPER grants, absence of admin membership, schema/object ownership and foundation/research
writes. Attestation runs at construction and every pooled checkout. Core store/truth
constructors independently refuse an admin Engine. Missing/bad/revoked credentials or grants
fail closed with redacted errors. Rollback cannot restore privileges the session never had.
Each direct connection requests UTC session rendering and attests it on every checkout.
This prevents local server timezone defaults from reaching strict UTC journal contracts;
timezone drift refuses reuse, while reconnect restores the UTC connection configuration.

PostgreSQL's built-in `pg_catalog.pg_settings` UPDATE is its session-local SET interface,
granted to PUBLIC by PostgreSQL. Attestation permits this exact built-in operation without
grant options; arbitrary catalog writes remain refused. The security matrix also attempts
a superuser-only `session_replication_role` change and requires denial. No service grant
is broadened. See [PostgreSQL parameter permissions](https://www.postgresql.org/docs/17/config-setting.html).

## Alternatives

Reject admin authentication plus repeated SET ROLE, accepting admin in tests, weakening
TRUNCATE CASCADE attacks, blanket privilege grants or automatic repair of unexpected role
drift. No broker-grade secret store, signing key, new dependency or persistent service.

## Consequences

The prior role tests and 95 domain tests are historical evidence, not final qualification.
Security probes run first after the collector protection window; only after they pass may
remaining PG races/outbox/reconciliation/recovery/performance and full verification resume.
Any new material invariant failure stops again. DEV schema/data, collector schedule and
qualification logic stay unchanged. All money modes, broker integration and Phase 5 stay closed.

## Validation

Prove identities and effective allowed/forbidden operations across fresh connect, normal
transaction, commit, rollback, permission error, pool reuse, dispose/reconnect, sequential and
concurrent connections. Refuse missing/wrong credentials, wrong database/role/endpoint,
revoked login/membership/grants, expired role, elevated flags and injected admin credentials.
Retain immutable UPDATE/DELETE/TRUNCATE CASCADE checks and all original Checkpoint A gates.

## Review point

GPT-5.6 Sol exact-final-SHA review before merge or persistent observation. No 14-day counter
or new PAPER task, no Phase 3 promotion, no Phase 5. Public exception review due 2026-10-24.
