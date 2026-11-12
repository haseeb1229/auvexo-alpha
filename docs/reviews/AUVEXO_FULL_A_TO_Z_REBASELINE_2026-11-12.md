# Auvexo Alpha: full independent rebaseline, 2026-11-12

Auditor: Claude, at the founder's request, replacing the previous operator workflow.
Scope: product intent, architecture, every document, the code, the tests, CI, the three
local checkouts, the scheduled tasks and the operational evidence.
Method: nothing was accepted because an earlier report said PASS. Claims were re-derived
from the repository, the remote, the host and official provider sources. Eight
independent read-only audits covered the subsystems; their findings were then verified
and either fixed or recorded here.

A machine-readable companion is in
[AUVEXO_FULL_A_TO_Z_REBASELINE_2026-11-12.json](AUVEXO_FULL_A_TO_Z_REBASELINE_2026-11-12.json).
Current status after this audit is maintained in [STATUS](../STATUS.md).

## 1. Product intent

Auvexo Alpha is a private, single-owner research and validation desk for BTC, ETH and
gold. It exists to find reproducible trading edges honestly and to preserve capital,
including by returning no trade. It is designed so that trading can later be automated
behind hard gates, first on an Exness MT5 demo account and only much later with tiny live
capital. Profitability is an open empirical question. Agent count, indicator count,
dashboard complexity and backtest profit are not success criteria.

The operator is one person: the founder, on one Windows laptop with 16 GB of memory, with
no budget for mandatory paid cloud, data or model services.

## 2. Architecture hierarchy and authority

```mermaid
flowchart LR
  S[Sources and evidence] --> D[Point-in-time research data]
  D --> H[Hypothesis and candidate]
  H --> B[Backtest, walk-forward, held-out evidence]
  B --> L[Lifecycle and promotion decision]
  L --> R[Deterministic risk engine]
  R --> X[Deterministic execution gateway]
  X --> T[Broker truth]
  T --> C[Reconciliation]
  C --> A[Audit, recovery, operator surfaces]
```

| Question | Answer in the canonical documents and in code |
| --- | --- |
| Who may research | The research worker and optional agents, on read-only snapshots |
| Who may decide promotion | The owner, on recorded evidence; nothing promotes itself |
| Who may risk-check | Only the deterministic risk kernel |
| Who may execute | Only a deterministic gateway holding a bound authorization. None exists for a broker. |
| What is broker truth | Facts reported by the broker; local intent is never a result |
| Who reconciles | The kernel's reconciliation path; unknown outcomes reconcile first and are never resent |
| Where AI may exist | Outside money authority: investigation, proposals, explanations |
| Where AI may never exist | Risk limits, kill states, permits, account binding, order construction and sending |

Modes are RESEARCH, BACKTEST, PAPER, DEMO, SHADOW, LIVE_LIMITED and LIVE. One domain model
serves all of them; each needs its own explicit authority. Today execution is disabled in
every mode by a literal in configuration that no setting can change, and the configured
mode label is refused unless it is RESEARCH, BACKTEST or PAPER.

The audit found no model-to-order path, no browser-to-broker path, no withdrawal or
transfer implementation and no Binance live derivatives capability.

## 3. Source of truth used

In descending order: the authenticated remote and exact commits; the local Git state and
host runtime; the canonical documents and ADRs; frozen designs and acceptance records as
history; reproducible tests and raw receipts; dated handoffs; the founder's brief; and
old prompts only as rationale. Where the brief's entry anchors and reality agreed, that
is stated. Where earlier documents and reality disagreed, reality was recorded and the
earlier text was preserved unchanged in the [history log](../history/README.md).

## 4. Repository and runtime inventory

Remote `haseeb1229/auvexo-alpha`: PUBLIC, default branch `main`, no branch protection,
no rulesets. At the start `main` was `fa0915130c9572c9c2a4a260b20abeaefc2c62f5` and PR #12
was open at `68dd54ad920fcbdf4375d813c6124e03ef8c7233` (tree
`14f1119491df012dc55287b696c76afa483dc93e`, 3 commits, 47 paths), exactly as the brief
stated.

| Checkout | Verified identity |
| --- | --- |
| Operational | `main` at `9b9038b6966843805c99f15e1c37cdba7c026679`, clean, own `.git`, no alternates or extra worktrees |
| Development | own `.git`, no alternates or extra worktrees; all work in this audit happened here |
| OI Runtime | detached at `f47770d7886d12240e24390e23f939cb49535a31`, clean, own `.git` |

The three are separate clones, not worktrees, junctions or shared object stores. One
coupling exists: the Development virtual environment uses the Python interpreter stored
under the Operational checkout's `.local/python`. It is read-only use, but deleting or
changing that directory would break Development.

