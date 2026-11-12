# Status

As of 2026-11-12 (Asia/Karachi). This is the only document that states current status.
Every other document holds standing content or is a dated record. When a fact here
changes, change this file in the same commit. Each fact below was verified directly on
2026-11-12 during the [independent rebaseline](reviews/AUVEXO_FULL_A_TO_Z_REBASELINE_2026-11-12.md);
earlier status text is kept unchanged in the [history log](history/README.md).

UNKNOWN means not measured. It is never zero and never PASS.

## Classification

| Question | Answer |
| --- | --- |
| Engineering system ready | PARTIAL. The research, data, PAPER, offline gateway, read-only terminal, open-interest and DS-03 read-only code exists, is tested and was independently re-audited. Open engineering findings remain; see below. |
| Operational qualification in progress | NO. Both evidence campaigns are registered but are not accruing evidence. |
| Live certified | NO. No validated edge, no eligible champion, no live gate passed. No edge means no live launch. |

There is no account connection, no broker session, no credential, no order path that can
be enabled, no withdrawal or transfer capability, and no model-to-order path.

## Repository

- `haseeb1229/auvexo-alpha`, visibility PUBLIC. This is temporary and owner-approved
  under [ADR-027](adr/027-temporary-public-ci-and-sanitized-engineering.md) for free
  hosted CI on sanitized engineering. Long-term intent is PRIVATE. Public copies cannot
  be revoked.
- Default branch `main`. No branch protection and no rulesets exist. A protected main or
  an equivalent reviewed control is required before Phase 8, not before.
- Hosted CI runs on pull requests to `main`, on pushes to `main` and weekly. A Linux job
  runs a full-history secret scan, PostgreSQL 17, the full Python suite, format, lint,
  strict typing, docs, dependency audit and the frontend type, lint, test, build and
  audit steps. A Windows job runs the native proofs that Linux must skip and audits the
  Windows-only pins.

### Merge register

| PR | Scope | Merge commit |
| --- | --- | --- |
| #1 | Phase 0 constitution and architecture | `eafec07ee7c7a98c9cca17b5f8665494bd650751` |
| #2 | Phase 1 engineering foundation | `16e63aeb9e7e1a97082d4a004142e0af163a4571` |
| #3 | Phase 2 trustworthy data | `26b20ca5f0ef18e5300d5213b1cc8d2667bb71d3` |
| #4 | Phase 3 backtest and simple alpha | `b24c42bc07dcd9bc1b62b04d32cc92f047116125` |
| #5 | Phase 4 Checkpoint A risk and PAPER core | `dbe3cd6f47bf5a48c044df2f36cba5ea7081ca09` |
| #6 | Phase 4 Checkpoint B observation harness | `9b9038b6966843805c99f15e1c37cdba7c026679` |
| #7 | Phase 5 offline execution foundation | `1d6b08fc36884f1bc4845ac54111776d80df056b` |
| #8 | Phase 7 read-only operator terminal | `94b7d66d3c7531a513759bab202a13bf3c2500b0` |
| #9 | Phase 6A1 open-interest design | `63fd627d0166efcfe716886af31ba96f299c79da` |
| #10 | Phase 6A1 open-interest engineering | `f47770d7886d12240e24390e23f939cb49535a31` |
| #11 | DS-03 synthetic read-only foundation | `fa0915130c9572c9c2a4a260b20abeaefc2c62f5` |
| #12 | DS-03 actual MT5 read-only adapter, with ADR-030 corrections | not merged: open at `e808e816f8b7eecb68b6902149e0e87ec3f0ce8f`, independently reviewed and verified, waiting for the owner to merge |

PRs #1 to #11 are normal merge commits. The rebaseline change that introduced this file is
stacked on PR #12. Later merges appear in `git log --first-parent --merges main`.

## Phases

