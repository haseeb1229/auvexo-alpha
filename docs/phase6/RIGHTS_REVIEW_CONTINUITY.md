# Same-evidence OI review continuity

Status: ENGINEERED VERIFIER; independent exact-SHA implementation review pending.
No continuation receipt, rights renewal, collection START or calendar credit is issued here.
The only admitted current source remains [the accepted DS-04-A1 scope](SOURCES_AND_RIGHTS.md).
Its exact base review is2026-10-27, due2026-11-27 or earlier relevant change.

## Why a separate review chain is necessary

OI-FWD-v1 fixes one48h warm-up and90calendar-day evaluation, so a lawful future campaign
necessarily crosses at least one project rights-review deadline. Silently extending the
base record, replacing a frozen study hash, or assigning a new study ID to reuse confirmation
observations would break provenance or holdout accounting. Review continuation therefore
uses an immutable chain separate from the fixed source/rights version and study identity.
This is engineering of a future acceptance verifier, not acceptance of any future review.

## Narrow verifier boundary

The [typed review verifier](../../src/auvexo_alpha/domain/oi_rights_review.py) accepts only
continuations that reaffirm the SAME exact base source, endpoint, symbols, product, legal
evidence hashes/URLs, personal noncommercial NONPRODUCTION use and restrictions. It does
not admit new provider terms, a new source/rights version, redistribution/live use, units,
products, endpoints or any wider DS-04 family. Changed/unknown evidence remains BLOCKED and
requires separate scoped authority; no generic provider-rights registry is introduced.

Each immutable continuation pins the base/source/evidence and previous review hash, records
its review and independent-acceptance references/timestamps and a finite next review due.
A separate externally accepted ordered digest list must exactly match the whole chain.
A locally constructed receipt or matching self-calculated hash is not represented as
independent review. There is no approval/renewal issuer or automatic acceptance in code;
trusted external digests must come from a later explicit owner/reviewer disposition.

The effective continuation interval starts at the later of the prior deadline and external
acceptance. A late review leaves an explicit admission gap. No receipt admits observations
retroactively in that gap, catches up missed collection, extends the study window or resets
T0. A receipt not externally accepted at observation time cannot stamp that observation.
The default without accepted continuation remains the original2026-11-27 hard stop.
Earlier relevant evidence/source/product/auth/unit change still stops affected work.

## Fixed study and immutable lineage

The base source/rights hash, code hash, study ID, original owner START timestamp, T0,
preregistered formulas and90day window remain fixed across same-evidence continuations.
Observations carry the receipt hash active at their original admission time, or no receipt
within the initial base interval. Their manifests bind that stamp into canonical hashes.
Features may straddle a timely review boundary only when exact source/unit/parser/code/base
rights semantics remain unchanged and both original observations independently pass admission.
No numerical feature or empirical threshold changes because a review receipt changes.

The store threads the verified review context through immutable publication and derived-ledger
recomputation. Scoring verifies original observation admission; final interpretation additionally
requires current accepted review coverage and binds the review-chain hash in its typed result.
No predictability result can approve review continuity or satisfy the separate OI-16 value gate.
START/configuration bind the immutable base source/rights and original study window.
Each future task invocation separately supplies the externally accepted ordered review
digests; task XML can represent them while remaining disabled in this run. Updating
review evidence never changes original owner_start_at, T0 or the study window. Changing
that window to rescue insufficient evidence remains prohibited.

## Evidence and remaining external gates

Only synthetic continuation fixtures may be used for engineering tests in this run.
No current continuation receipt, later deadline, owner acceptance, dataset, task or START is
created. Before actual collection require exact-SHA implementation acceptance, explicit owner
START, current source/rights/unit/clock/retention/security evidence and independently accepted
continuations as each review becomes due. Missing/invalid/expired/changed continuity blocks
admission and interpretation, leaves gaps, and can make the fixed study INCONCLUSIVE.
This verifier supplies no empirical value, strategy promotion, broker or money authority.