Source size at the start: about 23,800 lines of application code, 23,400 lines of tests,
3,700 lines of tools, five core migrations and one observation migration, 192 documents,
one CI workflow and a React operator terminal.

## 5. Operational evidence

Read-only inspection of the Operational checkout, Task Scheduler and the host:

| Item | Finding |
| --- | --- |
| Phase 2 genuine qualifying dates | **Zero.** No scheduled run has ever completed. 25 nights from 2026-10-18 to 2026-11-11: 8 failed within seconds, 1 missed its start, 16 left no summary. Earlier documents said UNKNOWN; the wrapper's own receipts prove zero. |
| Phase 4 qualifying PAPER dates | **At most one; exact count UNKNOWN.** The database was running at 21:00 PKT only on 2026-10-22. Receipts exist only in the database, which is down. |
| Cause | The Operational PostgreSQL cluster has not run since 2026-10-23 11:58 PKT. Nothing starts it after a reboot and no failure was surfaced. On most other nights the task did not start because the laptop was off, asleep or on battery. |
| Tasks | Both registered and Ready, triggers 21:00 and 22:57 PKT, interactive owner session required. Task Scheduler's history log is disabled. |
| Clock | Windows Time has never synchronised; measured about 33 seconds slow against two independent providers. One non-elevated resync attempt was refused. |
| Evidence integrity | Nothing was started, repaired, retimed or backfilled. File state in the Operational checkout was identical before and after every inspection. |

Three properties of the pinned release mean neither campaign could have completed even
with a healthy host:

1. The public-data rights review is hard-coded to expire on 2026-11-16. From then both
   tasks refuse, and the PAPER count cannot even be read, because verification checks
   rights at the current time instead of at each receipt's time.
2. The PAPER campaign denies every proposal by construction (kill state forced at start
   with no resume path, day-start never rolled, pinned specification older than a day,
   and a clock-offset cap of 250 ms against a 33-second skew). It would have produced
   fourteen days of denials and no authorization, reservation or fill. "Zero ledger
   mismatches" under those conditions measures nothing.
3. With the clock 33 seconds slow, an observation poll issued later than about 27 seconds
   into a minute fails the provider-finality rule and, in the pinned release, ends the
   night with no receipt.

A read-only tool, `tools/evidence_status.py`, now reproduces the Phase 2 table from the
wrapper summaries without opening a database or writing a file.

## 6. Phase matrix

| Phase | Engineering | Operational | Change from the documents before this audit |
| --- | --- | --- | --- |
| 0 Constitution and architecture | Accepted | Complete | None |
| 1 Engineering foundation | Accepted | Complete | None |
| 2 Trustworthy data | Public spot data and DS-03 read-only adapter accepted | OPEN, **zero** genuine dates | UNKNOWN replaced by zero, from the wrapper's own receipts |
| 3 Backtest and simple alpha | Accepted | Research complete: four INCONCLUSIVE, both holdouts consumed, no candidate | None to the outcomes; ledger enforcement corrected for future studies |
| 4 Lifecycle and hard risk | Accepted | OPEN, at most one date, exact count UNKNOWN; the pinned campaign cannot complete | "Observation active" was wrong |
| 5 Demo and shadow | Offline synthetic foundation accepted | NOT STARTED | None |
| 6 Intelligence | Open-interest engineering accepted; two collector defects fixed here | NOT STARTED, forward clock zero, value gate open | None |
| 7 Owner surfaces | Read-only web terminal accepted and improved | OPEN; no desktop, Android, voice or owner authentication | None |
| 8 Live certification | NOT STARTED | NOT STARTED | None |
| 9 Controlled scaling | NOT STARTED | NOT STARTED | None |

## 7. Findings

Eight independent read-only audits covered research and backtesting, PAPER risk and
observation, gateway, API and terminal, market data, open interest, database, CI and
supply chain, documentation, and external provider facts. Every finding below was
re-checked before it was given a disposition.

| Disposition | Meaning |
| --- | --- |
| FIXED | Corrected and verified in this change |
| RECORDED | A real engineering finding, not fixed here, tracked as required work before the phase it blocks |
| OWNER | Needs an owner, legal, provider or elapsed-time action |
| NO_CHANGE | Accurate statement of scope that is not built |

92 findings: 52 FIXED, 32 RECORDED, 7 OWNER, 1 NO_CHANGE. By severity: 2 critical
(1 fixed, 1 owner), 14 high (8 fixed, 2 recorded, 4 owner), 47 medium (28 fixed,
18 recorded, 1 owner), 27 low (15 fixed, 12 recorded), 2 informational.

