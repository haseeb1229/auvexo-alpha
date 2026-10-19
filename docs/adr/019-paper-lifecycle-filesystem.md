# ADR-019: production lifecycle history and isolated pytest cache

Status: FROZEN clarification; local implementation verified, independent review pending
Date: 2026-10-19
Requirements: R-006-P4-01/02, R-023-P4-01, R-025-P4-01

## Context

The [fourth resume](../reference/PHASE_4_FOURTH_RESUME_BRIEF.txt) authorizes correcting
production initial registration and the exact project-created pytest cache that blocks
quota traversal. The stopped aggregate is
`3da10c80d5b6a0d9adccb2efe5c36531ccb8829c28a12a8545df6abc5000c929`.
All recovery packages and frozen acceptance criteria remain preserved.

## Decision

A production release identity starts once, in RESEARCH only. Every later immutable
snapshot requires an explicit legal transition bound to the latest durable identity,
state, hashes, actor, evidence and time. Serialize concurrent transitions per identity;
reject stale, cross-identity, duplicate, hash-changing or history-free writes. Persist
the snapshot and its history atomically; derive current state only from that consistent
history. Retain the frozen explicit suspension/resume and terminal retirement rules.
Fixture PAPER initialization stays separate and cannot qualify production history.
Only synthetic isolated TEST databases may exercise production lifecycle metadata.
Production suspension may resume to PAPER only after that identity previously reached
PAPER through complete history; early suspension cannot become a promotion shortcut.

Before any ACL change, prove the exact `.local/pytest-phase4-sandbox` provenance,
complete content inventory, owner/ACL and absence of reparse points. Stop if uncertain.
Only this proven synthetic cache tree may receive minimum owner read/list/traverse
access; retain SYSTEM/Administrators protections and record before/after evidence.
No other managed path, credential, data, quota calculation or scheduler permission changes.

Prevent recurrence by putting synthetic pytest cache state outside the managed quota
root using an existing temporary-state convention, or creating it with intended owner
inheritance. Keep unexpected unreadable managed directories fail-closed; no catch,
quota exclusion, weakened accounting or skipped test. Prove remaining in-root bytes
are counted and rerun the unchanged data/research recovery path normally.

## Alternatives

Reject advanced initial production states, history-free updates, stale predecessor
transitions, fixture-derived production history, broad ACL grants, quota exclusions,
ignored traversal errors and permanent synthetic cache state in managed storage.

## Consequences

The current projection derives from validated immutable history; no extra mutable
production projection, privilege or migration is needed. The canonical pytest wrapper
uses unique temporary cache state outside managed storage and cleans it on failure.

## Validation

Fourth-resume order supersedes earlier sequences: focused lifecycle cases, filesystem/
quota and data/research recovery, all real PG correctness, full direct-LOGIN security,
full inherited suite, then remaining mandatory checks. Preserve all prior risk/truth/
loss/freshness/identity guards. Any new material invariant failure stops again.

Rerun the same performance workload and report every primary/wave percentile and miss.
A target miss requires reviewer disposition; never label it full acceptance.
The fourth brief reported PRIVATE. The authenticated remote recheck instead reported
PUBLIC, and the owner confirmed during this resume that they had just made it public.
This supersedes only the brief's current visibility statement. Preserve actual PUBLIC
visibility without changing settings or rewriting dated history. The temporary public
exception and its independent governance review due 2026-10-24 remain unresolved;
no permanent-public, billing, permissions or runner authorization is inferred.
No candidate/champion, persistent observation, Phase 5, broker,
money, permit issuer or runtime AI work. Exact-final-SHA independent review remains required.

## Review point

GPT-5.6 Sol exact-final-SHA review before merge or persistent observation. Historical
passes cannot replace the fourth resume's affected-gate reruns or performance disposition.
