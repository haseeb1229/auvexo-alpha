# ADR-034: Open-interest committed START acceptance and slot gap records

Status: ACCEPTED on 2026-11-15 with its implementation, after the independent review
recorded in [the OD-23 review](../reviews/OD23_INDEPENDENT_REVIEW_2026-11-15.md). No START, acceptance file, OI database, secret or task is created.
The frozen [preregistration](../phase6/EXPERIMENT_PREREGISTRATION.md) and every
preregistered number are unchanged.

Date: 2026-11-13. Owner: founder. Author: Claude (founder-requested OD-23 closure run).

Requirements: findings OI-4 and OI-9 of the
[rebaseline audit](../reviews/AUVEXO_FULL_A_TO_Z_REBASELINE_2026-11-12.md);
[ADR-026](026-ds04-open-interest-intelligence.md);
[runtime deployment](../phase6/OI_RUNTIME_DEPLOYMENT.md) (dated 2026-10-28; its
"future task binding" and "migration head 0005" lines are superseded here).

## Context

- **OI-4.** A day counted as genuine because the caller labelled it so, and START was
  accepted when a digest supplied on the command line equalled the hash of an envelope
  supplied by the same party. The collector could, in effect, accept itself.
- **OI-9.** A slot that was missed, refused or blocked left no durable record, so the
  evaluation calendar could not show why a day had fewer observations. The clock gate
  (sync no older than 3600 seconds) fails on a stock Windows host between its 4.5-hour
  polls even when the clock is close.

## Decision

1. **START is a committed file.** Acceptance exists only as an entry in
   `acceptance/oi-start-acceptance.json`, read with `git cat-file` from the commit the
   build gate proved, never from the working tree or a command-line path. An entry binds
   the owner intent, the START envelope (release, config, code, source, rights review and
   preregistration hashes, owner reference), the study id, the runtime identity (checkout
   and exact interpreter bytes), the commissioning clock evidence and the independent
   review reference. The START digest is the hash of that entry.
2. **Build gate.** The acceptance binds the release, so it cannot live in the release
   commit. HEAD must equal the release, or be a descendant whose only difference from it
   is that one file. Clean-tree, code, lock, preregistration and imported-tree checks are
   unchanged.
3. **The collector cannot accept itself.** `--start-envelope` is removed. The task passes
   only `--accepted-start-hash`. The collector never writes Git.
4. **Lineage, not labels.** Each manifest records the START digest and its transport.
   Evaluation treats data as genuine only through a lineage that binds the study to its
   committed START and covers every input and scored target, built by the store from
   manifests it re-verifies (this START, production transport, valid, personal research,
   no conflict). A label can only lower the result. Without lineage the result is
   ENGINEERING_ONLY. One study per database is enforced. The public evaluation accepts
   no lineage or START. The only genuine route is the store's evaluation entry point: it
   runs the build gate on its checkout, reads the START from the proven commit, requires
   that START to bind the given config, and derives the lineage itself.
5. **Gap records.** Every scheduled slot that has no manifest gets an append-only gap
   record with a reason from a closed list: the specific refusal when the run reached the
   database, `OI_NO_RUN_RECORDED` for a host that was off, a task that did not fire or a
   refusal before decryption, written on the next authorized run (including the slots
   left when the window closes), or the catch-all `OI_REFUSED_UNCLASSIFIED`. Nothing is
   fetched for a past slot. A symbol slot is a gap or a valid snapshot, never both: a
   gapped slot is never fetched or stored. The calendar reports recorded gaps; no
   statistic uses them. Limit: gaps are written only by an authorized run, so if no
   authorized run happens after the window closes (rights expired, START no longer valid,
   task removed), its trailing slots have neither a manifest nor a gap. They still carry
   no data, so no result can count them.
6. **Clock.** The one-hour sync age and one-second bound are frozen and stay. The owner
   configuration that satisfies them on a stock host, and a read-only diagnostic, are in
   [clock trust](../runbooks/CLOCK_TRUST.md).

## Alternatives

- **Cryptographic signature on START.** Stronger, but needs a key-management decision and
  a key the owner holds outside this laptop. A reviewed commit is the step available now.
- **A local journal for refusals before decryption.** Rejected: it would carry no
  evidential weight, being writable by the same party without the database role.
- **Lower the sync-age rule.** Rejected: frozen, and the host can be configured to meet it.

## Consequences

- A local owner can still create a commit. START is no longer an internal runtime label
  but a commit in the pinned checkout's history that a reviewer compares against the
  digest every manifest records.
- The OI runtime now follows the main-chain head (`0006` and later) instead of `0005`.
- Onboarding order: commit the acceptance file after review, then re-pin, then START.

## Validation

Tests cover the committed-file reader (size, duplicate keys, nesting, declared size), the
acceptance-only descendant rule, refusal of a self-computed digest, the CLI order, lineage
coverage and its refusal on a corrupt artifact, labels that cannot raise a result, a
hand-built lineage or uncommitted START that cannot make a result genuine, the genuine
path through the build-gated entry point on PostgreSQL, one study per database,
append-only gap records with hash checks and a closed reason list, missed and trailing
slots becoming gaps, a slot that is never both gap and snapshot, and the clock diagnostic
against recorded `w32tm` outputs.

## Review point

Independent review of the implementing pull request, and again of the actual acceptance
file before any START.