| ID | Area | Severity | Finding | Disposition | Note |
| --- | --- | --- | --- | --- | --- |
| OPS-1 | Operations | CRITICAL | Operational PostgreSQL down since 2026-10-23; both evidence campaigns silently dead | OWNER | Restart is an owner action on the pinned checkout; read-only evidence tool added |
| D-1 | Data | CRITICAL | Unclosed candle stored as final when the host clock runs fast; no provider time consulted | FIXED | Provider server time read before each request; bars must be closed in provider time; skew bound 2 s |
| OPS-2 | Operations | HIGH | Laptop off, asleep or on battery at trigger time on most nights | OWNER | Availability window documented in the runbook |
| OPS-3 | Operations | HIGH | Host clock never synchronised, measured about 33 s slow | OWNER | Elevated resync or NTP path required |
| OPS-4 | Operations | HIGH | Public-data rights review hard-coded to expire 2026-11-16; both tasks then refuse | OWNER | Renewal needs owner confirmation of provider terms and a new release |
| R12-1 | DS-03 | HIGH | Provider child could never start: Path.home() unresolvable in its stripped environment | FIXED | Token-derived profile; native real-child tests |
| R12-4 | DS-03 | HIGH | Source rights unresolved and adverse: Exness agreement restricts quote collection and automated access | OWNER | Recorded in ADR-030; legal decision |
| D-2 | Data | HIGH | Qualifying window anchored only to the unsynchronised local clock | FIXED | Same proof refuses collection while the clock disagrees with the provider |
| D-3 | Data | HIGH | Manual runs indistinguishable from scheduled runs in qualification | FIXED | A day needs exactly one completed scheduled wrapper summary from the pre-window (ADR-031) |
| RS-1 | Research | HIGH | Out-of-sample seal was per study: another study's window could read sealed bars | FIXED | Seal enforced per calendar across studies, at registration and at read |
| P-1 | PAPER | HIGH | Observation count unreadable once rights expire; campaign cannot complete as pinned | FIXED | Receipts verified against rights at their recorded time |
| P-2 | PAPER | HIGH | Observation campaign is denial-only by construction; ledger evidence vacuous | RECORDED | Superseding preregistration needed: owner resume, day roll, clock |
| P-3 | PAPER | HIGH | Kernel trusts caller-supplied market, specification and time | RECORDED | Latent; pin specs, require truth marks, bound time before Phase 5 |
| OI-1 | Open interest | HIGH | Daily job abort at 19:00 UTC: store recomputed a different feature reason for non-adjacent slots | FIXED | Store recomputes from its own checkpoint; per-symbol isolation with durable record |
| OI-2 | Open interest | HIGH | One transient transport failure blocked every later run permanently | FIXED | Failed attempts completed; unknown outcome blocks only its slot |
| DOC-1 | Documentation | HIGH | Ten files carried stacked, mutually contradictory 'current status' blocks | FIXED | One STATUS document; verbatim history log; guard in the docs check |
| OPS-5 | Operations | MEDIUM | No failure alerting; Task Scheduler history disabled; failures unseen for three weeks | FIXED | tools/evidence_status.py reports health read-only; wrapper now records refusals and reasons |
| R12-2 | DS-03 | MEDIUM | Source binding omitted four executed package initializers (actual and synthetic) | FIXED | Inventories completed; import-closure oracle test |
| R12-3 | DS-03 | MEDIUM | No static allowlist proof over the actual adapter (M5-08) | FIXED | Three static tests |
| R12-5 | DS-03 | MEDIUM | MT5 server-time basis unattested; adapter labels provider times as UTC | RECORDED | Onboarding precondition in ADR-030 |
| R12-6 | DS-03 | MEDIUM | Account and server digests are unsalted hashes of low-entropy values | RECORDED | Classified as private account data in ADR-030 |
| D-4 | Data | MEDIUM | Catch-up after an outage makes the next windows unqualifiable | FIXED | Warm-up catch-up, never inside the window |
| D-5 | Data | MEDIUM | Correction impact overstated: changed-row comparison used Decimal text | FIXED | Rows compared by numeric value |
| D-6 | Data | MEDIUM | Failures left no durable or specific evidence; local errors quarantined as bad input | FIXED | Stable reason codes; refused starts recorded; only parser failures quarantined |
| D-7 | Data | MEDIUM | No reconciliation between archive and REST bars for the same minute | RECORDED | Needs a design for cross-source comparison |
| D-8 | Data | MEDIUM | A provider-side missing minute wedges the live feed permanently | RECORDED | Needs an owner-reviewed explicit gap checkpoint |
| RS-2 | Research | MEDIUM | Ledger did not enforce the frozen one-config-per-family selection when opening a holdout | FIXED | Holdout opens only the verified frozen selection, one config per family |
| RS-3 | Research | MEDIUM | Verdict ignored manifest parameters and used code defaults | FIXED | Verdict uses the registered manifest parameters |
| RS-4 | Research | MEDIUM | Verdict never recorded in the ledger; stress-multiplier order unvalidated | FIXED | Verdict recorded as a ledger trial; stress multipliers validated |
| RS-5 | Research | MEDIUM | Rejection book incomplete (silent no-fill, shadowed signals, outage-expired entries) | FIXED | Unfillable, shadowed and outage-expired entries recorded; fills unchanged |
| RS-8 | Research | MEDIUM | Holdout consumption not atomic or resumable; post-consumption reads unlogged; gates application-side | RECORDED | Needs database-side enforcement design before any new study |
| RS-9 | Research | MEDIUM | Trial hash binding partly decorative (code, lock and input-bar digests unverified) | RECORDED | Before any new study |
| RS-10 | Research | MEDIUM | Walk-forward folds informational only; one fold duplicates validation | RECORDED | Matches the frozen plan wording; method gap for a future preregistration |
| RS-11 | Research | MEDIUM | Strategy rules, reader, screen branches and metrics values had no tests | FIXED | Hand-computed tests for rules, screen, selection and metric values |
| P-4 | PAPER | MEDIUM | Schedule guards trust the host clock | RECORDED | Clock bound per run in a superseding preregistration |
| P-5 | PAPER | MEDIUM | Provider-finality failure aborted the whole run instead of recording a missed bar | FIXED | Unprovable bar is a missed bar with a durable reason |
| P-6 | PAPER | MEDIUM | Missed and failed nights left no INCOMPLETE receipt | FIXED | One receipt per started night; failures and refused PASS record INCOMPLETE |
| P-7 | PAPER | MEDIUM | Manual scheduled start inside the 15 s window counts as genuine | RECORDED | Bind to a task-issued token or accept in the requirement |
| P-8 | PAPER | MEDIUM | Undispatched reservation never released | RECORDED | Kernel change; before Phase 5 |
| P-9 | PAPER | MEDIUM | Invalid truth makes reconciliation raise forever, unjournaled | RECORDED | Quarantine and correction fact; before Phase 5 |
| P-10 | PAPER | MEDIUM | Day roll needs an exact-midnight clock and has no production caller | RECORDED | Before any campaign with exposure |
| P-11 | PAPER | MEDIUM | Writer fencing covers dispatch only | RECORDED | Before Phase 5 |
| P-12 | PAPER | MEDIUM | Runtime role can rewrite most account state; cursor guard only requires an increase | RECORDED | New migration with transition triggers; before Phase 5 |
| P-13 | PAPER | MEDIUM | No real ledger-mismatch measurement | RECORDED | Before claiming mismatch evidence |
| G-1 | Gateway | MEDIUM | Offline permit compared an attestation with itself; self-issued in shape | FIXED | Compares against an independent pin; AST test keeps the permit unwired |
| G-2 | Gateway | MEDIUM | Identity drift masked and unjournaled above K1; shutdown raised at K2+ | FIXED | Journals at the current level; original error propagates |
| G-3 | Gateway | MEDIUM | Every reconnect forced UNKNOWN on healthy working orders | FIXED | Only unresolved attempts marked UNKNOWN before the query |
| T-1 | Terminal | MEDIUM | Journal kinds mapped wrongly: kills, loss latches and unknown orders shown as other events | FIXED | Closed mapping over every stored kind |
| T-2 | Terminal | MEDIUM | Hard-coded governance claims served as live data ('observation active') | FIXED | Labelled static summary; operational status UNKNOWN |
| T-3 | Terminal | MEDIUM | Mode label accepted LIVE from the environment | FIXED | Later modes refused at startup |
| T-4 | Terminal | MEDIUM | Safety state not continuously visible; retained data kept AVAILABLE labels; failures collapsed | FIXED | Sticky safety bar, stale band, distinct failure states |
| OI-3 | Open interest | MEDIUM | Study evaluation trusted a caller-supplied time | FIXED | Final result needs records through the end of the window |
| OI-4 | Open interest | MEDIUM | Genuineness is a caller-asserted label; START acceptance is a same-party digest | RECORDED | Needs a reviewed evaluation entry point and a pinned or signed acceptance |
| OI-5 | Open interest | MEDIUM | Clock and build gates invoked git and w32tm by bare name; untracked files invisible | FIXED | System-directory w32tm, absolute git outside the checkout, untracked refused, isolated child |
| OI-6 | Open interest | MEDIUM | Build gate hashed the source tree without proving it is the imported package | FIXED | Imported package proven byte-identical to the hashed tree |
| DB-1 | Database | MEDIUM | PostgreSQL tests run as cluster superuser on the fixed port shared with the operational cluster | RECORDED | Local guard added; full test-port isolation needs a design change in identity attestation |
| DB-2 | Database | MEDIUM | Test database name unvalidated; a ledger fixture writes permanent rows | RECORDED | Validate names and give the fixture its own database |
| DB-3 | Database | MEDIUM | No real backup: no schedule, no roles dump, unencrypted, same disk | OWNER | Runbook written; off-device encrypted backup is an owner gate |
| CI-1 | CI | MEDIUM | Merged main never tested; push triggers listed only old branches | FIXED | CI runs on push to main, on pull requests and weekly |
| CI-2 | CI | MEDIUM | No history secret scan in CI on a public repository | FIXED | Checksum-pinned Gitleaks over full history |
| CI-3 | CI | MEDIUM | No Windows job: native security proofs and Windows-only pins never ran in CI | FIXED | windows-2025 job: 2260 native and unit tests, Windows pin audit |
| DOC-2 | Documentation | MEDIUM | No runbooks for verification, checkouts, clock, backup, break-glass, release, rights or local state | FIXED | Ten runbooks |
| DOC-3 | Documentation | MEDIUM | Architecture diagram edges could be read as a client creating candidates or policy | FIXED | Labelled hierarchy plus authority, data and broker diagrams |
| OPS-6 | Operations | LOW | Development environment uses the interpreter stored under the Operational checkout | RECORDED | Read-only coupling; give Development its own interpreter at the next environment rebuild |
| R12-7 | DS-03 | LOW | Single redacted refusal code; no reason codes for onboarding diagnosis | RECORDED | Contract change for the onboarding ADR |
| R12-8 | DS-03 | LOW | Provider runtime must be installed by copy and without byte-compilation; pip compiles and uv hard-links by default | RECORDED | Adapter refuses both by design; CI now installs by copy; note for the onboarding runbook |
| D-9 | Data | LOW | Read-only commands took the collector lease and could fail a scheduled run | FIXED | Read-only commands no longer take the lease |
| D-10 | Data | LOW | Report budget of 10,000 rows will eventually break qualification | RECORDED | Filter by date range in SQL |
| D-11 | Data | LOW | Global three-day provider cooldown cannot be cleared | RECORDED | Documented policy; fatal to a streak |
| RS-6 | Research | LOW | Mean-reversion trigger strict where the frozen plan says at-or-below | FIXED | At-or-below, as the frozen plan states; the one intended behaviour change |
| RS-7 | Research | LOW | Metrics divisions ran under the ambient decimal context | FIXED | Local decimal context pinned |
| P-14 | PAPER | LOW | Dust close blocked by minimums; withdrawals loosen percentage caps; weaker DB uniqueness; no spread gate | RECORDED | Kernel refinements |
| P-15 | PAPER | LOW | Database role separation exists only inside the database; one Windows user holds all passwords | RECORDED | Residual of a single-user host |
| G-4 | Gateway | LOW | Dispatch reported UNKNOWN when nothing was attempted | FIXED | NOT_ATTEMPTED outcome |
| G-5 | Gateway | LOW | Frame MAC has no direction binding; child has no idle timeout or OS containment | RECORDED | Before any non-test launcher exists |
| G-6 | Gateway | LOW | A WITHDRAW verb exists in the action enum (denied everywhere) | FIXED | Test proves no handler exists; member kept so it can be refused |
| T-5 | Terminal | LOW | Snapshot all-or-nothing; constant-only error log; stale version field; missing isolation headers | FIXED | Per-view guard, class-only logging, headers, version field |
| T-6 | Terminal | LOW | Frontend validator tested against one all-unknown fixture only | FIXED | Schema-walking contract tests and a populated fixture |
| OI-7 | Open interest | LOW | Subprocess failures escaped the redaction boundary; inadmissible targets raised | FIXED | Redaction boundary covers subprocess errors; inadmissible targets unscored |
| OI-8 | Open interest | LOW | Test helper accepted the production runtime port | FIXED | Production runtime port refused outside CI |
| OI-9 | Open interest | LOW | No durable gap record for missed slots; clock gate may refuse a synchronised stock host | RECORDED | Before START |
| DB-4 | Database | LOW | Local tool could start a second cluster on the operational port | FIXED | Port-ownership guard and explicit --create |
| DB-5 | Database | LOW | Role passwords sent as SQL literals may reach server logs on failure | RECORDED | Send a SCRAM verifier instead |
| CI-4 | CI | LOW | Type checking covers src and migrations only; action pins target a deprecated Node runtime | RECORDED | Extend typing to tools and tests; refresh action pins deliberately |
| SC-1 | Supply chain | LOW | Inventory and SBOM stale and missing the Windows-only pins | FIXED | Both generated from the lock; test binds them to it |
| SC-2 | Supply chain | LOW | Third-party notices had corrupted fences and understated two licences | FIXED |  |
| SC-3 | Supply chain | LOW | Provider SDK and NumPy are main dependencies, so every Windows install carries the SDK | RECORDED | Move to an optional group with a lock regeneration under the pinned uv |
| SC-4 | Supply chain | LOW | A transitive package imported directly | FIXED | Response imported from FastAPI |
| DOC-4 | Documentation | LOW | ADR index broken into fragments with stale statuses; decisions register overtaken | FIXED |  |
| DOC-5 | Documentation | LOW | Requirement families OB, OI, D3 and M5 and ADRs 023-031 absent from the requirements register | FIXED | Register amendment added |
| T-7 | Terminal | INFO | No desktop, Android or voice client; no passkeys, sessions or step-up; not connected to operational data | NO_CHANGE | Phase 7 scope that is not built; stated in STATUS |
| CI-5 | CI | INFO | No branch protection or rulesets | OWNER | Required before Phase 8 |