| Phase | Engineering | Operational |
| --- | --- | --- |
| 0 Constitution and architecture | Accepted | Complete |
| 1 Engineering foundation | Accepted | Complete |
| 2 Trustworthy data | Public spot collection and DS-03 read-only adapter code accepted. Collector clock, provenance and failure-evidence defects found on 2026-11-12. | OPEN. Zero genuine qualifying dates. DS-03 has no account, rights or qualification. |
| 3 Backtest and simple alpha | Accepted. Simulator arithmetic re-audited without error; ledger gate and evidence-binding weaknesses found. | Complete as research: four outcomes INCONCLUSIVE, both out-of-sample holdouts consumed permanently, no candidate, no champion. |
| 4 Strategy lifecycle and hard risk | Accepted. Kernel and observation findings recorded on 2026-11-12. | OPEN. At most one qualifying PAPER date; exact count UNKNOWN. The campaign as pinned cannot complete. |
| 5 Exness demo and shadow | Offline synthetic foundation accepted. | NOT STARTED. Requires full Phase 4, accepted actual DS-03 and owner authority. |
| 6 Intelligence | Open-interest collector and study code accepted; two collector defects found on 2026-11-12. | NOT STARTED. No collection, forward clock zero, value gate open, clock untrusted. |
| 7 Owner surfaces | Read-only web terminal accepted. | OPEN. No desktop, Android or voice client; no owner authentication beyond a local bearer; not connected to operational data. |
| 8 Live certification | NOT STARTED | NOT STARTED |
| 9 Controlled scaling | NOT STARTED | NOT STARTED |

"Accepted" means engineering acceptance at an exact commit, as defined in the
[roadmap](ROADMAP.md). It never closes an operational gate.

## Runtimes on the owner laptop

| Checkout | Role | Pin | Rule |
| --- | --- | --- | --- |
| `Desktop/Auvexo Alpha` | Operational. Both scheduled tasks run from it. | `9b9038b` | Never edit, fetch, switch, install, test or migrate here. Read-only inspection only. |
| `Desktop/Auvexo Alpha Development` | All engineering. | moves | Separate `.git`, no shared worktree. Its virtual environment uses the Python interpreter stored under the Operational checkout's `.local/python`, read-only. |
| `Desktop/Auvexo Alpha OI Runtime` | Prepared open-interest runtime. | `f47770d` | No database, secret, task or START exists. Do not update without a reviewed re-pin. |
| `Desktop/Auvexo Alpha MT5 Readonly Runtime` | Future DS-03 runtime. | does not exist | Created only by a later PRIVATE onboarding ADR. |

Scheduled tasks, both under the interactive owner session, so the owner must be signed in:

| Task | Trigger | Conditions | Verified state |
| --- | --- | --- | --- |
| `AuvexoAlpha-Paper-Observation` | daily 21:00 PKT | network required; does not wake the machine; cannot be started on demand; 1 h 15 s limit | Registered and Ready. Failing; see below. |
| `AuvexoAlpha-PublicData-Daily` | daily 22:57 PKT warm-up, 23:00-23:12 PKT window | AC power required, stops on battery, wakes to run, network required; 20 min limit | Registered and Ready. Failing; see below. |

Protected intervals for heavy local work: 20:45-22:15 and 22:45-23:20 PKT.

## Operational evidence

Read-only inspection of the Operational checkout's wrapper summaries, PostgreSQL logs and
Task Scheduler on 2026-11-12:

- **Phase 2: zero genuine qualifying dates.** No scheduled run has ever completed. Of the
  25 nights from 2026-10-18 to 2026-11-11, one run missed its start, eight started on time
  and failed within seconds, and sixteen left no summary because the task did not start
  in its pre-window. One of those sixteen, 2026-11-11, started 29 minutes late and was
  refused. `tools/evidence_status.py` reproduces this table without writing anything.
- **Phase 4: at most one qualifying date; exact count UNKNOWN.** The database was up at
  21:00 PKT only on 2026-10-22. The count cannot be read while the database is down.
