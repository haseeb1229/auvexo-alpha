# ADR-030: DS-03 adapter independent-review corrections and onboarding preconditions

Status: ACCEPTED amendment to ADR-029; ENGINEERING_ONLY; NO_ACTUAL_ACCOUNT_SESSION.
Date: 2026-11-12. Owner: founder. Reviewer: Claude (founder-requested independent rebaseline).

Requirements: M5-04, M5-05, M5-08, M5-12, M5-13, M5-14 in the
[actual adapter requirements](../phase2/DS03_ACTUAL_ADAPTER_REQUIREMENTS.md).

## Context

[ADR-029](029-ds03-mt5-readonly-adapter.md) froze the actual MT5 read-only adapter design
before code and required a fresh exact-SHA independent review of PR #12 before merge.
The founder replaced the previous operator and asked for an independent base-to-head
re-audit of `68dd54ad920fcbdf4375d813c6124e03ef8c7233` rather than reliance on earlier
PASS reports. ADR-029 and its three companion documents keep their original bytes; this
ADR records what the review found, what changed, and what the code still cannot prove.

The review read every changed source file and ran native probes on the Windows host.
Three defects were proven, none of which the existing tests could detect:

1. The provider child could never start. The parent launches it with an environment of
   only `SYSTEMROOT` and `WINDIR`. The fixed runtime root was derived with `Path.home()`,
   which needs `USERPROFILE`; in that child it raises, so `measure_binding` refused and the
   child exited before admission. Every test replaced the launcher or the home lookup, so
   the suite passed while the production composition was dead. The same lookup in the
   parent also let an inherited `USERPROFILE` relocate the "fixed" runtime.
2. The source binding omitted executed code. `connector_source_hash` covered sixteen
   modules, but the child also executes four package `__init__.py` files. A change there
   would not have changed the hash that the authority binds. The accepted synthetic
   connector's binding had the same omission.
3. The M5-08 static proof did not cover the actual adapter. The AST capability test
   inspected only the synthetic files; nothing statically pinned the SDK surface used by
   `ds03_mt5.py` to the ADR-029 allowlist.

## Decision

Correct the three defects inside PR #12 and merge it only after the full verification
matrix passes on the corrected exact commit.

- Derive the owner profile from the process token with the Windows known-folder API
  (`FOLDERID_Profile`), requiring the current and default locations to agree. The fixed
  runtime remains `<owner profile>/Desktop/Auvexo Alpha MT5 Readonly Runtime`, the same
  directory ADR-029 names; only the derivation changes. No environment variable is read.
- Bind every first-party module the child executes, for both the actual and the synthetic
  connector, and prove it with an independent import-closure test.
- Add static proofs that the SDK handle is reached only as a direct call to one of the
  fourteen ADR-029 functions, that the typed provider stub exposes exactly those functions,
  and that the actual adapter sources contain no trade, selection, subscription, login or
  dynamic-dispatch call and no network import.

No allowlist, bound, authority rule, credential rule or refusal is relaxed.

## Onboarding preconditions recorded by this review

These are not code defects in PR #12. They are facts the code cannot establish and that
a later PRIVATE onboarding ADR must resolve before any actual session. Each one denies
qualification until resolved.

- **Source rights are unresolved and currently adverse.** The Exness (SC) and (VG) Client
  Agreements dated 24 July 2026 restrict collecting or storing quotes for any purpose
  other than the client's own trading, restrict software that automates obtaining
  information through the platform, and prohibit AI analysis software against the
  platform, while another clause permits storing and analysing information for oneself.
  Which entity contracts with the owner's account is visible only in the Personal Area.
  This is an owner legal decision; package licence and read-only access grant no rights.
- **Server-time basis is unattested.** MT5 reports bar, tick, order and deal times in
  trade-server time. The adapter labels them as UTC event time. A server offset other
  than zero would mislabel history without any refusal. The offset must be evidenced as
  zero, or the contract extended under a superseding ADR, before any DS-03 timestamp is
  used as UTC. All DS-03 evidence already carries `STRUCTURAL_ONLY_CLOCK_BLOCKED`.
- **Reference digests are not anonymous.** Account and server references are unsalted
  SHA-256 digests of low-entropy values and can be reversed by enumeration. Any artifact
  containing them is private account data and must never enter public history.
- **The authority is an integrity binding, not an authorization proof.** A caller that
  can construct an authority can also compute its digest. Independence comes only from
  the outer composition that supplies the accepted digest, which does not exist yet.
- **Demo continuity.** Exness deletes inactive demo accounts after an unpublished period,
  and a read-only session performs no trading or balance operation.
- **Unproven provider compatibility.** The terminal has never been run under the stripped
  environment and the 1 GiB kill-on-close Job. Same-millisecond ticks, floating
  `trade_tick_value` on cross-currency symbols and daily swap changes each close the
  session by design; whether real feeds trigger them is unknown.
- **Diagnosability.** Every refusal is the single redacted code `DS03_UNAVAILABLE`.
  Onboarding needs a closed set of non-secret reason codes before a refusal can be
  explained; adding them is a contract change for that later ADR.
- **Third-party runtime bytes.** Only the SDK payload and the NumPy version are verified
  at run time. Other installed packages rely on the hash-locked install.

## Alternatives

Merge `68dd54a` unchanged because hosted CI was green: rejected; the production path was
proven dead and the binding incomplete. Pass `USERPROFILE` into the child: rejected; it
reintroduces an inherited override of the fixed runtime. Leave the synthetic binding as
accepted: rejected; the same omission is the same defect. Rewrite ADR-029: rejected; a
frozen design is amended by a new ADR, not edited.

## Consequences

`connector_source_hash` values change for both connector families because four files
joined each inventory; no stored authority exists, so nothing is invalidated. Actual
onboarding stays blocked on the preconditions above, on return of the repository to
PRIVATE, and on separate owner authority. This ADR grants no account, session,
credential, order or money authority and earns no source qualification.

## Validation

Native Windows tests start a real child with the exact production environment and with
poisoned home variables and require the same fixed root. An AST import-closure oracle
checks both binding inventories in both directions. Three static tests pin the SDK
surface. Focused DS-03 tests, the full Windows non-integration suite, strict typing,
lint and format pass locally; full Linux PostgreSQL, frontend and audit checks run in
hosted CI on the exact commit. Results are recorded in the
[independent review](../reviews/PHASE_2_DS03_ACTUAL_ADAPTER_INDEPENDENT_REVIEW.md).

## Review point

Before any actual DS-03 session: a PRIVATE onboarding ADR that resolves each precondition
above with evidence. Any new contradiction between provider behaviour and these controls
stops that lane.