What was claimed before and was not true:

- "Phase 2 genuine credit UNKNOWN, not ZERO": the wrapper's receipts prove zero.
- "Observation is ACTIVE": the task is registered; the database it needs has been down
  for three weeks.
- "Transitive project source closure" in the DS-03 binding: four executed files were
  outside it.
- "Production-capable read-only adapter": its provider child could not start.
- "Frozen exact-SHA review" of the open-interest collector: the collector aborted every
  day at 19:00 UTC and could block itself permanently after one timeout.
- "Repository verified PRIVATE" in a status block directly beneath one that said PUBLIC.

Accepted claims that held: no model-to-order path; no withdrawal or transfer capability;
no Binance live derivatives capability; execution impossible to enable; append-only
journals and ledgers with database-enforced refusal of updates; no same-close lookahead,
fill, cost, split or embargo error in the backtester; every preregistered open-interest
statistic exactly as frozen; CI actions pinned to genuine official releases; every
direct dependency a genuine package from its expected publisher.

## 8. What was fixed

DS-03 (PR #12, recorded in [ADR-030](../adr/030-ds03-adapter-independent-review-corrections.md)
and the [review record](PHASE_2_DS03_ACTUAL_ADAPTER_INDEPENDENT_REVIEW.md)): the provider
child now resolves its fixed runtime from the process token, the source binding covers
every executed module, and static tests pin the SDK surface to the allowlist.

