# ADR-032: PAPER evidence campaign v2

Status: ACCEPTED on 2026-11-15 after the independent review recorded in
[the OD-23 review](../reviews/OD23_INDEPENDENT_REVIEW_2026-11-15.md). Frozen before
implementation on 2026-11-13; the two amendments marked below were made before
acceptance. It authorizes no START, re-pin, task change or database start. Campaign dates
under v2: zero.

Date: 2026-11-13. Owner: founder. Author: Claude (founder-requested OD-23 closure run).

Requirements: OBV2-01 through OBV2-12 below. They supersede, for campaign v2 only, the
parts of [ADR-023](023-paper-observation-qualification.md) and the
[observation acceptance](../phase4/OBSERVATION_ACCEPTANCE.md) that they name. ADR-023,
ADR-031 and those frozen documents are not edited. Findings P-2, P-3, P-4, P-7 to P-15
and G-5 of the [rebaseline audit](../reviews/AUVEXO_FULL_A_TO_Z_REBASELINE_2026-11-12.md).

## Context

The campaign registered on the pinned release cannot produce meaningful evidence. Read
from the code on 2026-11-13, every proposal it makes is denied, for five independent
reasons:

1. **Kill state.** Account initialization sets K1. Nothing in the campaign resumes it.
2. **Day roll.** The account's day starts at the UTC midnight of PREPARE. On every later
   day the kernel denies with ACCOUNT_STALE. The only roll requires the process to run at
   exactly midnight with an account snapshot taken at exactly midnight, and nothing calls it.
3. **Specification age.** Instrument specifications are pinned in the configuration with
   the PREPARE instant as `observed_at`. After 24 hours every proposal is SPEC_STALE.
4. **Market age.** The canonical policy allows a market snapshot 2 seconds old. The
   campaign's market snapshot is a one-minute bar whose `as_of` is the bar end, and a bar
   can only be proven final after the provider's clock passes that end. A request takes
   0.9 to 2.5 seconds from this host (measured 2026-11-13), so a fresh-enough proven bar
   almost never exists.
5. **Clock bound.** The proof of clock offset for each fact is the worst case over the
   request round trip, which on this network is never under 250 ms, the canonical cap.

Fourteen nights of these denials with zero ledger mismatches would measure nothing. The
audit also found kernel and database gaps that matter only once something is authorized
(P-3, P-8 to P-14), and a provenance gap: a person can start the task by hand inside the
start window and the night counts (P-7).

## Decision

Campaign v2 is a new campaign, with a new identity, new configuration version
`paper.observation.v2`, new policy version and a first eligible date fixed only by a
future owner START. Nothing earned under v1 transfers.

Its purpose is unchanged: show that the PAPER lifecycle (propose, authorize, reserve,
simulate a fill, mark, close, reconcile, journal, recover) runs every night on the actual
public feed without a ledger mismatch. It is not an alpha test. The planner stays the
existing price-independent ten-minute long/flat cycle, with marketable closes (OBV2-02).
No parameter below was chosen from market outcomes; each one follows from minute-bar
semantics, a measured host fact or a distance the planner already uses.

### Reachability (P-2, P-10)

- **OBV2-01 Owner resume at START, and a bound standing resume.** The START record binds
  one audited `OWNER_PAPER_RESUME` through the existing owner-command path. Acquiring the
  writer sets K1 on every run by design, so the START record also carries a standing
  owner authority, bound to the campaign hash and the reviewed commit, that lets the
  scheduled runner clear exactly that K1 through the same journaled owner-resume path, and
  only when all of these hold: the previous run ended flat, reconciled, with a replay
  mismatch count of zero; the day rolled under OBV2-02; and no kill was raised since the
  previous run's last reconciliation for any other reason (source gap, resource pause,
  truth quarantine, loss latch, K2 or higher). Any other kill stays until the owner
  resumes it by hand. The authority never lowers K2, K3 or K4, expires with the campaign,
  and every use is journaled with the facts it relied on.
  *Amended 2026-11-15, before acceptance, after the kernel showed that every writer
  acquisition sets K1; without it the owner would have to resume by hand every night.*
