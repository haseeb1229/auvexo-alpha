# OD-23 engineering closure, 2026-11-15

> Dated record. The current state is in [STATUS](../STATUS.md). A machine-readable copy is
> in the [JSON file](AUVEXO_OD23_ENGINEERING_CLOSURE_2026-11-15.json). This record closes
> engineering findings only. It starts no campaign, re-pins nothing and authorizes no
> START, database start, task change or money action.

## Scope

The [rebaseline audit](AUVEXO_FULL_A_TO_Z_REBASELINE_2026-11-12.md) left 32 findings
RECORDED: real engineering work not done in that change. This run gives each one a final
disposition:

- **FIXED**: corrected in this change, with tests.
- **ACCEPTED_RESIDUAL**: what is left is accepted, with the reason and a review point.
- **EXTERNAL_PRECONDITION**: the engineering is done; what remains needs an owner, legal,
  provider or elapsed-time action.

The audit's OWNER, FIXED and NO_CHANGE findings are not reopened here.

Decisions behind the changes: [ADR-032](../adr/032-paper-evidence-campaign-v2.md) (PAPER
campaign v2), [ADR-033](../adr/033-data-and-research-integrity.md) (data and research),
[ADR-034](../adr/034-oi-committed-start-and-gap-records.md) (open interest) and
[ADR-035](../adr/035-ds03-onboarding-contract-corrections.md) (DS-03 onboarding contract).
All four were PROPOSED before implementation and were ACCEPTED on 2026-11-15 after the
independent review in [the review record](OD23_INDEPENDENT_REVIEW_2026-11-15.md), whose
findings (one HIGH, two MEDIUM, twelve LOW, none CRITICAL) were fixed and re-verified
before merge.

## Dispositions

| ID | Sev. | Disposition | What changed | Residual or precondition |
| --- | --- | --- | --- | --- |
| OPS-6 | LOW | FIXED | Development has its own Python 3.13.16 and uv 0.13.1 under its own `.local`, hash-verified; the environment is rebuilt in copy mode. [Local state](../runbooks/LOCAL_STATE.md). | None. |
| R12-5 | MEDIUM | EXTERNAL_PRECONDITION | Server-time basis is measured from provider ticks against trusted local receipt times, requires a tick to advance during the measurement, and must be bound before any time label; daily bars align in the server basis (ADR-035 §1). | The measurement runs only at DS-03 onboarding, which is blocked by unresolved Exness rights. |
| R12-6 | MEDIUM | FIXED | Account and server references are HMAC-SHA256 keyed by a DPAPI slot, never in Git (ADR-035 §2). | None. |
| R12-7 | LOW | FIXED | A closed set of non-secret reason codes on every refusal and IPC error frame (ADR-035 §3). | None. |
| R12-8 | LOW | FIXED | `tools/mt5_runtime.py install` and `verify` install by copy, without bytecode, hash-locked (ADR-035 §4). | Use is an onboarding step; not authorized now. |
| D-7 | MEDIUM | FIXED | `compare-sources` records matches and durable conflicts between DS-01 and DS-02; research refuses conflicted versions (ADR-033 §1). | None. |
| D-8 | MEDIUM | FIXED | `record-gap` records an evidenced, reviewed provider gap; nothing is filled and the day never qualifies (ADR-033 §2). | Each gap needs an owner review label when it happens. |
| D-10 | LOW | FIXED | Qualification and reports read only the days they judge; ranges are bounded to 31 days (ADR-033 §3). | None. |
| D-11 | LOW | FIXED | Cooldowns are per host; `release-cooldown` plus one passed probe clears one (ADR-033 §4). | None. |
| RS-8 | MEDIUM | FIXED | Holdout opening only through a locked database function; every read logged; resumable without reopening (ADR-033 §5). | Applies to future studies; Phase 3 holdouts stay consumed. |
| RS-9 | MEDIUM | FIXED | Code, lock and input manifest hashes verified at registration and every read; trials carry consumed-bar digests (ADR-033 §6). | None. |
| RS-10 | MEDIUM | FIXED | Folds derived from the training span only, never overlapping validation, marked informational; [preregistration template](../phase3/FUTURE_STUDY_PREREGISTRATION_TEMPLATE.md). | Phase 3 outcomes untouched. |
| P-2 | HIGH | EXTERNAL_PRECONDITION | Campaign v2: flat-boundary day roll, bound standing resume of the writer K1, minute-bar policy, observed specifications (ADR-032 OBV2-01 to 04). | Evidence needs owner START after re-pin, clock, scheduler log and review. |
| P-3 | HIGH | FIXED | The kernel authorizes only against store-verified truth marks, pinned and observed specification hashes and a bounded `now` (OBV2-07). | None. |
| P-4 | MEDIUM | EXTERNAL_PRECONDITION | Per-run gate: Windows Time sync within 3600 s at leap 0, provider bound at most 2000 ms, windows checked in provider time (OBV2-05). | Host clock still unsynchronised; see [clock trust](../runbooks/CLOCK_TRUST.md). |
| P-7 | MEDIUM | EXTERNAL_PRECONDITION | A night or Phase 2 day counts only with a Task Scheduler parent and a time-trigger event in the operational log; a user trigger never counts (OBV2-06). | Owner must enable the scheduler log and do one dry run that confirms the event shapes. |
| P-8 | MEDIUM | FIXED | Undispatched reservations are released at expiry by a journaled event (OBV2-08). | None. |
| P-9 | MEDIUM | FIXED | Invalid truth is quarantined with a journaled correction fact and K1 (OBV2-09). | None. |
| P-10 | MEDIUM | FIXED | The flat-boundary roll has a production caller in the campaign runner; refusal leaves K1 and the night cannot qualify (OBV2-02). | None. |
| P-11 | MEDIUM | FIXED | Writer fencing by epoch on every write path (OBV2-10). | None. |
| P-12 | MEDIUM | FIXED | Migration `0007_paper_state_guards`: transition guards on account state; the truth cursor advances only to an existing truth event (OBV2-10). | None. |
| P-13 | MEDIUM | FIXED | Independent journal replay compared field by field with the stored account; the receipt carries the mismatch count, recomputed on verification (OBV2-11). | None. |
| P-14 | LOW | FIXED | Reduce-only dust close, withdrawal cannot loosen percentage caps, database uniqueness matches the kernel, recorded spread gate (OBV2-11). | Bar-close snapshots have zero spread, stated in the receipt. |
| P-15 | LOW | ACCEPTED_RESIDUAL | None. | One Windows user holds every role secret. Accepted for PAPER (no money); revisit before any broker credential (ADR-032). |
| G-5 | LOW | FIXED | Frame MACs bind direction, channel, session and per-direction sequence; 30 s child idle timeout; Job Object containment. No non-test launcher. | None. |
| OI-4 | MEDIUM | FIXED | START is a committed acceptance entry read from the proven commit; data is genuine only through verified lineage (ADR-034 §1 to 4). | None. |
| OI-9 | LOW | EXTERNAL_PRECONDITION | Append-only gap records for every slot without a manifest; read-only clock diagnostic `tools/oi_clock_status.py` (ADR-034 §5, 6). | The frozen sync-age gate needs the owner's clock fix before START. |
| DB-1 | MEDIUM | FIXED | Tests run only on a disposable cluster (`tools/disposable_pg.py`) with a random port and a verified marker; fixed operational ports refused. | None. |
| DB-2 | MEDIUM | FIXED | Test database names validated; each ledger test gets its own `auvexo_test_<hex>` database, dropped afterwards. | None. |
| DB-5 | LOW | FIXED | Role passwords are sent as SCRAM-SHA-256 verifiers, never as plaintext literals. | None. |
| CI-4 | LOW | FIXED | `tools` under strict mypy on Windows and Linux; action pins refreshed to current majors by SHA. | Accepted residual: `tests` not type-checked (665 strict errors, nearly all fixture annotations). One `benchmark_paper` override (file is hash-frozen). Review 2027-02-14. |
| SC-3 | LOW | FIXED | The broker SDK and NumPy moved from main dependencies to an optional `provider` group; lock regenerated under the pinned uv. | None. |