Evidence semantics ([ADR-031](../adr/031-evidence-semantics-corrections-and-campaign-restart.md)):
provider-time finality and clock-skew refusal for public data; scheduled-wrapper
provenance for qualifying days; durable reason codes for every failure and refused
start; warm-up catch-up; observation bars that cannot be proven become missed bars
instead of ending the night; one receipt per started night; earned dates readable after
rights expire.

Research ledger: the out-of-sample seal holds across studies; only the verified frozen
selection can open a holdout; the verdict uses the registered parameters and is a ledger
fact; rejected candidates are complete; the mean-reversion boundary follows the frozen
plan; hand-computed tests now cover the strategy rules, screens and metric values.

Open interest: no daily abort, no permanent block, absolute tool paths, isolated child,
imported-package proof, unscored inadmissible targets, final results only with records
through the window's end.

Offline gateway: drift journaled at any kill level, honest reconnect, NOT_ATTEMPTED, an
independent pin for the inert permit, and tests proving the permit stays unwired and no
withdrawal or transfer handler exists.

Operator terminal: true journal reasons, a labelled static summary instead of invented
status, later modes refused, a sticky safety bar, stale-data marking, distinct failure
states, contract tests against the schema. It stays read-only with no control.

Operations and supply chain: a read-only evidence-status tool; a port guard so a
development checkout cannot take the operational database port; a disposable-database
guard for the PostgreSQL tests; CI on pushes to main and weekly, a checksum-pinned
full-history secret scan and a Windows job for the native proofs; an inventory and SBOM
derived from the lock; repaired notices.