- **Root cause since 2026-10-23:** the Operational PostgreSQL cluster on port 55432 is not
  running. Its last log line is 2026-10-23 11:58 PKT. Nothing starts it after a reboot,
  and no failure was reported to anyone.
- **Availability:** the laptop was off, asleep or on battery at trigger time on most nights.
- **Clock:** Windows Time has never synchronised (source is the local CMOS clock). The
  clock was measured about 33 seconds slow against two independent providers. A
  non-elevated resync is refused.
- **Design limits found in the pinned release.** The PAPER campaign denies every proposal
  by construction, so it exercises no authorization, reservation or fill. The 33-second
  skew makes observation polls fail finality for part of each minute. The public-data
  rights review hard-coded in the release expires on 2026-11-16, after which both tasks
  refuse and the PAPER count becomes unreadable. Renewal needs a new release, which
  restarts the campaign.

Nothing was started, repaired, retimed or backfilled. No missed night can be recovered.

## Dated obligations

| Date | Obligation | State |
| --- | --- | --- |
| 2026-11-16 | DS-01 and DS-02 public-data rights review. Enforced in code. | Due. Binance general terms could not be retrieved by automation, so the owner must read and confirm before renewal. |
| 2026-11-16 | Dependency lock maturity exception review. | Due. |
| 2026-11-16 | Secret-scan allowlist re-review. | Due. |
| 2026-11-27 | DS-04-A1 open-interest rights review. Enforced in code. | Matters only if collection is started. |
| passed | PUBLIC governance review due 2026-10-24. | Superseded by ADR-027 on 2026-11-02. |

## Gates that need the owner

1. **Restart the evidence campaigns.** Start the Operational database and keep it
   running, keep the laptop on AC power, awake and signed in from 20:45 to 23:20 PKT, and
   decide whether to restart both campaigns on a corrected release instead of the pinned
   one. Recorded credit is zero for Phase 2 and at most one date for Phase 4, so a
   restart costs almost nothing.
2. **Clock.** An elevated Windows Time resync, or a network path for NTP. Required for
   Phase 4 qualification and for any open-interest START.
3. **Public-data rights renewal** before 2026-11-16.
4. **DS-03 source rights.** The Exness client agreement restricts collecting or storing
   quotes and automated access to platform information. This is a legal decision for the
   owner, possibly with written consent from the broker. See
   [ADR-030](adr/030-ds03-adapter-independent-review-corrections.md).
5. **Return to PRIVATE** before any actual account, session, credential or confidential
   alpha work. Not needed earlier.
6. Live capital limits, legal and jurisdiction eligibility, off-device encrypted backup,
   and release integrity controls, all before Phase 8.

## Open engineering findings

The rebaseline audit lists every finding with severity and disposition. Findings that
were not fixed in that change are tracked there as required work before the phase they
block, most of them before any Phase 5 demo order.

## Safe to run, and never run

Safe in the Development checkout: format, lint, typing, documentation and secret checks,
and the non-integration test suite. See [local verification](runbooks/LOCAL_VERIFICATION.md).

Never:

- write, fetch, install, test or migrate in the Operational or OI Runtime checkouts;
- start a PostgreSQL cluster on port 55432 from the Development checkout, or run
  PostgreSQL integration tests against the Operational cluster;
- run a scheduled wrapper by hand and count it, backfill a missed date, or change a
  timestamp;
- commit a credential, account identifier, broker data, a machine identifier or
  confidential results while the repository is PUBLIC;
- re-read or reuse the consumed Phase 3 holdouts;
- place any order, in any mode.

## Where things are

- Product and authority: [constitution](PRODUCT_CONSTITUTION.md), [architecture](ARCHITECTURE.md),
  [roadmap](ROADMAP.md), [decisions and gates](OPEN_DECISIONS.md), [ADRs](adr/README.md).
- Operating the system: [runbooks](runbooks/README.md).
- Acceptance records: [reviews](reviews/). Dated handoffs and implementation records
  under each phase directory describe the state on their own date.