Count: 26 FIXED, 1 ACCEPTED_RESIDUAL (P-15), 5 EXTERNAL_PRECONDITION (R12-5, P-2, P-4,
P-7, OI-9). Nothing is left RECORDED.

## Further changes in this run

- **Rights renewal.** The owner renewed DS-01 and DS-02 for personal, non-commercial,
  non-production research until 2027-02-16
  ([record](BINANCE_DS01_DS02_RIGHTS_RENEWAL_2026-11-14.md)). Review history is kept: the
  earlier records are byte-identical and their hashes are pinned in tests. Rights lookups
  take the instant they apply to. A recorded review continues for research only while a
  later review with identical scope is in force.
- **Contract hashes.** Nested contracts now contribute their own canonical bytes, so a
  field added later and omitted at its legacy default cannot change the hash of an
  enclosing v1 record. No contract overrode its canonical form before this run, so every
  existing recorded hash is unchanged; a test compares against the old encoding.
- **Dependency lock maturity** reviewed ([record](DEPENDENCY_LOCK_MATURITY_REVIEW_2026-11-13.md)).
- **PostgreSQL autostart candidate**: tool, tests and
  [runbook](../runbooks/POSTGRES_AUTOSTART.md). Not installed.
- **Restart candidate** for the Operational checkout
  ([record](OPERATIONAL_CAMPAIGN_RESTART_CANDIDATE_2026-11-13.md)).

## Verification

Recorded in [the review record](OD23_INDEPENDENT_REVIEW_2026-11-15.md), with the exact
commit, CI runs and test counts.

## Known limits

- The synthetic observation recovery drill (`tools/verify_observation_recovery.py`)
  uses the previous day's window. Until 2026-11-16 00:00 UTC that window precedes the
  rights renewal, so the drill refuses with OBSERVATION_SOURCE_BINDING_DENIED, which is the
  correct rule. It is not part of CI. It is rerun after that time and the result recorded.
- The scheduler event shapes (107, 110, 129 and the instance ActivityID) come from the
  documented formats. The log is disabled on this host. A missing or unexpected field
  makes the night UNVERIFIABLE, never a pass. The owner dry run confirms them.
- The v2 database PASS guard can only be exercised inside the real 17:00:00 to 17:00:30
  UTC close window; tests cover everything before it.
- The two-symbol runner test runs in real time against the database clock. Starved of
  CPU and disk by a concurrent full unit suite, it once ended at K1 (cause not captured)
  and once hit the 2 s statement timeout on a database size check. Both fail closed: the
  night gets exactly one INCOMPLETE receipt. On a quiet host it passes. The evening runs
  happen inside the protected interval, when no heavy local work is allowed.