Documentation: one [STATUS](../STATUS.md) document; the contradictory status stacks moved
verbatim into a [history log](../history/README.md) pinned by hash; ten
[runbooks](../runbooks/README.md); labelled architecture, authority, data and broker
diagrams; a contiguous ADR index with supersession; an updated decisions register with
eight new gates; the requirement families that were missing from the register.

The rendered terminal was inspected in a headless browser at desktop width and at
360 px: no horizontal scroll, the safety bar stays visible, the token is held in memory
only (no local storage, session storage or cookie), and every status reads UNKNOWN or
not connected where nothing is measured.

## 9. What was intentionally not changed

- **The Operational and OI Runtime checkouts**, their tasks, databases, configuration
  and evidence. Not started, not repaired, not retimed, not backfilled.
- **Frozen documents**: ADRs 001-029, the hash-pinned preregistrations, acceptance and
  runbook files, the review records and the archived briefs. Corrections are new ADRs
  (030, 031) and new records. The dated status stacks were moved verbatim into a history
  log, not rewritten.
- **The four Phase 3 outcomes and both consumed holdouts.** Nothing was re-read, re-run
  or re-labelled. The simulator arithmetic was re-audited without error, so the results
  stand as computed. They carry one evidentiary note: the out-of-sample seal and the
  frozen selection were enforced by the worker's convention rather than by the ledger,
  the verdict was not a ledger fact, and the screen used code defaults. Whether the seal
  was honoured in the historical runs is therefore UNPROVEN, not refuted; it can be
  checked from ledger metadata alone once the database is available.
