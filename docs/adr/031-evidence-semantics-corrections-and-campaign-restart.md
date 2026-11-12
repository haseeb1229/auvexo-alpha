# ADR-031: Evidence semantics corrections and campaign restart preconditions

Status: ACCEPTED engineering corrections; campaigns NOT restarted; restart requires
separate owner authority and a superseding preregistration.
Date: 2026-11-12. Owner: founder. Reviewer: Claude (founder-requested independent rebaseline).

Requirements: R-035-P2-01 and R-027-P2-01 in the [Phase 2 acceptance](../phase2/ACCEPTANCE_TESTS.md);
OB-09, OB-10 and OB-12 in the [observation acceptance](../phase4/OBSERVATION_ACCEPTANCE.md).

## Context

Two campaigns are meant to earn genuine operational evidence from scheduled runs on a
pinned release: seven consecutive public-data dates
([ADR-013](013-source-specific-acceptance.md), [schedule](../amendments/SCHEDULER_2300.md))
and fourteen PAPER observation dates ([ADR-023](023-paper-observation-qualification.md)).
Those documents are frozen and are not edited by this ADR.

The 2026-11-12 [rebaseline audit](../reviews/AUVEXO_FULL_A_TO_Z_REBASELINE_2026-11-12.md)
established the following by read-only inspection:

- No scheduled public-data run has ever completed. The PAPER campaign has at most one
  qualifying date. The operational database has been down since 2026-10-23.
- The host clock is unsynchronised and about 33 seconds slow.
- The collector decided which bars are final, and which events fall in the qualifying
  window, from the local clock alone. A fast clock would store an unclosed candle as
  final; a slow clock shifts the whole window.
- A day qualified from stored events alone, so a manual collection inside the window was
  indistinguishable from the scheduled task.
- Failed nights left only a generic code, or nothing, so three weeks of failures were
  invisible.
- In the observation feed, a bar that could not be proven final ended the whole night
  without a receipt, and the qualifying-date counter became unreadable once the rights
  review date passed.
- The pinned PAPER campaign denies every proposal by construction, and the rights review
  compiled into the pinned release expires on 2026-11-16.

The pinned release can therefore complete neither campaign, and what it has recorded is
zero public-data dates and at most one PAPER date.

## Decision

Correct the evidence code in the Development line. None of this changes the pinned
operational release, its tasks, its database or anything it has recorded.

1. **Provider-time finality for public data.** Before each kline request the collector
   reads the provider's server time. It refuses the poll unless every requested bar has
   closed in provider time and the local clock is within two seconds of the provider's.
   A refusal is a durable event with its own reason code. It is not a rejected payload
   and nothing is quarantined.
2. **Scheduled provenance.** A day can pass qualification only if exactly one scheduled
   wrapper summary for that day exists, started in the pre-window and completed. This
   binds qualification to the wrapper. It still cannot prove that Task Scheduler rather
   than a person launched the wrapper; that residual is stated, not hidden.
3. **Failure evidence.** Every scheduled invocation leaves a summary, including one that
   is refused for starting outside the pre-window. Failures carry a short, non-secret
   reason code, for example that the database is unavailable. Only parser failures on
   fetched bytes quarantine a payload.
4. **Warm-up catch-up.** After an outage the warm-up, never the window, brings each feed
   up to date within its deadline and request budget. Catch-up never runs inside the
   qualifying window and never counts.
5. **Observation feed.** A bar that cannot be proven final and current is a missed bar:
   no fact, a durable event with a reason, and the run continues. The existing gap rule
   then decides the day. The finality rule itself is not widened.
6. **One receipt per night.** A failure after a run begins, or a refused PASS, records an
   INCOMPLETE receipt with a reason. INCOMPLETE never counts.
7. **Rights at receipt time.** Reading earned dates verifies each receipt against the
   rights valid when it was recorded. Starting a run still requires currently valid
   rights. Reading history never extends rights.

Rules 1, 2, 5 and 6 make qualification stricter or more complete. None lets something
count that the frozen documents exclude.

## Restart preconditions

Evidence earned under different semantics cannot be merged, and there is almost none to
lose. A restart is an owner decision and needs all of the following first:

- a reviewed release that contains these corrections, and a re-pin of the operational
  checkout that the owner authorizes;
- a superseding preregistration for the PAPER campaign that either makes authorization
  reachable (owner resume, day roll, a specification refreshed within a day, a clock
  inside the kernel's offset cap) or states plainly that the campaign is denial-only and
  what that does and does not evidence;
- a trusted clock ([clock trust](../runbooks/CLOCK_TRUST.md));
- the public-data rights review renewed by the owner
  ([rights review](../runbooks/RIGHTS_REVIEW.md));
- the operational database running, with a way to keep it running across reboots, and
  the laptop available each evening ([evidence campaigns](../runbooks/EVIDENCE_CAMPAIGNS.md));
- a new campaign identity and a new first eligible date. No earlier date transfers and no
  missed date is recovered.

## Alternatives

Patch the pinned checkout in place: rejected; it would break the pin that makes evidence
meaningful and could not be reviewed. Keep the old semantics and only restart the
database: rejected; the release still expires on 2026-11-16, still trusts a clock that
is wrong, and the PAPER campaign still exercises nothing. Widen the finality rule to
tolerate the skew: rejected; the fault is the clock, and a wider rule admits unclosed
bars. Count the nights the task tried to run: rejected; a failed or missed night is not
evidence.

## Consequences

Phase 2 and Phase 4 operational gates stay OPEN with their counters not accruing until
the owner restarts them. Engineering can continue in parallel. Public-data collection
now needs one extra public request per poll, within the existing request budget. A
skewed clock now stops collection visibly instead of producing mis-timed evidence.

## Validation

Tests reproduce the real host condition (clock 33 seconds slow), a fast clock that
exposes an in-progress bar exactly as the provider returns it, boundary values of the
skew bound, malformed provider time, manual-only days, refused and failed summaries,
missed observation bars, refused PASS receipts and the rights boundary instants.
PostgreSQL-backed cases run in hosted CI. Results are in the rebaseline audit.

## Review point

Before any restart: independent review of the superseding PAPER preregistration and of
the release to be pinned. Any new unexplained gap or contradiction stops the restart.
