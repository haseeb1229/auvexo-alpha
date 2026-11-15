# ADR-035: DS-03 onboarding contract corrections

Status: ACCEPTED on 2026-11-15 with its implementation, after the independent review
recorded in [the OD-23 review](../reviews/OD23_INDEPENDENT_REVIEW_2026-11-15.md). ENGINEERING_ONLY; NO_ACTUAL_ACCOUNT_SESSION. DS-03 rights remain
unresolved ([owner packet](../reviews/DS03_RIGHTS_OWNER_DECISION_PACKET_2026-11-13.md)).

Date: 2026-11-13. Owner: founder. Author: Claude (founder-requested OD-23 closure run).

Requirements: findings R12-5 to R12-8 of the
[rebaseline audit](../reviews/AUVEXO_FULL_A_TO_Z_REBASELINE_2026-11-12.md); amends
[ADR-029](029-ds03-mt5-readonly-adapter.md) and [ADR-030](030-ds03-adapter-independent-review-corrections.md)
without editing them.

## Context

ADR-030 left four onboarding preconditions as recorded findings: the adapter labelled
MT5 server times as UTC without evidence (R12-5); account and server references were
unsalted hashes of low-entropy values, reversible by enumeration (R12-6); every refusal
had one code, so onboarding could not be diagnosed (R12-7); and the provider runtime had
to be installed by copy without byte-compilation, with no tool to do it (R12-8).

## Decision

1. **Server-time basis (R12-5).** Raw provider timestamps are kept. A measurement step
   compares provider tick times with trusted local receipt times (at least 5 samples and
   3 distinct ticks, the freshest within 120 seconds, offset within 14 hours, and proven
   liveness: some symbol's tick must advance between two of its samples, which bounds the
   offset from above, so frozen ticks of any age give unknown) and
   classifies the basis as UTC, a whole-hour offset or unknown, with an evidence hash over
   the samples and the local clock evidence. The authority must bind a basis that is not
   unknown. A record refuses a UTC label with no bound basis or one that disagrees with it.
   Without a bound basis every time-labelling operation refuses. Bar boundaries are
   trade-server boundaries: a D1 bar and a D1 request align to server midnight, while the
   stored label stays the true UTC instant. The measurement uses only the allowlisted
   `symbol_info_tick` call.
2. **Keyed references (R12-6).** Account and server references are HMAC-SHA256 over a
   fixed purpose, version, kind and value, keyed by 32 random bytes in a new fixed
   CurrentUser DPAPI slot (`mt5-reference-key.v1`). The reference shape is unchanged. The
   key is never rotated, because rotation would silently change every reference. The
   domain only compares digests. The key must exist before metadata and authority.
3. **Reason codes (R12-7).** Refusals carry one of a closed set of non-secret reason
   codes, `DS03_UNAVAILABLE:<CODE>`, and the IPC ERROR frame carries the code. Anything
   outside the set, or secret-shaped, becomes UNCLASSIFIED or IPC_PROTOCOL. No login,
   server, password, account number or provider text appears in any code or frame.
4. **Provider runtime (R12-8).** `tools/mt5_runtime.py install|verify` installs from a
   hash-locked requirements file with pip in isolated, no-compile, no-index, binary-only,
   no-cache mode, and verifies the exact SDK file hashes, the absence of any bytecode
   cache, hard link, symlink or reparse point, and the exact interpreter. Comparing final
   resolved paths (short names, junctions and substituted drives resolved), it refuses
   any root that contains or lies inside the real fixed runtime root, and that root itself
   unless `--future-onboarding` is given. It never imports MetaTrader5.

## Alternatives

- **Assume the trade server runs on UTC.** Rejected: many MT5 servers do not, and a wrong
  basis shifts every bar.
- **Salt with a value stored in Git.** Rejected: public, so no protection.
- **Free-text error messages.** Rejected: they can carry account or server text.
- **uv for the provider runtime.** Rejected: it hard-links by default, which the binding
  refuses; pip with explicit flags is simpler to prove.

## Consequences

The error text and IPC ERROR frame now carry a reason. Onboarding gains steps: create the
reference key, install and verify the runtime with the tool, and run a measurement-only
first session to bind the time basis before any record is labelled. None of this is
authorized now; ADR-030's preconditions, including source rights and a PRIVATE
repository, still apply.

## Validation

Fake-SDK tests for classification boundaries, unbound and mismatched bases, keyed
references and their DPAPI slot, a static proof that every refusal on the actual path
names a closed code, frames free of secret-shaped text, and install and verify refusals
on temporary roots with a fake pip.

## Review point

Independent review of the implementing pull request. Any actual onboarding needs its own
PRIVATE ADR and review.
