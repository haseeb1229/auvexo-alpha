# Checkpoint B observation implementation map

The [frozen requirements](OBSERVATION_ACCEPTANCE.md), [ADR-023](../adr/023-paper-observation-qualification.md)
and [future runbook](OBSERVATION_RUNBOOK.md) govern this implementation. No persistent
task is registered and no campaign is activated. Genuine observation_days = 0.
Full Phase 4, Phase 2 B/C and PUBLIC governance remain OPEN.

| Component | Implemented boundary |
| --- | --- |
| [Typed contracts](../../src/auvexo_alpha/domain/observation.py) | Fixed DS-02 BTC/ETH SPOT, USDT virtual account, original causal times, public server-time proof, configuration/source/rights/spec pins, resource evidence and standalone immutable receipts. |
| [Qualification/planning](../../src/auvexo_alpha/application/observation_qualification.py) | Price-direction-independent ten-minute long/flat cadence; <=0.05% equity sizing; unchanged canonical numeric caps; paired coverage including window edges; every proposal/decision/fill binding; immutable receipt sequence and 14-date/14-day-span checks. |
| [Current feed](../../src/auvexo_alpha/infrastructure/observation_feed.py) | Reuses PublicHTTP, accepted parser and DataStore; dedicated observation checkpoint; one current minute, never backlog. Retains /time response bytes/hash and request interval to prove provider finality and conservatively bound clock error. No zero-drift assumption or bar freshness retiming. |
| [Runner](../../src/auvexo_alpha/application/observation_runner.py) | PREPARED refuses scheduled operation; schema/direct LOGIN, writer fence/reconcile, rights and resource checks before proposals. No automatic owner resume. Truth/source gap or resource failure preserves capacity and produces incomplete evidence. |
| [Ports](../../src/auvexo_alpha/application/observation_ports.py) | Separate typed feed/persistence/PAPER commands/truth/simulator contracts; immutable run/snapshot/journal results. Application signatures expose no engine, connection, filesystem or provider types. |
| [PAPER adapters](../../src/auvexo_alpha/infrastructure/observation_paper.py) | Thin delegation to accepted PaperStore/PaperTruth; no duplicated authorization, risk, reconciliation, reservation or journal rules. |
| [Simulator adapter](../../src/auvexo_alpha/infrastructure/observation_simulator.py) | Approved claimed order on source N; fill only from independently received strictly later bar/provider end/availability, original limit/quantity/90-second expiry. Five-basis-point adverse slippage, zero synthetic bid/ask spread; accepted policy fee/gap assumptions remain unchanged. All truth explicitly SIMULATED. Restart never blindly resends. [Pure calculations](../../src/auvexo_alpha/application/observation_simulator.py) have no storage or provider dependency. |
| [Replay](../../src/auvexo_alpha/application/observation_replay.py) | Exact risk decisions and authorization bindings from retained full inputs; independent raw parser/Parquet replay and journal-prefix/financial-state verification at persistence boundary. Later history cannot rewrite an earlier receipt. |
| [Persistent store](../../src/auvexo_alpha/infrastructure/observation_store.py) | Append-only source/proposal/simulation/receipt evidence over accepted PAPER journals; source archive and manifest-ledger rehash; all decisions/fills accounted; pending truth blocks closure; server-bound run/date/origin; counter replays immutable receipts instead of trusting imported flags. |
| [Observation schema](../../migrations/observation/versions/obs0001_qualification.py) | Separate obs0001_qualification version table on base0005 only. Date/window/activation guards, immutable histories and source/runtime privilege separation. Merged 0001-0005 and default head unchanged. Restored original database origin is retained; restored database cannot count original dates. |
| [Provisioning](../../tools/paper_observation_local.py) | Persistent auvexo_paperobs_<20hex>, scoped pw/po/pt direct LOGINs, exact per-checkout attestation; no admin service/fallback. Idempotent verification. Test cleanup tracks only resources actually created by that context. Unowned namespace collisions refuse. |
| [Local entrypoint](../../tools/run_paper_observation.py) | Configuration/schema/rights inspection, PREPARE, optional NON_COUNTING preflight and future --scheduled path. Exact reviewed committed SHA/executable-clean checkout required for scheduled operation. No START issuer or task registration. Host sampling uses existing ops-only psutil; no package dependency added. No optional research worker is launched. |
| [Task definition](../../tools/paper_observation_task.py) | Generates XML only: AuvexoAlpha-Paper-Observation, 16:00 UTC, InteractiveToken/LeastPrivilege, no password/highest/wake/catch-up/on-demand, IgnoreNew. Hard runtime 1h15s plus maximum15s start lateness stops by17:00:30 UTC. No scheduler mutation code. |
| [Recovery](../../tools/verify_observation_recovery.py) | Isolated synthetic restore of exact PAPER/observation rows and triggers, retained synthetic DS-02 raw/Parquet archive and receipt replay. Original origin preserved; no activation/date credit. Same-disk engineering proof only. |

