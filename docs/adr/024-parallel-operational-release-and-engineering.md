# ADR-024: pinned operational release and parallel non-money engineering

Status: FROZEN for offline implementation, 2026-10-20; independent exact-SHA review pending.
Requirements: R-003, R-006, R-008, R-018, R-021, R-022, R-023, R-024, R-029, R-031, R-035; OF-01 through OF-12.

## Context

ADR-013 separates engineering-unblocking acceptance from operational activation. Phase4
engineering is accepted and actual-feed observation ACTIVE at pinned merge
9b9038b6966843805c99f15e1c37cdba7c026679. Full Phase4 is OPEN. A development branch in
that checkout would invalidate its scheduled source identity. The owner separately
[authorizes](../reference/PHASE_5_OFFLINE_BRIEF.txt) physically separate parallel engineering.
The accepted PAPER contracts deliberately deny DEMO and external execution; they must
not be weakened or coerced into a second operational risk implementation.

## Decision

Canonical phases0-9 and all original numeric gates remain unchanged. The active
observation checkout is a PINNED OPERATIONAL RELEASE. Its HEAD, task, activation,
config, rights, receipts and dates stay unchanged. Never silently repoint a campaign.
A separate sibling clone from founder remote may implement generic NON-MONEY
Phase5 OFFLINE/PRE-COMMISSIONING foundations. This is ENGINEERING-UNBLOCKING only;
actual Phase5 commissioning and sustained-demo clock are NOT STARTED.

One core remains authoritative across future modes: typed intents, deterministic risk,
reservations/outbox, writer fencing, reconciliation/journals, kill states and hash binds.
This foundation delegates synthetic execution to accepted PaperStore/PaperTruth under
PAPER_NONEXTERNAL semantics; it does not fork their risk/financial state machines.
DEMO account attestation and offline qualification permit contracts are design/inert
validation artifacts, never a signer/issuer or replacement for risk authorization.
Future actual commissioning needs Phase4 closure, accepted account/spec/terms/source
rights and separate explicit authorization. Credentials never grant authority.

The separate gateway process uses bounded strict authenticated local protocol and a
fake transport only. No broker SDK/import, terminal, network provider, session, real
account ID, broker credential, live permit, withdrawal/transfer or money operation.
No execution_enabled change. All synthetic state/evidence is NON_COUNTING.
Material defects affecting pinned release interpretation stop affected review; no
unreviewed patch/activation/task change. Protect Phase4 20:45-22:15 and Phase2
22:45-23:20 Pakistan from heavy development DB/recovery/clone work.

PUBLIC temporary-exception review due2026-10-24 remains unwaived. Before broker
SDK/session/credentials/DS-03/proprietary-alpha work require PRIVATE return or an
independently accepted owner-approved permanent-public superseding ADR. No settings
change. Public code contains generic sanitized framework only.

## Alternatives

Freeze all engineering until calendar closure: rejects ADR-013's scoped dependency
model. Develop inside operational checkout or change config SHA: breaks release
integrity. Enable DEMO through PAPER contracts or duplicate risk logic: weakens
accepted invariants. None is adopted.

## Consequences

Phase4 dates cannot be earned by development. Phase2 full operational remains OPEN,
DS-03 BLOCKED. Phase3 four results INCONCLUSIVE, both OOS consumed, no candidate/champion.
Offline synthetic proof is neither broker realism nor actual commissioning evidence.
New PR stays OPEN/UNMERGED for GPT-5.6 Sol exact-SHA review.

## Validation

Freeze this ADR and requirements before executable implementation. Verify physical
clone separation and pinned task/source/activation before and after. Focused malformed/
auth/replay/expiry/account/mode/permit/UNKNOWN/failure tests; unchanged risk/PAPER PG,
full unskipped suite, static/docs/scans/audit/recovery and exact-final Windows clone;
exact-head push/PR jobs and passing logs. No timing benchmark or broker tests.

## Review point

Independent exact-SHA review before merge or any commissioning proposal; operational
Phase4 closure and separate owner authority remain prerequisites for actual Phase5.
