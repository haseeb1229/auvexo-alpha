# PR #10 commissioning-readiness correction

> Dated record. Status lines below describe the day this was written; the current
> state is in [STATUS](../STATUS.md).

Status: engineering changes for independent exact-SHA review; no acceptance, merge,
commissioning or collection authority. The founder's 2026-10-29 engineering resume
separates deterministic engineering verification from the unresolved native clock gate.
`CLOCK_EXTERNAL_BLOCKED` permits fixed/synthetic-time tests and disposable engineering
resources. It still denies real commissioning, owner START acceptance, task activation,
collection and calendar credit. No clock threshold or old receipt is changed.

## Corrected boundaries

The inherited environment migration path remains available for existing DEV/TEST/PAPER
tools. OI provisioning supplies a live SQLAlchemy Connection through Alembic
`Config.attributes`, with actual connection/driver/identity validation. It does not read
`AUVEXO_MIGRATION_DSN` on that path. Offline migrations remain refused. No new schema
migration is introduced and merged migration bytes remain unchanged.
An otherwise untransactioned supplied connection gets an owned transaction that commits
only on success. An existing caller transaction retains commit/rollback ownership;
connection validation must not accidentally create an uncommitted external transaction.

The scheduled collector imports only its existing writer credential loader. Separate
[owner APIs](../../src/auvexo_alpha/infrastructure/oi_owner_secrets.py) expose explicitly
named admin/app operations. The fixed CurrentUser DPAPI slots are:

| Identity | Exact purpose | File under KnownFolder LocalAppData/AuvexoAlpha/phase6 |
| --- | --- | --- |
| Admin | `auvexo-alpha:phase6:ds04-a1:oi-db-admin-password:v1` | `oi-db-admin-password.v1.dpapi` |
| App | `auvexo-alpha:phase6:ds04-a1:oi-db-app-password:v1` | `oi-db-app-password.v1.dpapi` |
| Writer | `auvexo-alpha:phase6:ds04-a1:oi-db-password:v1` | `oi-db-password.v1.dpapi` |

Writer-v1 ciphertext/envelope/purpose/location compatibility is retained. Every slot
uses UI-forbidden protection, current-owner/SYSTEM ACLs, no-follow/reparse/final-path/
hardlink checks, atomic rotation and explicit deletion. No arbitrary secret name,
purpose, production path, plaintext fallback/export, automatic recovery or general
credential-vault API is provided. Native tests use disposable UUID leaves and synthetic
secrets only; those leaves cannot select production locations.

The future owner-only provisioner targets only the third runtime and PostgreSQL 17.11
at `127.0.0.1:55433/auvexo_dev_oiresearch`. It has no production target override or broad
reset. Bootstrap uses distinct in-memory passwords, `initdb --pwprompt` with supervised
stdin, SCRAM and the supplied-Connection migration path. Passwords are never arguments,
environment variables or plaintext files. Partial/ambiguous ownership requires explicit
recovery; no task or financial authority follows provisioning. Disposable native tests
must prove actual prompt behavior, migration, least-privilege grants, restart, redaction
and cleanup; design inference alone is insufficient evidence.