- **Every preregistered open-interest number and statistic.** They were verified against
  an independent reference and left alone.
- **The stack.** No framework, database, language or library was replaced. No dependency
  was added or upgraded.
- **Repository settings.** Visibility, branch protection, secret scanning, billing and
  runners were not touched.
- **Risk-kernel internals.** Findings in the PAPER kernel and database roles are recorded
  rather than patched, because the PostgreSQL-backed PAPER tests can only run in hosted
  CI from this laptop (they are pinned to the operational port) and kernel changes without
  local database verification would be reckless. They are required work before Phase 5.

## 10. Genuine external and elapsed gates

Only the owner, a provider or the calendar can close these.

1. Merge PR #12 and then the rebaseline pull request, as normal merge commits. The audit
   session is not permitted to merge without a human review.
2. Restart the evidence campaigns: start the operational database and keep it running,
   keep the laptop on AC power, awake and signed in from 20:45 to 23:20 PKT, and decide
   on a re-pin to a corrected release under ADR-031.
3. Synchronise the clock (elevated resync, or a network path for NTP).
4. Confirm provider terms and renew the public-data rights review before 2026-11-16;
   the open-interest review is due 2026-11-27.
5. Decide DS-03 source rights under the Exness client agreement, with qualified advice
   if wanted.
6. Make the repository PRIVATE before any actual account, session or credential work.
   That point has not been reached: source rights come first.
7. Elapsed evidence that cannot be compressed: seven consecutive public-data dates;
   fourteen PAPER dates over at least fourteen days; thirty days, twenty sessions and one
   hundred demo lifecycles for Phase 5; the fixed ninety-day open-interest window; ninety
   live days before any scaling proposal.
8. Before Phase 8: live capital limits, legal and jurisdiction eligibility, off-device
   encrypted backup and release-integrity controls.

## 11. Security residuals

- One Windows user holds every local database password and can therefore act as any
  database role. Role separation is real inside PostgreSQL and absent on the host.
- The operator API authenticates with one static bearer. There are no passkeys, sessions,
  step-up, device revocation or idle expiry on the server.
- Permit signing, service identity and an owner activation flow do not exist. They are
  not needed until an order path exists, and none does.
- DS-03 authority objects are integrity bindings, not cryptographic authorizations; the
  independent acceptance input has no implementation yet.
- Account and server reference digests are reversible by enumeration and must be treated
  as private account data.
- GitHub secret scanning, push protection and branch protection are disabled. CI now
  scans full history on every run.
- No off-device, encrypted backup exists.
- The gateway IPC frame authentication has no direction field and the synthetic gateway
  child has no idle timeout or OS containment. Neither is reachable outside tests.

## 12. Data and research residuals

- Public-data evidence depends on a trusted clock. The collector now refuses to collect
  when the clock disagrees with the provider by more than two seconds, so nothing will be
  collected on this host until the clock is fixed.
- There is no reconciliation between archive and REST bars for the same minute, and a
  provider-side missing minute would wedge the live feed until an explicit reviewed gap
  checkpoint exists.
- Archive-derived results remain personal, non-production research under the Binance
  Vision dataset terms, whatever they show.
- A new study needs: database-side enforcement of the holdout gate, verified code and
  input digests in every trial, a walk-forward design that is actually used, and a new
  preregistration on unconsumed evidence. None of that may touch the consumed holdouts.
- The open-interest study can prove predictability at most. It proves no price alpha,
  trading value, filter value or safety value, and its value gate stays open until an
  honest outcome-blind mechanism from open interest to a candidate exists.

## 13. Release and CI proof

