# Operations and recovery

Status: FROZEN safe-restart method; RPO/RTO PROVISIONAL and untested until later phases.

Phase 1 has real DEV/TEST migration, rollback-refusal and isolated backup/restore proof;
see [commands and recovery](phase1/SETUP.md) and [evidence](phase1/VERIFICATION.md).
This does not qualify broker reconciliation, live restart or off-device encrypted recovery.

Deploy stages: local-only loopback -> private identity-aware access -> qualified remote
demo/shadow -> certified live. Each is a separate release gate, never a configuration
shortcut. The laptop is suitable for research and supervised demo; sleeping, power loss
and internet loss prevent an unconditional always-on guarantee. No public signup, database
port, terminal port or obscure-subdomain security. Student/free services are optional.

Startup: load signed/configured mode without execution credentials in non-executing modes;
validate schema/migrations, clock, disk, audit durability and policy; obtain one gateway
writer epoch; attest account/server/type; reconcile open orders/positions/recent history;
verify broker-side protection and permits; only then set readiness. Restart defaults to
pause-new. Owner-reviewed recovery clears pause; process restart alone cannot clear losses,
unknown orders, suspension or live permit revocation.

| Incident | Immediate response | Recovery evidence |
| --- | --- | --- |
| Feed gap/stale/clock skew | K1, quarantine dependent source, bound reconnect/backfill | Contiguous sequence or explicit gap, fresh snapshot and corrected clock; replay availability checks |
| Broker disconnect/unknown send | Pause account entries, retain worst-case reservation; no send retry | Broker orders/deals/positions matched to journal and zero unresolved unknowns |
| Position/order mismatch/manual broker trade | K1/K2 as applicable, owner alert; retain broker facts | External action recorded, recalculated exposure, reconciled protection and owner resume |
| Partial fill/failed stop | Keep residual reservation; verify protection; controlled cancel/close if authorized | Filled/residual quantities and fees reconcile, protection or flat state proven |
| Process/terminal/laptop restart | No auto-arm; fence old writer and reattest | Single writer proof, complete history window and release/permit recheck |
| DB unavailable/disk full | Stop new dispatch; pause research and optional writes, preserve journal reserve | Durable journal restored and broker reconciled; no inferred missed fills |
| LLM/provider outage | Disable dependent proposals; deterministic qualified paths stay eligible | Circuit probe passes, budgets reset only per policy; no replay of expired opportunities |
| Compromised credential/auth/audit | K4, revoke access/permits, isolate and preserve evidence | Rotation, forensic scope, clean restore, owner recovery and new release |
| Loss/drawdown/edge suspension | K1/K2 and approved protective handling | Incident/edge review; no daily reset workaround; explicit new authorization |

If automation cannot safely close a known exposure, notify owner to inspect the broker
terminal; do not claim safe flattening while disconnected. Emergency actions still use
typed authorization and fresh relevant truth. Acknowledged cancel/close is checked against
broker outcome; manual intervention is appended as external evidence.

Backup policy target: encrypted daily DB snapshot plus WAL/incremental capture as supported,
immutable dataset manifests and selected artifact copies, and protected configuration/key
recovery instructions. Research RPO <=24 h/RTO <=1 working day; operational journal recovery
target RPO <=5 min/RTO <=60 min in demo. These recovery objectives do not authorize 5 min
of unaccounted trades: broker replay is mandatory before any resume, and unresolved gaps
block it. Live RPO/RTO and owner response must be independently qualified in Phase 8.

Before demo, restore to isolated non-executing instance and compare hashes/ledger totals;
inject lost responses, stale snapshots, duplicate events, process crashes and cancel/fill
races. Before live, prove off-device encrypted restore and recover keys independently.
A same-disk backup does not survive theft/disk loss. No backup medium is purchased now.

Release: immutable build/config/strategy/data manifest, checks and owner approval. Database
changes need backup and expand/contract migrations. Rollback disables dispatch first, preserves
the current execution journal, restores compatible code/config and reconciles current broker
state. Never restore an old DB and assume old positions are current. Irreversible migrations
require tested forward recovery, not a fictional down migration.

Incident record: ID, start/detection/containment/resolution times, affected scope, last healthy
snapshot, unknown exposures, actions/actors, evidence hashes, root cause, residual risk and
preventive tests. Daily review checks coverage, costs and reconciliation; weekly review checks
edge/capacity/security updates. An owner unavailable during unqualified incidents keeps
new exposure disabled. Monitoring doesn't replace a realistic owner-response commitment.

## Phase 2 data operations

Use the [data setup and recovery runbook](phase2/SETUP_AND_RECOVERY.md) for bounded
imports, scheduled observation, persistent cooldowns, orphan reconciliation and
metadata-plus-Parquet restore. Seven scheduled days must be actual calendar evidence;
engineering completion does not close this observation gate. Readiness is diagnostics,
never trading readiness. Source correction creates a new lineage, not a destructive rollback.
