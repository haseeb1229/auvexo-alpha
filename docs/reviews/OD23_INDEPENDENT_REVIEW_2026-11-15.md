# OD-23 independent review, 2026-11-15

> Dated record. The current state is in [STATUS](../STATUS.md). This records the
> independent review of the OD-23 engineering closure
> ([closure record](AUVEXO_OD23_ENGINEERING_CLOSURE_2026-11-15.md)) before merge. It
> authorizes no START, re-pin, task change, database start or money action.

## Method

Three reviewers that did not write the code each read one area of the uncommitted change
on `0617c78`, against the governing ADRs and the audit findings, read-only, with focused
unit tests and scratch scripts outside the repository. Each finding was verified against
the code before it was reported. Fixes were then made by implementers that had not
reviewed them, and the full suite was rerun afterwards.

| Area | Scope | Governing decisions |
| --- | --- | --- |
| PAPER kernel and campaign v2 | Migrations `0007` and `obs0002`, kernel, ledger replay, observation runner, gates, provenance, qualification, gateway | ADR-032, ADR-023 |
| Data, research, rights, database and CI | Migration `0006`, collectors, reports, research ledger, rights history, disposable clusters, SCRAM roles, CI | ADR-033, ADR-031, the rights renewal |
| Open interest, DS-03 and gateway | OI START, lineage and gap records, DS-03 time basis, keyed references, reason codes, runtime installer, gateway IPC | ADR-034, ADR-035, ADR-030 |

## Findings and resolution

No finding was CRITICAL.

| Area | Sev. | Finding | Resolution |
| --- | --- | --- | --- |
| PAPER | HIGH | The runner reconciled after each symbol, so the other symbol's mark was always just over the 60 s market age. Holding BTC and ETH together raised K1 every minute, the night ended at K1 and the standing resume then refused every later night. Fail-closed, but it made v2 unreachable. | FIXED: both symbols are marked for the same bar end and reconciled once per completed pair; a PostgreSQL runner test holds both across a minute boundary. |
| PAPER | LOW | The roll guard in `0007` did not bind the new day start to the database clock, so a hostile runtime session could roll to a future midnight and reset the daily loss base. | FIXED in `0007`, with PostgreSQL tests. |
| OI | MEDIUM | A caller could build its own lineage and get a genuine result; the recorded-study entry read START from a caller-supplied root without the build gate. | FIXED: the public evaluation always returns ENGINEERING_ONLY; only the store entry point, after the build gate and the committed START, can produce a genuine result. |
| DS-03 | MEDIUM | Ticks uniformly stale by about an hour were classified as an offset one hour smaller. | FIXED: classification requires a tick to advance during the measurement, otherwise UNKNOWN. A live feed that delivers every tick an hour late remains undetectable and is documented. |
| DS-03 | LOW | The runtime-root refusal could be bypassed with an 8.3 name, junction or substituted drive. | FIXED: resolved-path comparison; any overlap with the fixed root refused. |
| OI | LOW | Slots after the last run and before the window end never got gap records. | FIXED when an authorized run follows the window end. If none does, the trailing slots have no record; they carry no data, so no result counts them. Stated in ADR-034 §5. |
| OI | LOW | Gap reasons were a pattern, not a closed set; a slot could get both a gap and a manifest under a race. | FIXED: closed set with one catch-all code; gap and snapshot exclusive under one lock. |
| DS-03 | LOW | Daily bars always failed alignment under a non-zero server offset. | FIXED: alignment checked in the server basis. |
| Data | LOW | A probe on one host shortened a legacy host-less cooldown in reports for both hosts. | FIXED: one span per host. |
| Research | LOW | With raw SQL the research role could freeze a selection before the validation grid existed and file trials without a read. | FIXED in `0006`: complete grid required to freeze, every trial needs an authorized read receipt of its phase. The remaining limit (the database cannot prove a result was computed from the bars read) is stated in ADR-033. |
| Data | LOW | The data recovery drill did not cover the `0006` tables or take the cooldown lock. | FIXED; per-study locks are not taken (deadlock order), so the drill runs with no research worker, as the runbook says. |
| Research | LOW | Any change to a research-hashed module, including a rights renewal, strands an open holdout. | ACCEPTED as an operating rule in ADR-033 and the preregistration template: no such release while a holdout is open. |
| Tests | LOW | Dead CI port bypasses in two test helpers. | FIXED. |

## Re-verification of the fixes

Each reviewer then checked the fixes for its own findings.

- **Data and research:** all five VERIFIED, no regression; 230 unit and 56 PostgreSQL
  tests passed in the reviewer's rerun.
- **OI and DS-03:** M1, M2, L1, L3 and L4 VERIFIED, L2 partial (resolved as above). Two
  new LOW issues, both fixed: two port tests still expected the removed CI bypass (now
  expect refusal everywhere), and a gap recorded during a fetch escaped the collector
  without its reason (now BLOCKED with `OI_SLOT_GAP_RECORDED`, nothing stored, other
  symbol still gapped; unit test added). Also noted: a time-basis request with no more
  samples than symbols can only return UNKNOWN, which fails safe.