A green mark was not accepted as evidence. Each run below was opened and its executed
steps and test summaries were read.

| Commit | Run | Result |
| --- | --- | --- |
| `68dd54a` (PR #12 as received) | 41692985155 | 24 steps; 2718 passed, 33 skipped. Green, but the provider child could not start (R12-1). |
| `b743fc6` (PR #12 corrected) | 43152174148 | 24 steps all successful; 2723 passed, 35 skipped |
| `e808e81` (PR #12 final) | 43219379860 | 28 steps all successful; 2723 passed, 35 skipped; frontend 31; audits clean |
| `bd313d0` (rebaseline, first CI shape change) | 43220570848 | Linux job successful; new Windows job failed 1 of 2261: uv hard-links installed files and the provider binding refuses hard links by design. Fixed in `94b959c`. |
| `94b959c` | 43221132497 | Linux job 29 steps all successful: full-history secret scan of 63 commits clean, 2745 passed, 35 skipped, typing clean on 98 files, 31 frontend tests, audits clean. Windows job 11 steps all successful: 2260 passed, 1 skipped, 519 PostgreSQL tests deselected, Windows-pin audit clean. |

Local Windows verification of the fix commits, before the documentation commit: the
complete non-integration suite passed with 2738 tests and 2 platform skips; format, lint
and strict typing clean. A fresh clone of the PR #12 head, built in a new environment
from the hash-locked requirements as a normal wheel, passed every check with 2238 tests
and a clean tree.

The hosted runs for the final head of this change are in the pull request; a commit
cannot contain its own CI result.

PostgreSQL-backed tests were written or edited for several fixes and could only run in
hosted CI, because on this laptop the PostgreSQL test port belongs to the operational
cluster. Their results are part of the final hosted run.

## 14. Operational checkout proof

- Head `9b9038b6966843805c99f15e1c37cdba7c026679` on `main`, working tree clean, before
  and after the audit.
- Only read operations were performed there: Git queries with a per-command
  safe-directory option and optional locks disabled, file listings, and reads of wrapper
  summaries, task definitions and PostgreSQL log files.
- The evidence-status tool was run against it with a before-and-after comparison of file
  sizes and modification times for the summaries, the pid file, the Git head and the Git
  index: identical.
- No PostgreSQL cluster was started on any port. No scheduled task was run, changed,
  disabled or retimed. No process belonging to the owner was stopped.
- No heavy local work ran during 20:45-22:15 or 22:45-23:20 PKT.

## 15. Commits and trees

| Item | Value |
| --- | --- |
| `main` at start | `fa0915130c9572c9c2a4a260b20abeaefc2c62f5`, tree `9a5ea762c3d7e5498440c37f5fc9b0cf5b550123` |
| PR #12 as received | `68dd54ad920fcbdf4375d813c6124e03ef8c7233`, tree `14f1119491df012dc55287b696c76afa483dc93e` |
| PR #12 corrected | `b743fc6ee8da3ba39435d9a4a3d4464bca547d5c`, tree `30ac7d319a5b8d7970e64f36452ffe6955f0a60c` |
| PR #12 final | `e808e816f8b7eecb68b6902149e0e87ec3f0ce8f`, tree `787c65ea458f26b87397d0acdd887977b6e296b5` |
| Rebaseline branch | `rebaseline/claude-a-to-z-20261112`, stacked on `e808e81` |
| Operational checkout | `9b9038b6966843805c99f15e1c37cdba7c026679`, unchanged |
| OI Runtime checkout | `f47770d7886d12240e24390e23f939cb49535a31`, unchanged |

Every commit in this audit is authored and committed under the founder's configured
identity with no AI co-author trailer, and nothing was force-pushed or rewritten.

**Neither PR #12 nor this change is merged.** The audit session was not permitted to
merge without a human review; both wait for the owner, in order, as normal merge
commits. After each merge, check that the first parent is the previous `main`, the
second parent is the verified head, and the trees are equal.

## 16. System ready, operationally qualified, live certified

| Level | Meaning | State |
| --- | --- | --- |
| Engineering system ready | Code, architecture, security, recovery and operator surfaces built and independently verified | PARTIAL. The built parts are verified and many defects were repaired. Recorded findings in the PAPER kernel, database roles, research ledger enforcement and operator authentication remain, and Phase 5 execution, Phase 6 agents and most of Phase 7 are not built. |
| Operational qualification in progress | Genuine evidence clocks running | NO. Both campaigns are stalled at zero and at most one date. No clock is running. |
| Live certified | Every live gate passed | NO. There is no validated edge and no eligible champion. No edge means no live launch. |

Production-quality software is not authorization to trade real money, and this system
is not yet either.