Native Windows restricted-token child console behavior requires the initdb child-only,
nonsecret `OSTYPE=msys` selection of PostgreSQL's built-in stdin/stderr prompt path;
[PostgreSQL 17.11 source](https://raw.githubusercontent.com/postgres/postgres/REL_17_11/src/common/sprompt.c)
defines that path. The password still travels only through supervised stdin. Lifecycle
commands have no credential input and avoid inherited output pipes retained by the server.
Native success and failure/cleanup evidence is required; a zero exit alone is insufficient.

`psutil==7.2.2` is declared as a runtime dependency because resource measurement is
required. Missing/failed measurements still yield safely. Other locked package versions
and hashes remain unchanged, including `filelock==4.2.1`.

Both configuration and proof use the same bounded exact-preserving Windows clock-source
type: nonblank printable text, at most 128 characters, never shell interpolation.
Native parser checks, local/free-running/loopback refusal, source equality, leap/stratum,
sync age, error bound and freshness remain unchanged. Engineering tests inject fixed
trusted evidence; native host status is reported separately.

The production configuration includes literal database name `auvexo_dev_oiresearch` and
port `55433`; host stays fixed to `127.0.0.1`. These fields enter the configuration hash,
which the externally accepted START binds. The collector and task renderer expose no
separately mutable database/port argument. Old START hashes cannot silently authorize the
new contract. OIStore retains its dedicated-database and least-privilege attestation,
including foreign generic-row refusal without deletion or repair.
The shared read-only dedication proof covers manifest/checkpoint/event/review namespaces
and refuses any instrument-spec row, since OI snapshots produce no instrument specs.
Store initialization/publication and owner restart/verification reuse that proof.
Owner verification/start default to no continuation authority and refuse continuation
rows. The programmatic APIs may receive the exact externally checked typed review
authority; the shared verifier reconstructs and validates it. The CLI issues no review
acceptance. Stop is containment: it attests the exact owned server identity and files,
without requiring source qualification or app/writer decryption. It repairs no rows.

## Verification and release gates

Focused tests cover each boundary and adversarial failure. Full verification includes
the inherited PostgreSQL suite in a private container network namespace (no host port
or operational database access), native Windows DPAPI and disposable PostgreSQL tests,
Ruff, strict mypy, docs/requirements/links, secret scans, Gitleaks source/history,
hash-required dependency audit, inherited frontend checks and an exact committed-source
fresh Windows clone. Per-run logs, source inventories and final counts are ignored local
evidence and the consolidated handoff; historical results are not new-SHA verification.
Protected operational windows and the pinned operational checkout remain untouched.
Hosted CI is a factual separate result: zero executable steps never mean PASS.

The five accepted proposal documents, OI-FWD-v1, OI-16, source scope/rights due 2026-11-27,
consumed Phase3 holdouts and `VALUE_ABLATION_PREREGISTRATION_BLOCKED_MECHANISM` remain
unchanged. No real OI endpoint/data, persistent runtime/database/credentials, task or
START is created. `PHASE6_FORWARD_CLOCK=ZERO`; value and Phase6 closure remain OPEN.

## Operational evidence reconciliation and future schedule

The read-only 2026-10-29 reconciliation found both registered tasks Ready. Phase2 retains
boundary `2026-10-18T22:57:00+05:00`; its wrapper schedules collection at 23:00–23:12 PK.
Phase4 retains boundary `2026-10-21T21:00:00+05:00` and original campaign
`observation.prepared.20261020.a80174069ece`. The current campaign envelope's hash matches
the original verified activation record. Latest scheduler result codes were 1 (Phase2)
and 2 (Phase4); those codes do not establish a database failure cause or qualification.
Host-reported run timestamps remain explicitly untrusted.

Available Phase2 scheduled summaries report a missed start on October18 and failures on
October21/26/27. Some other run logs lack summaries. The older qualification export covers
only October18–24 with zero verified events; the Phase4 activation snapshot had zero runs
on October20. Neither historical range establishes complete current qualified-date sets,
counts, streak, span, replay or mismatches. Those current fields remain UNKNOWN. Task
Scheduler's Operational history channel is disabled; it was not enabled. This audit
does not connect to operational 55432, repair evidence, backfill or create credit.

Preserve current schedules: zero reset cost is not established. Only after a complete
independently accepted audit proves zero credit and clean repreregistration could a
future proposal use Phase2 warmup22:00/collection22:03–22:15 PK, Phase4 at/after22:20 once
Phase2 safely finishes, and maintenance after midnight. No old-date transfer is allowed.
OI retains its frozen hourly design and protected-hour exclusions.

## Fastest safe parallel path

- Lane A: preserve Phase2 seven genuine consecutive dates and Phase4 >=14 genuine PAPER
  dates/span/replay/zero unexplained mismatch gates; present credit remains UNKNOWN.
- Lane B: PR10 exact-SHA review -> separately authorized normal merge -> trusted native
  clock and real commissioning/recovery/rights proof -> accepted owner START -> OI's
  fixed 90-day background study. No unrelated engineering waits for OI Day90.
- Lane C: separately scoped DS-03 read-only MT5 DEMO source/spec/history/security
  onboarding can proceed when its accepted dependencies and owner authority permit.
- Lane D: full Phase4 closure is a hard predecessor for actual Phase5 commissioning,
  together with accepted DEMO source/account/terms/security and explicit authority;
  then >=30 calendar days/>=20 sessions/>=100 lifecycle observations remain mandatory.
- Lane E: permitted Phase7/operator/security/recovery/release engineering may overlap
  accepted observation clocks under ADR-013/024, without financial authority.
- Lane F: Phase8 additionally needs all applicable prior gates, an eligible validated
  champion, OD-04/05/06/07, legal/data-use/risk/release/recovery decisions and activation.
  Four INCONCLUSIVE Phase3 outcomes supply no champion; no edge means no live launch.
- Lane G: Phase9 follows Phase8 and >=90 genuine live days, adequate preregistered
  evidence and explicit incremental approvals. Binance live derivatives stay blocked.

ENGINEERING_SYSTEM_READY, OPERATIONAL_QUALIFICATION_IN_PROGRESS and LIVE_CERTIFIED are
distinct states. This correction alone establishes none of them. Future DS-03 owner
inputs are an accessible Exness Personal Area, owner-created MT5 DEMO account/login,
exact server, trading password, account type/currency/leverage, dedicated local terminal/
profile and secure local onboarding authority. Credentials belong only in future accepted
local encrypted storage, never chat, Git, logs, CLI or plaintext configuration. No REAL
account, funding or broker connection is requested in PR10.

## Public CI platform correction — 2026-10-31

The owner-authorized temporary public CI exception permitted one unchanged-head rerun
of implementation `6b93b507865df54bcc519b61576781daa0c5cbd5`. Run
[41062301152, attempt 2](https://github.com/haseeb1229/auvexo-alpha/actions/runs/41062301152/attempts/2),
job 124546323790, executed real steps and failed strict Linux mypy with eight errors
for Windows-only ctypes/subprocess attributes. Tests and later checks did not run.
The former zero-step infrastructure failure is retained separately; this is an actual
verification defect, not a hosted test PASS. Conditional acceptance of the old exact
implementation cannot cover this correction; fresh independent exact-SHA review is required.

Explicit `sys.platform` guards now delimit native Windows APIs. The loader attributes
use their portable `ctypes.CDLL` base type while actual Windows construction retains
`WinDLL`, its calling convention and last-error handling. Windows child processes retain
`CREATE_NO_WINDOW`; unsupported native secret/clock operations refuse before API access.
No typing suppression, dynamic attribute fallback, workflow/test weakening, dependency
change or security/clock threshold change is introduced. Strict mypy is checked for both
Linux and Windows, together with native credential/provisioner and full regression evidence.

Temporary public scope permits only sanitized engineering and synthetic fixtures; the
owner separately authorized retaining already-public historical machine/user metadata,
without publishing new identifiers. No new acceptance or temporary-public ADR is
materialized before the release gates pass. PR #10 remains open/unmerged for review;
runtime preparation and DS-03 implementation still require its verified normal merge.
Actual broker credential/session onboarding requires a return to PRIVATE and accepted
source/security gates. Auvexo must never ingest a Personal Area or trading password;
future DS-03 uses an owner-created DEMO account and separately supported read-only access.
Real OI commissioning/START remains clock-gated and `PHASE6_FORWARD_CLOCK=ZERO`.