- **PAPER:** both fixes VERIFIED, no regression (211 unit and 41 PostgreSQL tests in the
  reviewer's rerun). The implementer also found and fixed a day bug: the runner used the
  UTC date while the database binds the Pakistan date, so any run started between 19:00
  and 24:00 UTC failed its closes and left no receipt (scheduled runs at 16:00 UTC were
  not affected). It also noted that under v1 a simulated close filled only when the next
  close, less 5 bp, was at least the decision close, so a night could end with a position
  open and every later night's roll would refuse. A v2 close is now marketable at the
  planner's existing 1% stop distance, with the fill price model unchanged (ADR-032
  OBV2-02 amended); the reviewer VERIFIED it, including that a close re-proposed while one
  is reserved is denied as OVER_CLOSE without raising a kill, so there is no double close
  and no loop. Two LOW notes remain by design: a position still open at 17:00 is valued
  past 60 s at the closing reconcile and raises K1, and a close proposed on the 16:59 bar
  has no later bar to fill on. Both apply only to a night that already failed to end flat.

One integration run during the fixes ended the new two-symbol runner test at K1 under
concurrent load and could not be reproduced. The test now prints the full journal trail
on failure; the result of the targeted reruns is recorded under verification below.

## What the reviewers checked and found correct

- The standing resume clears only the writer-acquisition K1, never K2 or above, only
  after a clean previous night, bound to campaign and commit; no service role can write
  its own authority row.
- The flat-boundary roll conditions, both in the kernel and in the database guard.
- Every v1 recorded hash is unchanged: the reviewer wrapped the canonical encoder across
  450 unit tests (1,730,281 calls) and compared with the old encoding.
- Neither new main-chain migration rewrites a row; downgrades refuse; trigger functions
  pin `search_path`.
- Scheduler provenance never turns a disabled, unreadable or ambiguous log into a pass.
- The rights renewal keeps the earlier records byte-identical (hashes recomputed from the
  old registry) with identical scope.
- Disposable clusters refuse ports 55432 and 55433 and prove their marker; role passwords
  travel only as SCRAM verifiers; CI actions are pinned by SHA with read-only permissions.
- OI START is read only from the build-proven commit; the clock gate's frozen limits are
  unchanged; DS-03 refusal codes are closed and secret-free; gateway frames bind
  direction, channel, session and sequence.

## Not verified

- Real Task Scheduler event fields; the log is disabled on this host. The restart
  candidate makes an owner dry run a START precondition.
- Real Job Object and pip behaviour beyond code reading and tests with fakes.
- Whether the Exness servers run on UTC.
- That the pinned action SHAs match their tags (reviewers had no network); CI runs them.

## Incident during the fixes

One fix agent's PowerShell .NET file call resolved a relative path against the
Operational checkout and created an empty, new `tests/test_mt5_runtime.py` there. It was
deleted at once. Checked afterwards without writing: the file is absent, the checkout is
at `9b9038b` with no changed or untracked files. The rule is unchanged: absolute paths
only.

## Verification after the fixes

Local, on the final source, on 2026-11-15 (Windows, Python 3.13.16, uv 0.13.1):

| Check | Result |
| --- | --- |
| Full suite on a disposable PostgreSQL cluster (`tools/disposable_pg.py test -q`), quiet host | First head, 12:38 to 13:18 PKT: 3907 passed, 2 skipped, 0 failed. Final head (after the CI fixes below), 14:12 to 14:36 PKT: 3914 passed, 2 skipped (both non-Windows refusals), 0 failed; cluster destroyed, no PostgreSQL process left |
| `ruff format --check`, `ruff check` (src, tests, tools, migrations) | 236 files formatted; no findings |
| `mypy`, `mypy --platform linux` | no issues in 141 files each |
| `node tools/check-docs.mjs` | PASS |
| `tools/secret_scan.py`, `git diff --check` | PASS |
| Two-symbol runner test with a concurrent full unit suite | Passed once without load. Under load it once hit the 2 s statement timeout (fails closed with one INCOMPLETE receipt), and once, during the fixes, ended at K1 with the cause not captured. |
| `tools/verify_observation_recovery.py` | Refuses until 2026-11-16 00:00 UTC by design (previous-day synthetic window precedes the rights renewal); not in CI. |

Hosted CI on the first head (`5a1c892`, run 43693991237) failed in two places, both
fixed in the next commit:

- **Linux, 1 of 3909 tests.** `test_committed_file_must_be_bounded_strict_and_exact[deep]`:
  on Linux the standard JSON scanner admits 5000 levels of nesting (on Windows it hits
  its limit), so the input reached the strict model, whose refusal carried pydantic's
  message instead of the closed code `OI_START_ACCEPTANCE_INVALID`. Still a refusal, but
  not the closed one. The model's validation error now maps to the closed code, and a
  well-formed wrong-schema case tests that path on every platform.
- **Windows dependency audit.** CVE-2026-126360 in `opentelemetry-api` 1.45.1, published
  after the lock review; scoped upgrade to 1.45.2, recorded in the
  [lock review addendum](DEPENDENCY_LOCK_MATURITY_REVIEW_2026-11-13.md).

The local rerun on the new lock then failed
`test_disposable_pg.py::test_create_then_destroy_leaves_no_process_port_or_directory`, which
an implementer had seen once before and called a timing flake. Ten repeated runs failed
six times, so it was investigated rather than retried. On this host the Windows TCP table
reported a running cluster's listening socket, which has no remote endpoint, as
FIN_WAIT1, CLOSE, NONE or LISTEN from one snapshot to the next (also visible in
`netstat`). `port_bound` counted only LISTEN and NONE, so it could miss a live listener.
That also weakened the guard that refuses to start a cluster on an occupied port. It now
counts any socket on the port with no remote endpoint, whatever its reported state, and a
connected socket only in a listening state, so it can only over-count. Unit tests cover
each observed state; the same test then passed ten runs out of ten.

Exact-head CI runs for the merged head are recorded in STATUS by the follow-up change
after merge.