- **OBV2-02 Flat-boundary day roll.** The run must end flat: the planner already closes
  every position in the last five minutes of the window. At the start of the next run the
  day rolls only if the account is flat, reconciled, has no unknown order, no active
  reservation and no truth event after the previous run's last reconciliation. Equity
  cannot change while flat with no events, so the new day's start equity equals the
  journaled equity at that point, and the roll records that proof. If any condition fails
  the roll is refused, the account goes to K1 and the night cannot qualify. This replaces
  the exact-midnight roll for this campaign and gives it a production caller.
  To make ending flat reachable, a v2 close is marketable: its limit is the decision close
  less the planner's existing 1% stop distance, tick-floored. Under v1 a close was limited
  at the decision close and filled only when the next close, less the 5 bp slippage, was
  at least that high, so a night could end with a position open and every later night
  would refuse its roll. The simulated fill price is unchanged (the later close less
  adverse slippage), so the simulation is no more generous; only acceptance widens.
  Opens are unchanged. *Amended 2026-11-15, before acceptance, after independent review.*
- **OBV2-03 Minute-bar freshness policy.** A new policy version keeps every canonical
  risk number except three freshness bounds, set from the one-minute bar: market and FX
  age at most 60 seconds from the bar end (a bar is usable only until the next one
  closes), and a clock-offset bound of at most 2000 ms, the same bound ADR-031 applies to
  public-data collection. A fact whose proven bound exceeds it is a missed bar, as ADR-031
  rule 5 already requires. Money modes never inherit this policy.
- **OBV2-04 Pinned and fresh specifications.** Specification content stays pinned by hash
  in the configuration. At each run start the runner reads the provider's exchange
  information for both symbols (an endpoint inside the DS-02 rights scope), checks that the
  pinned tick, step, minimum quantity and minimum notional still match, and records an
  observed specification with the provider's time. A mismatch refuses the night with
  SPEC_DRIFT. A pinned specification is never silently replaced.

### Clock and provenance (P-4, P-7)

- **OBV2-05 Per-run clock gate.** A run starts only if Windows Time reports a successful
  synchronisation within the last 3600 seconds with leap indicator 0, and the measured
  provider offset bound is within 2000 ms. The start window and every window guard are
  checked against provider time as well as local time; disagreement refuses. A refusal is
  an INCOMPLETE receipt with reason CLOCK_UNTRUSTED.
- **OBV2-06 Scheduler provenance.** A night counts only if the runner's parent process is
  the Task Scheduler service and the Task Scheduler operational log holds a time-trigger
  event for this task and this instance inside the start window. A task started by a
  person (the log records a user trigger) never counts. If the log is disabled the night
  is INCOMPLETE with reason PROVENANCE_UNVERIFIABLE. Enabling that log is an owner action
  and a START precondition.

### Kernel and database prerequisites (P-3, P-8, P-9, P-11 to P-14, G-5)

The release pinned for v2 must contain, each with adversarial and PostgreSQL tests:

- **OBV2-07 Trusted inputs (P-3).** The kernel authorizes only against a market snapshot
  that matches a stored, verified truth mark; a specification whose hash is pinned in the
  campaign and observed under OBV2-04; and a `now` inside the run's proven clock bound.
- **OBV2-08 Reservation lifecycle (P-8).** An authorized reservation that is never
  dispatched is released at expiry by a journaled event. Exposure from it ends then.
- **OBV2-09 Invalid truth (P-9).** Truth that fails validation is quarantined with a
  journaled correction fact and K1, instead of making reconciliation raise on every later
  call.
- **OBV2-10 Fencing and state guards (P-11, P-12).** Writer fencing covers every write
  path, not only dispatch. A new migration adds database transition guards for account
  state: the runtime role cannot rewrite cash, equity, kill or day fields outside the
  journaled transitions, and the truth cursor advances only to an existing truth event.
