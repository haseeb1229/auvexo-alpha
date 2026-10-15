# Auvexo Alpha — Phase 0 handoff

Date: 2026-10-15. Verdict: **PASS-WITH-OPEN-GATES** for the documentation and repository
baseline only. Independent review is pending. No production trading implementation exists.

## Repository and delivery

| Item | Evidence |
| --- | --- |
| Repository | [haseeb1229/auvexo-alpha](https://github.com/haseeb1229/auvexo-alpha) |
| Visibility | PRIVATE, verified through GitHub |
| Branch | `phase-0/product-architecture-freeze` |
| Main baseline | `b70db178eacf51f856a6a8538381ae4c060d73f0`, pushed to main |
| Architecture content commit | Recorded after the documentation validation commit |
| Final handoff commit | Exact SHA supplied in delivery receipt/final response; a commit cannot embed its own hash |
| Phase 0 push | Pending final validation and push; main remains unmerged |
| Git identity | Muhammad Haseeb, `abdulhaseeb1229@gmail.com`; authenticated GitHub owner haseeb1229 |

Changed/created files: root README, .gitignore and .gitattributes baseline; aligned AGENTS.md
and CLAUDE.md; all documents in the [document index](README.md); ten records in the
[ADR index](adr/README.md); the archived source brief; verification evidence; and
`tools/check-docs.mjs`. Full exact inventory is available with `git ls-tree -r --name-only HEAD`.
No source application, dependency lockfile, client or trading adapter was created.

## Product and architecture outcome

Auvexo Alpha is a private BTC/ETH/XAU alpha research and validation system with gated
autonomous execution. NO TRADE is a first-class outcome. Profitability is neither assumed
nor established. Auvexo's other future products remain separate systems/repositories.

Agentic investigation surrounds a deterministic core. A modular Python backend owns
instruments, point-in-time features, experiments, strategies, risk, execution/reconciliation
and audit. A bounded research worker and isolated Windows MT5 gateway have distinct
capabilities. Agents propose typed candidates; the kernel authorizes a bounded immutable
intent; only the gateway can construct broker requests. Agents cannot alter live limits,
promote strategies, sign permits, access execution credentials or withdraw.

Stack direction: supported CPython, FastAPI/Pydantic, PostgreSQL with SQLAlchemy/Alembic,
Parquet, NumPy/Polars/SciPy and later justified statistical libraries. Plain PostgreSQL
transactions and durable job/outbox tables avoid early bus/extension overhead. Timescale,
Redis/NATS, heavyweight ML/agent frameworks and monitoring stacks remain evidence-triggered
options. No Kubernetes. Exact versions are deliberately researched/pinned/tested in Phase 1.

The Python MT5 integration is the provisional first transport; EA/hybrid alternatives were
compared for callbacks, reliability, Windows dependency, duplicate prevention and recovery.
Actual Exness demo failure tests decide transport qualification. Broker execution facts
are authoritative; an unknown outcome holds risk capacity and reconciles before any retry.

RESEARCH/BACKTEST/PAPER/DEMO/SHADOW/LIVE_LIMITED/LIVE share domain semantics. PAPER uses
virtual execution; SHADOW cannot send. Real mode independently requires correct attested
account, eligible venue/product, qualified release, signed permit, step-up owner activation,
fresh market/account state and risk authorization. Credential swapping cannot arm live.
Current real allocation is zero. Binance live derivatives remain BLOCKED_BY_POLICY;
public spot/derivatives intelligence and later paper are permitted. Bybit/OKX execution
is outside initial scope. Financial/religious eligibility remains an auditable owner policy.

## Research, resources and cost

Preregistered hypotheses, deterministic features, availability-time/vintage data, walk-forward
and untouched OOS, leakage checks, realistic cost/fill stress and simple baselines precede
promotion. All failed trials remain visible. Mandatory rejected-candidate/counterfactual
book and paired ablations measure filter/news/macro/agent value. Edge decay can tighten or
suspend, not silently mutate or promote code. Historical LLM contamination requires
prospective evaluation. Operational readiness alone does not establish edge.

Planning estimate: ~11.5 GB active RAM including OS, ~4.5 GB reserve on 16 GB; research
worker <=2 GB/2 CPU threads, no GPU. Managed disk target 120 GB, hard quota 150 GB, with
separate pressure thresholds and bounded raw ticks. Three assets over five years yield
~7.884 million minute bars (~0.8-2.0 GB/source at the stated compression assumptions).
These are estimates; measured qualification is OD-08. Same-disk backups are not disaster
protection. Off-device encrypted restore and reliable runtime/owner response gate live.

Free-first path requires no paid API/data/cloud/LLM subscription. Paid budget defaults to
USD 0. Existing chat subscriptions are not treated as API entitlements. Optional sources
require legal access, incremental-value evidence and explicit spending approval. All LLM
providers can be down while qualified deterministic strategies/protection continue safely.

## Reuse, security and engineering

Hummingbot order lifecycle, Freqtrade lookahead analysis, LEAN brokerage transaction handling,
TradingAgents orchestration and OpenBB provider abstraction were inspected as references;
CCXT is a deferred dependency candidate. None was adopted or copied. Observed root licenses:
Hummingbot/LEAN/TradingAgents Apache-2.0; Freqtrade GPL-3.0; OpenBB current root declares
Apache-2.0 despite GitHub NOASSERTION metadata; CCXT MIT. Exact-revision license, NOTICE,
transitive dependency and security review precede any adoption. See [review sources and
limitations](OPEN_SOURCE_REUSE_REVIEW.md); no upstream vulnerability-free claim is made.

Security baseline: one owner, no public signup, passkey/step-up direction, OS secret store,
separate environment credentials, least privilege, no withdrawal capability, authenticated
gateway, signed permits, append-only/tamper-evident audit and tested encrypted recovery.
Private repo and obscure domain do not replace authentication. Local administrator compromise
is a residual threat, disclosed rather than hidden by the word immutable.

Performance targets include <=100 ms p95 normalization/evaluation/dispatch stages, <=10 ms
p95 kernel decision, bounded DB/queue latency and explicit stale/unknown refusal. Broker
latency is measured separately. Backpressure and research throttling protect operational
work. Logs/metrics cover feed and queue lag, broker mismatch, risk/strategy status, agent
cost/time, providers and machine resources. Targets are not benchmark results.

Future React/TypeScript web, Tauri desktop, Expo/React Native Android and voice clients use
versioned typed contracts/presentation adapters. No trading-domain UI imports or client
broker keys. Dangerous voice commands require action-specific step-up. External Auvexo
systems get scoped APIs/events, never shared tables or implicit execution authority.

AGENTS.md and CLAUDE.md require canonical-doc reading, phase limits, deterministic risk,
live-policy preservation, frontend separation, no duplicate/dead code, justified dependencies,
unchanged merged migrations, real verification, no weakened tests/secrets/AI trailers and
exact handoff evidence. Structural checks run now; runtime lint/type/contract/security
enforcement is a Phase 1 deliverable, not falsely claimed complete here.

## Roadmap and decisions

Phase 0 freeze -> 1 engineering foundation -> 2 trustworthy data -> 3 backtest correctness
and simple alpha -> 4 strategy/risk/paper -> 5 Exness demo and sustained shadow -> 6
derivatives/macro/news/agent incremental value -> 7 clients -> 8 independent live certification
and explicitly authorized tiny capital -> 9 separately approved scaling.

Frozen: product/authority boundaries, gated shared modes, private standalone repo, client
decoupling, PostgreSQL/Parquet direction, durable jobs, provenance, free-first, research
promotion and security/local-first requirements. Provisional: precise stack versions,
Python-first MT5 qualification, performance/retention estimates, auth implementation and
preregistered experiment thresholds. Deferred: bus/Timescale/cache, rich data/heavy models,
clients and external engines/adapters until their specified triggers.

All open decisions have owner, evidence and decision point in [OD-01..OD-15](OPEN_DECISIONS.md).
Future external gates include actual demo source/account access; live financial/religious/
jurisdiction eligibility and numeric capital policy; recovery medium and uptime/response;
independent security/readiness approval. None is silently satisfied by this handoff.

## Verification and next-phase gate

See [verification evidence](validation/PHASE_0_CHECKS.md) and [internal review](PHASE_0_SELF_REVIEW.md).
Final exact commands/results and remote comparison are recorded at delivery. No runtime,
broker, performance or profitability tests are claimed. Internal contradictions found during
review were resolved before the content commit; external reviewer acceptance remains open.

Before Phase 1: reviewer receives this complete repository at the exact final handoff SHA;
checks R-000..R-039 and safety subrequirements plus all ten ADRs; issues a dated disposition;
critical findings are fixed in new commits and re-reviewed; founder supplies the explicit
Phase 1 prompt stating accepted baseline and scope. Open future-live gates may remain open
because Phase 1 cannot trade. Merge, if later desired, is a separate authorized action.

Immediate founder action: send the handoff/commit to the independent reviewer, then provide
their disposition and next-phase prompt. No credential, signup or financial decision is
needed now. Python setup is ordinary Phase 1 engineering, not work offloaded to the founder.

Confirmed: **no demo or real trading occurred; no trading account was connected; no paid
service was purchased or signed up for; Binance live derivatives remain blocked; Phase 1
was not started; Phase 0 was not merged into main.**