The public server-time proof is unsigned HTTPS evidence from the allowlisted host,
not a cryptographic exchange attestation. Runtime cannot write independent truth/feed
tables. Owner/admin provisioning, source archive integrity and the reviewed acquisition
process remain the trust boundary. No broker or execution entitlement follows.
PublicHTTP's existing rate spacing and conservative request-interval clock bound can
produce CLOCK_OFFSET or MARKET_STALE denials. These are retained safety behavior,
not reasons to relax policy, fabricate fills or require profitability.

The [dependency resume brief](../reference/PHASE_4_CHECKPOINT_B_DEPENDENCY_RESUME_BRIEF.txt)
authorizes correcting the initial unpublished dependency-direction regression. The
application runner imports domain/application ports and stdlib only. Pinned-release SQL
and typed snapshot conversion live in observation storage; current source/rights and
expected provider-outage translation live in the feed adapter. Concrete PAPER adapters
and simulator are injected only by the outer CLI. Unknown/configuration, identity,
corruption and programmer failures propagate. The inherited R019 test remains unchanged.

Future operations use a local ignored envelope with exactly `database` and `campaign`
fields; campaign is the strict ObservationConfig canonical JSON. Pin the independently
reviewed source SHA, current DS-02 rights/source records and both versioned USDT specs.
Provision/prepare do not issue START. The future independently reviewed owner activation
must bind SHA/config/task/authority hashes and a future first eligible date. No activation
issuer is exposed by this change. An admin who deliberately bypasses schema guards or
rewrites local archives is outside the runtime trust boundary; such changes invalidate
review/restore/source evidence and cannot silently become genuine calendar qualification.

Operational commands below are references for a later explicitly authorized setup;
they were not used to create a persistent campaign in this delivery:

```text
python -m tools.paper_observation_local provision <dedicated-observation-database>
python -m tools.run_paper_observation --config <ignored-local-envelope> --prepare
python -m tools.run_paper_observation --config <ignored-local-envelope>
python -m tools.paper_observation_task --help
```

The task helper accepts paths/owner/date and writes a definition; it never calls
Register-ScheduledTask, schtasks /Create or task start. Separate independent review
and explicit owner START are required before registration or real scheduled runs.
No actual-feed preflight or observation was run in this implementation. Tests and
recovery use explicitly synthetic NON_COUNTING evidence; no fixture is real-source
qualification. The original public-data daily task remains unchanged.

## Dependency-resume verification

The preserved unpublished draft failed the inherited R019 import-direction test.
Its recovery inventory and failed receipt remain owner-local and unchanged. The
resume corrects dependency direction through ports and outer adapters; it does not
amend ADR-023 or either frozen observation requirements document.

| Verification | Dependency-resume result |
| --- | --- |
| Exact inherited R019 import-direction test | Passed unchanged, before subsequent verification. |
| Focused observation cases | 113 passed, including 14 added fake-port orchestration and narrow error-translation cases. |
| Observation PostgreSQL cases | 70 passed; direct identities, immutable histories, activation/source forgery denials and provisioning idempotence. |
| Synthetic PostgreSQL pipeline | One passed; retained raw/Parquet, approved proposal, independently later simulated fill, immutable receipt and replay. |
| Inherited PAPER correctness | 180 passed, including lifecycle, monotonic reconciliation and performance regressions. |
| Full direct-LOGIN security | 111 passed; isolated resources cleaned, DEV unchanged. |
| Full inherited suite | 1,457 passed, no skips, in 416.64 seconds. |
| Static/documentation | Ruff format/check passed (120 files); strict mypy passed (60 source files); documentation/links and byte-identical AGENTS/CLAUDE passed. |
| Dependencies/privacy | Hash-required locked audit: 69 dependencies, zero reported vulnerabilities; redacted source/all-history Gitleaks, high-signal scan and diff check passed. |
| Foundation recovery | Three tables matched; migration idempotence, destructive downgrade refusal, restored trigger and schema-drift checks passed. |
| PAPER recovery | 15 tables and 11 triggers matched; K4, UNKNOWN capacity and virtual financial totals preserved; reconciled without retry. |
| Data/research recovery | 11 tables, 176 manifests, 118 trials and 96 artifacts verified; exact retained source-to-Parquet replay passed. |
| Observation recovery | Exact rows/triggers plus one synthetic raw/Parquet archive and immutable receipt replay passed; original origin retained, activation count and qualified dates zero. |

The concrete simulator class is AST-identical to the preserved draft except for
its structural submission-port annotation. The pure calculation AST is unchanged.
Application fake-port tests perform no database or provider calls. Only expected
provider availability errors translate to the neutral outage exception; configuration,
identity, hash/corruption and programmer failures propagate. No inherited boundary
test, accepted PAPER business rule, merged migration or dependency lock was changed.

Final clone and hosted-CI receipts must bind the exact delivered
commit in the consolidated owner-local handoff and open PR review request. These
engineering receipts do not award a genuine observation date or independent acceptance.
All recovery proofs use the same disk; encrypted off-device disaster recovery remains open.