- **OBV2-11 Mismatch measurement and refinements (P-13, P-14).** Each night ends with an
  independent replay of the journal into account state, compared field by field with the
  stored account; the receipt records the mismatch count. Reduce-only closes below the
  minimum quantity are allowed so a position can always be closed; withdrawals cannot
  loosen percentage caps; the database enforces the same uniqueness as the kernel; a
  spread gate exists and is recorded (bar-close snapshots have zero spread, which the
  receipt states rather than hides).
- **G-5.** Frame MACs bind direction, the child has an idle timeout and runs under a
  Job Object. No non-test launcher is added.

### Qualification

- **OBV2-12 What a date is.** A date qualifies only if all of these hold: scheduled
  provenance (OBV2-06), trusted clock (OBV2-05), specifications verified (OBV2-04), rights
  valid at receipt time (ADR-031 rule 7), day rolled (OBV2-02), at least one authorization
  that reached a terminal journaled state, the account flat at the end, and a replay
  mismatch count of zero (OBV2-11). A night with only denials is recorded as DENIAL_ONLY
  and does not count. ADR-023's closure rule is unchanged: at least 14 distinct genuine
  post-START dates and at least 14 calendar days from first to last.

P-15 is accepted as a residual for PAPER: database role separation exists only inside
PostgreSQL, because one Windows user holds every role's secret. That cannot be fixed on a
single-user host and does not affect a campaign with no money. It must be revisited
before any phase with broker credentials.

## Alternatives

- **Keep v1 and only restart the database.** Rejected: it denies everything (Context).
- **Relabel v1 as denial-only evidence.** Allowed by ADR-031, rejected here: fourteen
  denial nights do not exercise reservation, fill, mark, close or reconciliation, which is
  what Phase 4 exists to show.
- **Use the canonical 2 s market age and 250 ms clock cap.** Rejected: unreachable for
  minute bars on this network, so the campaign would again deny by construction. The
  canonical policy keeps those numbers for every other use.
- **Clear K1 automatically at each run start.** Rejected: ADR-023 forbids implicit resume,
  and an automatic clear would hide the gap or pause that set it. The bound standing
  authority in OBV2-01 is explicit owner authority, recorded at START, limited to the
  writer-acquisition K1 after a clean previous night, and journaled at every use.
- **Owner resumes by hand every night.** Rejected: the campaign would then measure the
  owner's evening availability rather than the lifecycle, and a missed resume would be
  indistinguishable from a real kill.
- **Freshen bars with receipt time.** Rejected by ADR-023 and still rejected.
- **A task-issued secret token for provenance.** Rejected: Task Scheduler cannot hold a
  secret without a stored password, which ADR-023 forbids. The operational log
  distinguishes time triggers from user triggers without any secret.

## Consequences

- Implementation (the kernel, migration `0007_paper_state_guards`, runner and receipt
  changes) follows this ADR in a separate pull request with an independent review.
- START needs the owner actions listed in the
  [restart candidate](../reviews/OPERATIONAL_CAMPAIGN_RESTART_CANDIDATE_2026-11-13.md):
  re-pin, rights renewal, clock synchronisation interval, scheduler log, database
  autostart, and an evening availability commitment.
- Nights can now fail visibly for new reasons (SPEC_DRIFT, CLOCK_UNTRUSTED,
  PROVENANCE_UNVERIFIABLE, DENIAL_ONLY). That is the intended cost of making a date mean
  something.
- The minute-bar policy makes the PAPER simulation coarser than a tick-level one. Fills
  remain simulated against later bars; nothing here claims executable prices.

## Validation

Tests must show, against PostgreSQL on a disposable cluster: a full night that authorizes,
fills, closes and reconciles with zero mismatches; each OBV2 refusal with its reason; the
flat-boundary roll accepted and each of its refusal conditions; a manual trigger and a
missing scheduler log never counting; a stale or drifted specification refused; a market
or clock bound one unit past each limit refused; a replayed journal that disagrees with
the stored account counted as a mismatch.

## Review point

Independent review of this ADR before its implementation merges, and of the release to
be pinned before any START. Any unexplained gap or contradiction stops the restart.
