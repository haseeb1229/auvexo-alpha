# ADR-018: retained PAPER valuation and derived mark freshness

Status: FROZEN clarification; local implementation verified, independent review pending
Date: 2026-10-19
Requirements: R-021-P4-02, R-022-P4-01, R-022-P4-02, R-022-P4-04, R-023-P4-01

## Context

The [third resume brief](../reference/PHASE_4_THIRD_RESUME_BRIEF.txt) authorizes correction
of stale-mark replay after a real PostgreSQL stop at source aggregate
`281b127ff42c0a7bad6e6b713f6cfd78a19b7d327d18dcda339f591f8d446bc4`.
The guard correctly refused a position/equity mutation without new truth. The preceding
110 security passes and 155 passing correctness cases are historical evidence, not final
qualification. All prior stopped states and logs remain preserved. The frozen acceptance
requirements, merged migrations and dependency lock remain unchanged.

## Decision

Replay selects eligible immutable marks by causal event ordering, independently of their
current age. The latest accepted observed value, FX, original observed/available timestamps
and fact identity remain valuation inputs when they age. Freshness is derived separately
against the injected UTC clock. Passage of time changes health/readiness; it cannot erase
an observation, restore a fill price, invent a value or forward-date a timestamp.

Apply the retained valuation before classifying current market and FX freshness. A stale
account remains not ready for new exposure, and bounded reductions still require current
position truth. Health changes are audited under the account lock and cannot alter financial
fields or relax stronger K2/K3/K4. Preserve the database financial mutation guard.

Older facts cannot rewind a newer observation; repeated facts are idempotent. Conflicting
same-time facts, future-dated and wrong-scope marks refuse or quarantine under the existing
fail-closed truth boundary. Missing conversion remains unpriceable; never synthesize a quote.
New valid truth may change valuation and freshness, while an existing loss latch remains
until the already-required explicit eligible owner PAPER resume.

The truth writer learns instrument scope only from its own independent ORDER or
EXTERNAL_POSITION facts. A held position supplied solely at initialization does not grant
that writer access to the owner's journal. Before publishing a mark for such a position,
publish an independent EXTERNAL_POSITION observation. An unobserved or unrelated instrument
refuses marking. This preserves the existing least-privilege grants; baseline fixtures
alone do not prove reconciled independent position truth.

## Alternatives

Reject age-filtering the historical mark map, fill-price fallback, timestamp refresh,
synthetic marks, weaker financial guards and broader service privileges. No risk threshold,
action, dependency, broker capability or persistent service is introduced.

## Consequences

The prior three fixes in [ADR-017](017-paper-risk-state-corrections.md) and direct LOGIN
boundary in [ADR-016](016-paper-direct-login.md) remain required. The third brief supersedes
their earlier verification sequence for this correction: rerun the failing stale-mark case
first, then all hard PostgreSQL correctness cases, then the full direct LOGIN security suite,
before continuing full Checkpoint A verification. A material invariant/security failure stops
again. The separate collector reporting PermissionError is not corrected by this scope.

## Validation

Prove identical financial projections at fresh T1 and stale T2 without new truth, retained
original timestamps/fact identity, repeated stale replay and restart/dispose determinism.
Cover older/duplicate/conflicting/future/wrong-scope facts and stale/missing FX. Prove a new
mark changes valuation once without clearing K2. Execute all prior collision/contradiction/
loss-latch/transaction regressions, full security and all original recovery/resource/scan/
audit/clean-clone/CI gates. Authored or collected tests never count as passing evidence.

## Review point

GPT-5.6 Sol exact-final-SHA review before any merge or persistent observation. No candidate,
champion, 14-day PAPER observation, Phase 5 or broker work. PUBLIC governance review remains
due 2026-10-24; scheduled collector windows and the no-heavy-work interval remain unchanged.
