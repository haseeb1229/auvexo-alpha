# Performance and reliability

Status: PROVISIONAL acceptance budgets for non-HFT minute/hour strategies; not measurements.

Phase 1 idle-foundation measurements are recorded separately in
[verification](phase1/VERIFICATION.md). They do not qualify the following trading/load budgets.

| Path | Initial target under qualified load | Deadline/failure |
| --- | --- | --- |
| Market ingest receive-to-normalized | p95 <=100 ms | Required quote age <=2 s at opening; stale denies |
| Event/news ingest from first available source | p95 <=60 s for selected polled feeds | Record source delay separately; unknown completeness disables dependent strategies |
| Strategy deterministic evaluation | p95 <=100 ms, p99 <=250 ms | 1 s deadline, reject expired opportunity |
| Risk decision | p95 <=10 ms, p99 <=25 ms (kernel only) | Full transaction <=100 ms target; lock contention defers/denies |
| Dispatch authorization-to-gateway call | p95 <=100 ms | Broker ack excluded; 5 s watchdog -> UNKNOWN |
| Broker reconciliation | Steady state <=5 s polling; <=30 s recovery target after connectivity restored | Any unresolved mismatch denies new exposure; 60 s unresolved -> urgent owner alert |
| UI | <=1 s event-to-display p95, freshness label always visible | Reconnect snapshot; stale badge and disabled unsafe controls |
| DB bounded indexed queries | p95 <=50 ms, p99 <=200 ms | 1 s query deadline; unbounded table scans off operational path |
| Research | 1 worker, <=2 GB RAM, <=2 CPU threads, <=30 min checkpoint chunk | Throttle/pause before operational latency breaches |

The 2 s quote maximum is a provisional execution-health guard, not appropriate for every
future strategy. Strategy/source contracts can be stricter, never silently looser. Account
snapshot age target <=5 s, with reconciliation on every execution ambiguity. Clock offset
>250 ms trips freshness review/pause-new until corrected. Phase 5 measures terminal/provider
latencies; if budgets cannot be met, reject that operating regime or revise through evidence
and an ADR before qualification, not by ignoring failures.

16 GB planning envelope: OS/security/browser <=5.5 GB, backend <=1 GB, PostgreSQL <=1 GB,
MT5+gateway <=1 GB, research <=2 GB, frontend dev/observability <=1 GB, reserve ~4.5 GB.
Application aggregate cap ~6 GB; total planned active ~11.5 GB. These are targets, not
observed laptop usage. Heavy IDE/browser/WSL use consumes reserve: do not run all development
tools alongside execution. No GPU or local LLM required. Pause research if available RAM
<3 GB, system CPU >80% for 60 s, or latency breach; pause entries if RAM <1.5 GB or
operational health remains degraded. Disk rules are canonical in data architecture.

Bounded queues: initial market queue <=10,000 messages with coalescing by instrument;
durable jobs <=1,000 active/pending before rejecting new research; execution/audit outbox
never silently discarded. Set per-source rate budgets. A consumer lag/overflow becomes
an explicit data gap and resnapshot; backpressure cannot silently preserve a misleading
healthy label. One scheduled task per key avoids overlapping timer jobs. No busy loops.

Benchmark on supplied-class hardware with replayed 3-asset representative load, bursts at
5x measured arrival rate, research concurrently enabled and then throttled. Report p50/p95/
p99, throughput, sample count, dataset hash and machine/software configuration. No performance
claim until measured. Profile CPU, allocations, DB plan and I/O before optimization. LLM
latency never enters synchronous risk/dispatch logic. Slow optional modules lose budget.

Observability: structured redacted logs with correlation/intent/event IDs, counters and
histograms for feed/queue lag, broker disconnect, unknown orders, mismatched positions,
risk denials/kill state, strategy state, job failures, agent cost/time, model/provider
failures, disk/RAM/CPU/clock. Traces span API -> intent -> authorization -> dispatch ->
reconciliation without raw credentials or article content. Liveness means process alive;
readiness requires DB/journal/data/account/policy checks. A green process is not a safe desk.

Minimum local alert channels are persistent dashboard/CLI health and OS notification;
external delivery is optional, explicitly configured and tested. An alert cannot make
an offline laptop always-on. Demo may pause with sleep/lid close; live needs an approved
uptime/power/connectivity/owner-response plan and broker-side protection. Free-tier uptime
is not a capital-safety assumption.

## Phase 2 workload qualification

[Data verification](phase2/VERIFICATION.md) separates genuine bounded pilot load from
Phase 1 idle measurements. Collector: one worker, two Polars CPU threads, 16 MiB
compressed/32 MiB expanded archive, 50,000 rows per batch, explicit request/byte budgets.
No tick/quote latency guarantee or continuous uptime claim follows from closed-bar polling.
The [scheduled collection procedure](phase2/SETUP_AND_RECOVERY.md) produces genuine
daily evidence; sleeping/offline days remain gaps.

Phase 3 must benchmark the current audit-first Parquet string/canonical-record layout at
realistic multi-year 1m scale before any derived-format optimization; see
[data architecture](DATA_ARCHITECTURE.md). This is a future design/measurement requirement,
not a new storage format or a performance claim.
