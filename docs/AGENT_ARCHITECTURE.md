# Agent architecture and always-on loops

Status: FROZEN authority model; roles/loop budgets PROVISIONAL until measured in Phase 6.
No agent runtime is implemented in Phase 0. Zero enabled LLMs is a valid operating state.

| Role | Implementation decision | Allowed purpose/tools |
| --- | --- | --- |
| Supervisor / Head of Desk | Deterministic scheduler first; optional LLM briefing | Schedule bounded jobs, summarize evidence; no capital allocation authority |
| Market Radar | Deterministic service | Scan validated features and health thresholds |
| Technical / Market Structure | Deterministic features/statistical classifier | Versioned structure/regime calculations; optional explanation |
| Crypto Intelligence | Scheduled collectors + optional LLM investigator | Public derivative/spot/event evidence retrieval |
| Gold specialist | Optional LLM research role after baseline | Gold/macro/session evidence and hypothesis requests |
| Macro specialist | Scheduled release collector + optional analyst | Vintage-aware macro comparisons; no fabricated consensus |
| News / Geopolitical specialist | Optional LLM classification plus deterministic trust gates | Entity/event extraction and cited summaries |
| Bull researcher | Optional bounded LLM role | Supporting evidence for a registered hypothesis |
| Bear / Adversarial researcher | Optional bounded LLM role | Falsification and competing explanations; paired ablation with bull role |
| Risk Critic | Optional advisory LLM | Explain deterministic denials and identify missing evidence |
| Quant Research | Deterministic runner + optional LLM planner | Submit allowlisted experiment specifications; sandboxed research branches only |
| Strategy Portfolio | Statistical analysis and deterministic allocation | Correlation, concentration and approved portfolio rules |
| Post-Trade Auditor | Scheduled deterministic attribution + optional narrative | Reconcile decision evidence, costs and rejection outcomes |
| Execution Agent | Deterministic coordinator, NOT an LLM | Submit only authorized immutable intents; reconcile |

Each service/role gets a distinct identity and capability manifest: allowed data classes,
tools with schemas, permitted output namespace, token/cost/time/concurrency caps, retry
rules, evidence schema and escalation owner. Optional LLM roles above share the restrictive
research profile: read approved redacted snapshots/events; call retrieval/feature-query/
backtest-proposal tools; write proposals and run records only. No credentials, owner cookies,
live DB writes, arbitrary shell, arbitrary outbound URLs, risk/strategy promotion or withdrawals.
Individual roles receive only their listed subject tools, not the union of all tools.

Default per investigator run: <=8 tool calls, <=12,000 input and <=2,000 output tokens,
120-second wall deadline, one concurrent LLM run, one retry for a transient provider error
within the same deadline. Global <=50,000 tokens/day; paid spend default USD 0/day.
An explicitly approved funded adapter needs its own money cap in addition to token caps.
No subscription access is assumed to grant an API entitlement. Local models are optional
and may be too heavy for concurrent laptop operation; disable them under resource pressure.

Every material conclusion references source_id/event_id, market_state_id, dataset_version,
model_version, strategy_version and timestamp as applicable; missing refs mean unsupported,
not confident. Tool results are untrusted evidence. Validate schemas, evidence existence,
availability times and tool authorization outside the model. Prompt injection cannot expand
permissions. Sandbox research browsing uses a dedicated disposable profile and egress
allowlist; official APIs then permitted feeds precede browsing. Never personal Chrome or
browser-click trading. Log URLs/tool outcomes, redact secrets and respect provider terms.

ModelProvider port: structured request, model/prompt/version, deadline, token cap, tool
allowlist and structured result/usage/error. Swap providers without changing risk semantics.
Provider outage opens a circuit after 3 failures/5 minutes, with one bounded half-open
probe after 5 minutes. All providers down disables dependent opportunities; deterministic
qualified strategies and position protection continue if their own inputs remain healthy.

## Event loops

Common loop rules: durable job identity and checkpoint; bounded queues; no infinite LLM
polling. Read-only transient I/O retries at 1/2/4 seconds with jitter, at most 3 retries
within stated deadline; provider quotas take precedence. Money-changing sends are never
automatically retried on unknown outcome. Every loop stops at deadline, shutdown or kill
state; requeue only durable idempotent work. Failure creates a typed error and alert.

| Loop / trigger | Work budget, tools and state | Timeout/retry/idempotency | Verifier, stop/failure/escalation |
| --- | --- | --- | --- |
| Fast market / feed event | Deterministic normalize/features; <=50 ms batch target; source watermark | 2 s freshness guard; bounded read reconnect; source+sequence key | Sequence/lag checks; quarantine gaps, pause dependent entries; owner on >60 s outage |
| News/event / feed item or 60 s due poll | Collect/dedup; classify novel material items only; event cluster | 30 s fetch; classifier 120 s; source/hash job key | Trust/evidence schema; timeout leaves UNCONFIRMED, no dependent trade; alert on required feed loss |
| Macro / scheduled release window | Due schedule, fetch original release/vintage, calendar state | 30 s job; up to 3 reads; release+vintage key | Official source/time check; missing release stays unknown and blackout persists; owner |
| Opportunity / closed bar or qualified event | Strategy features/candidate/risk; <=100 ms strategy target | 1 s job deadline excluding agent investigation; snapshot+strategy+instrument key | Deterministic candidate verifier; stale/duplicate -> NO TRADE; counterfactual record |
| Open position / fill or 1 s due timer | Exposure/stop/state checks; position version | 1 s task; fresh broker reads bounded; position+event key | Broker protection and risk verifier; escalate unprotected or mismatched position immediately |
| Execution/reconciliation / outbox, broker event, 5 s poll | One account writer; order/position/history queries; journal epoch | Submission watchdog 5 s then UNKNOWN; reconcile cycles <=10 s; intent+attempt/fill keys | Account/permit/fill checks; pause new entries on UNKNOWN; urgent owner alert |
| System health / 5 s timer | Lag/CPU/RAM/disk/readiness/clock; health state | 1 s check; no recursive retry; service+interval key | Threshold evaluator; trip K1/K4 as relevant, stop research first; owner alert |
| Research / approved queued hypothesis | Bounded dataset/backtest tools; one worker <=2 GB RAM/2 CPU threads | <=30 min chunk, checkpoint; 1 infrastructure retry; experiment+config+dataset key | Reproducible output/holdout checks; failed artifact retained, no promotion; research review |
| Daily review / UTC day close | Ledger/cost/counterfactual summary; day watermark | <=5 min; 1 retry; date+report version key | Balance/coverage totals; incomplete marked, never silently green; owner digest locally |
| Weekly edge / UTC week close | Drift, champion/challenger, ablations; evidence windows | <=15 min; 1 retry; week+registry version key | Sample/threshold checks; WATCH/SUSPEND per policy, no self-edit; owner review |

Deadlines are maximum work envelopes, not promises of market/provider latency. Persistent
timeouts fail readiness qualification. Coalesce redundant price snapshots; never silently
drop execution/audit events. Agent notifications are stored locally by default; external
notification channels require explicitly configured owner destinations and consent.
