# Data architecture

Status: FROZEN provenance and availability semantics; retention/capacity PROVISIONAL.

PostgreSQL stores instruments, source registry, operational state, intent/reservation/outbox,
orders/deals/positions, policy/releases, strategy registry, event metadata, experiment manifests,
audit and counterfactual indexes. Parquet stores immutable partitioned bars/features and bounded
ticks/events. Do not use a dataframe or a cache as broker truth. Archive writes use temporary
files, checksums, atomic rename and a manifest committed only after file validation.

## Point-in-time contract

Preserve provider time, exchange event time, publication time, first-seen time, received time,
processed time, decision time, order-sent time, acknowledgment time and fill time where applicable.
Unavailable timestamps are null with a reason, never invented. UTC-aware timestamps internally;
preserve original timestamp/timezone and precision. Use monotonic clocks for durations/deadlines,
not for reconstructing market history. Clock skew is measured and enters data-health decisions.

Every observation has source_id, source record ID, schema version, instrument mapping version,
raw content hash, lineage, quality flags and observed/available-at times. Data downloaded today
with an old publication date is not proof it was available historically. Revisions append
vintages: observed value and later revised value remain separately queryable. Do not overwrite
old macro/on-chain values. Backtests use as-of joins where available_at <= simulated decision
time, not merely event_time <= decision_time. Missing vintage data disqualifies claims that
depend on accurate historical release timing; price-only experiments can proceed independently.

DatasetVersion manifests contain immutable file hashes, source/license provenance, time range,
instruments, schema, quality report, collection code and extraction configuration. FeatureSnapshot
references dataset_version, feature definitions, code hash, cutoff, lookback, missingness and
market_state_id. A decision binds these IDs plus policy, model and strategy versions. Replay
must reconstruct why an intent was proposed, rejected or executed without querying current data.

Validate monotonicity, duplicates, gaps, OHLC relationships, volume units, sequence resets,
bid <= ask, session calendars and timestamp units. Quarantine anomalies; do not silently
forward-fill executable quotes or convert absent volume to zero. Corrections create new
dataset versions. Source changes require overlap comparisons; avoid splicing unlike products.

## Event/news model

Store source identity and URL, publication/first-seen/ingestion timestamps, content hash,
semantic_duplicate_id, novelty, trust tier, confirmation_state, entities/assets, category,
severity, confidence, expiry/decay policy and evidence references. Distinguish statement,
commentary, proposal and enacted action. Confirmation is an explicit transition with evidence.
An official source can still publish a correction; confidence is not a trading permission.

Trust order: official government/central bank/regulator; official exchange/company/project;
professional financial source; verified public social identity; reputable secondary reporting;
low-confidence social/rumor. Provenance and independence matter more than duplicate count.
Use source IDs/hashes for exact deduplication, then bounded semantic clustering with human
review for material ambiguities. Compare original publication time to first-seen time to
flag recycled headlines and resurfacing posts. Preserve all versions and cluster membership.
Rumors cannot independently authorize trades. Deterministic blackout rules may tighten risk
on an unconfirmed severe event; reopening requires the policy's explicit evidence rule.

## Retention, quota and sizing

| Tier/category | Default retention | Managed budget | Behavior |
| --- | --- | --- | --- |
| Hot operational DB/WAL | 90 days detailed feed/event indexes; permanent compact decision ledger | 15 GB | Partition/compact; audit/order records never deleted merely for space |
| Warm bars/features Parquet | 5 years bars where licensed; 1 year reproducible selected features | 35 GB | Immutable monthly/source/instrument partitions; manifests |
| Raw ticks/events | 7 days by default, incident samples longer with budget | 10 GB | No unlimited full-depth book; subscription quotas |
| Experiments/artifacts | 90 days exploratory, retained accepted/rejected evidence summaries | 15 GB | Evict regenerable outputs by manifest, preserve promotion evidence |
| Logs/metrics | 14 days verbose, 90 days summaries | 5 GB | Redact, rotate and compress |
| Local encrypted backups | Rotating incremental/snapshot set | 20 GB | Never count same-disk copy as disaster protection |
| Repo/toolchains/temp/compaction | Bounded caches and reserved workspace | 20 GB | Check free space before compaction; delete only disposable data |
| Total target | Hot + warm + local backup + tools | 120 GB | 150 GB hard managed quota |

Sizing assumptions: 3 assets * 525,600 one-minute bars/year * 5 years = 7.884 million
rows; at 100-250 compressed bytes/row approximately 0.8-2.0 GB per source before indexes
and derived features. Ten source-equivalents can consume 8-20 GB. An illustrative combined
30 ticks/second * 150 bytes * 86,400 is 0.389 GB/day, ~2.72 GB/week before overhead.
Tick rates/serialization vary greatly: enforce the 10 GB cap and downsample/drop optional
raw capture with an explicit gap record. Never assume those rates bound market bursts.

At managed usage >=120 GB or free disk <60 GB: pause research/backfills, compact/expire
disposable partitions and alert. At >=135 GB or free <40 GB: pause new exposure and
optional feeds, reserve audit/reconciliation I/O. At >=150 GB or free <20 GB: deny new
work; enter controlled safety handling. Any inability to durably record an intent denies
automated money changes. Never erase audit/unknown-order evidence to keep trading.
Cold archives are optional encrypted external storage with manifests and restore verification.
If no external backup exists, retain evidence locally within budget and block live certification
until disaster recovery is proven. Long-term ledger growth triggers archive planning at Phase 6.

Database roles separate migrator, application, append-only audit writer, read-only researcher
and backup. Append-only constraints plus hash chains and signed exported checkpoints detect
tampering; a local administrator can still alter storage, so do not call local logs immutable
against administrator compromise. Restore verification includes referential/lineage checks.
