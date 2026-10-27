# Phase 6A1 DS-04-A1 engineering implementation

Status: IMPLEMENTED ENGINEERING CHECKPOINT; independent exact-SHA code review pending.
No collection START, empirical result, module enablement or financial authority.
Proposal design source independently accepted at 887b6ac38636e07ff922d2ba2d0ec7b2063edd4f.
PR #9 administrative acceptance commit5344c596423dd8221a4d1ba45f4ab98742a273ac normally
merged at63fd627d0166efcfe716886af31ba96f299c79da, with ordered parents
94b7d66d3c7531a513759bab202a13bf3c2500b0 and5344c596423dd8221a4d1ba45f4ab98742a273ac.
The merge tree exactly equals the administrative tree. See [independent acceptance](../reviews/PHASE_6A1_OI_PROPOSAL_INDEPENDENT_ACCEPTANCE.md).
Engineering branch: phase-6/ds04-open-interest-engineering; executable PR stays OPEN/UNMERGED.

## Implemented boundaries

| Component | Actual implementation and invariant |
| --- | --- |
| [OI contracts](../../src/auvexo_alpha/domain/open_interest.py) | Distinct source/rights/observation/manifest types, native unspecified OI unit, exact accepted evidence/version/hash and due date, causal timestamps, explicit quality/conflict lineage; no Candle coercion. |
| [Strict parser](../../src/auvexo_alpha/infrastructure/oi_parser.py) | Exactly three JSON fields, duplicate/extra/missing refusal, bounded plain Decimal/string/integer time, symbol/unit/chronology/stale/future checks and raw SHA256. Zero is retained; fractional denominator zero stays unavailable. |
| [Source-scoped transport](../../src/auvexo_alpha/infrastructure/oi_http.py) | Only the two literal fapi OI URLs. Existing spot PublicHTTP and allowlist unchanged. Fixed GET/headers; no auth/key/cookie/proxy/redirect/provider fallback. Killable child bounds DNS/connect/read, reserves cleanup inside <=10s attempt; <=20s symbol/60s slot. One worker, >=2s spacing, <=6/hour/144/day, <=4KiB, <=3 attempts, nominal1/2s backoff. |
| [Immutable OI store](../../src/auvexo_alpha/infrastructure/oi_store.py) | Existing generic append-only data tables, dedicated OI database/least-privilege data-writer LOGIN, exact loopback/actual endpoint attestation, never operational55432. Atomic no-replace raw/normalized publication, content hashes, quota/path/reparse guards, idempotency, conflict quarantine, out-of-order/recycled refusal, staging/orphan reconciliation and as-of admission. |
| [Same-evidence review continuity](RIGHTS_REVIEW_CONTINUITY.md) | [Typed verifier](../../src/auvexo_alpha/domain/oi_rights_review.py) accepts only externally accepted same-evidence hash chains, with original base rights/study fixed, observation receipt stamps, late-review gaps and no issuer or automatic extension. Default remains the original review deadline. |
| Durable network state | Reserve PENDING in append-only PostgreSQL before each attempt. Completion/cooldown follows; unknown crash/kill/persistence outcome fails closed on restart. Received429/418/403/451 blocks persist before cancel/deadline checks. Concurrent/stale state cannot lower counters or cooldown. No automatic uncertain-state reset. |
| [Feature and research engine](../../src/auvexo_alpha/application/oi_research.py) | Native level, adjacent absolute/fractional hourly change only. Exact symbol/source/parser/code/rights/input hashes and actual availability bind features/forecasts. Immutable input-only forecasts precede later target scoring; missing targets retained unscored. Persisted ledger recomputes derived records from verified registered parents. |
| OI-FWD-v1 | Fixed48h warm-up,90calendar-day window,80joint-valid days,1500pairs/symbol,>=30genuine days. Calendar/null/dependence preserved; fixed5000 aligned noncircular moving-block draws, seed1229, L14 primary/L7/28 sensitivity, two co-primary symbols and frozen decisions. Descriptive MAE/RMSE/bias/coverage/clipping/creation-lag do not rescue primary failure. No real study was executed. |
| OI-16 | Typed result permissions remain literal false for operational enablement, value approval, promotion and progression. PASS_RESEARCH_PREDICTABILITY cannot satisfy the canonical Phase6 incremental-value exit or upgrade data-use rights. |
| [Schedule/START contracts](../../src/auvexo_alpha/domain/oi_schedule.py) | Exact hourly slots, UTC16/17/18 exclusion, ETH>=h+2s,15s launch lateness/no catch-up. Default disabled; separate owner envelope and externally accepted digest bind config/build/source/rights/preregistration/review references. No START issuer exists. |
| [One-slot job](../../src/auvexo_alpha/infrastructure/oi_collection.py) | Immediate source-global PostgreSQL lease, no queue/busy loop; resource/clock/rights/START/deadline gates rechecked after waits. No collection before T0 or after fixed evaluation end. Restart cannot repeat a successful symbol slot. Optional research yields first. |
| [Runtime preflight](../../src/auvexo_alpha/infrastructure/oi_runtime.py) | Exact clean Git/build/lock/preregistration hash checks; bounded read-only Windows time-service inspection; unknown/localized clock evidence blocks. Missing optional resource probe yields rather than starting. No clock/power/service change. |
| [Future task renderer](../../tools/oi_task.py) and [collector CLI](../../tools/run_oi_collection.py) | Render-only disabled XML, InteractiveToken/LeastPrivilege, IgnoreNew, no wake/catch-up/on-demand. Reviewed START arguments may be represented later; no task registration/start or real activation was performed. CLI requires external accepted START and never falls back to operational secrets. |

## Source rights and migration disposition

Only DS-04-A1 Binance USDⓈ-M current OI snapshots for BTCUSDT/ETHUSDT are admitted for
personal noncommercial NONPRODUCTION research. [Accepted rights](SOURCES_AND_RIGHTS.md)
remain exact-source bounded, review due2026-11-27 or earlier relevant change. Raw,
normalized and derived artifacts stay private/local/ignored; no redistribution/live grant.
The source-document hash in code names accepted substantive bytes, preceding administrative
status alignment. No base quantity/contracts/notional conversion is inferred.

No migration: accepted data_manifest/data_event/data_checkpoint/data_source_review tables
already bind immutable payloads/hashes and source-scoped checkpoints. Root parser_version
is explicit OI, preserving the existing generic index. OI uses dedicated names
auvexo_dev_oi<alphanumeric> or auvexo_test_oi<alphanumeric>, compatible with the unchanged
migrator allowlist. Never mix spot manifests or use the active Phase4 database. Runtime
accepts only the data-writer LOGIN and rejects55432 even when a URL appears otherwise safe.
Existing append-only grants/triggers remain intact. No schema/role/grant workflow change.

The standalone collector checks disabled/protected-window/late-launch schedule gates
before build inspection, clock subprocess or any database connection. Its new-source
footprint is dedicated ignored .local/phase6/oi-managed/artifacts, with managed quota
root .local/phase6/oi-managed; engineering toolchains/caches are not part of that new
source tree. Existing Phase2/4 managed quotas, roots and exclusions are unchanged. The
separate volume-wide resource preflight still requires disk headroom and optional
research yields under memory/CPU/disk pressure; a dedicated source quota does not waive
existing managed-storage or global capacity gates.

The accepted rights snapshot cannot cover the whole90day study today. Expiry blocks new
admission and result interpretation; a separately reviewed renewal/version is required,
never auto-extended or manufactured. Collection START also requires independently accepted
implementation, current source/unit/clock/rights/retention/security proof and reviewed
configuration/task/owner authorization. A caller-constructible config/envelope alone is
not claimed to be independent acceptance or resistance to a compromised local owner.

The prebuilt [same-evidence review-continuity verifier](RIGHTS_REVIEW_CONTINUITY.md)
keeps the exact base rights/source/code/study identity fixed while verifying a separately
accepted immutable chain of project review continuations. Observations bind the receipt
active at original admission; late acceptance leaves a gap, never backdating/catch-up or a
new study ID. Default unknown/newer/changed evidence remains blocked. No continuation or
later deadline is issued in this run. RIGHTS_CONTINUITY_ACCEPTANCE_REQUIRED remains an
external gate as each review comes due; its typed verifier and storage/research plumbing
are supplied by this engineering checkpoint. Current accepted due remains2026-11-27.
No elapsed time, fixture or predictability PASS can satisfy that external acceptance gate.

## OI-01 through OI-16 evidence map

| Requirements | Test evidence |
| --- | --- |
| OI-01,12,13,15 | [Collection/schedule/task tests](../../tests/test_oi_collection.py): disabled/default, windows, no catch-up, START/hash/clock/resource/expiry/cancel/busy/CLI denials, bounded whole-job synthetic flow, disabled XML. |
| OI-02 review continuity | [Review-chain tests](../../tests/test_oi_rights_review.py), research and isolated storage fixtures cover exact external digests, changed/revoked/unknown evidence refusal, timely boundary lineage and late gaps. |
| OI-02,03,05,06,09 | [Contract/parser tests](../../tests/test_oi_contracts.py): exact rights/expiry, cross-product negatives, Decimal/property tests, timestamp/field/quality rejection. |
| OI-03,04,06,12 | [Network tests](../../tests/test_oi_http.py): exact allowlist, headers/proxy/redirect, byte/deadline/retry/cancel/budget, persistent cooldown and crash-unknown refusal; no real endpoint. |
| OI-07,08,14 | [Real isolated storage tests](../../tests/test_oi_storage.py): raw/normalized/hash/idempotency/conflict/corruption/quota/reparse/crash/orphan/lease, direct LOGIN privilege negatives and recomputed immutable ledger. |
| OI-09,10,11,16 | [Research tests](../../tests/test_oi_research.py): fixed formulas/clip, no future targets at forecast creation, calendar/sample/nulls, independent naive bootstrap reference, all verdicts and explicit permission denials. |

Inherited local formatting/Ruff/strict mypy/docs/scans/audits/frontend and regression
receipts are retained under ignored Development .local/phase6/engineering; final exact
counts/timings and CI run IDs are consolidated in the delivery handoff. Failed attempts
remain evidence and are never relabeled PASS. Windows resource and filesystem coverage
is retained separately from the complete unchanged security suite in an isolated Linux
network namespace when fixed55432 service guards require it. Host operational55432 is
never started/stopped/connected/repaired for Development verification.

## Value mechanism, smoke and residual gates

[Future value-ablation disposition](VALUE_ABLATION_PREREGISTRATION.md):
VALUE_ABLATION_PREREGISTRATION_BLOCKED_MECHANISM. The accepted OI-only mechanism supplies
no justified OI-to-price-candidate rule; no arbitrary filter or thresholds were invented.
This narrow allowed blocker does not stop source/feature-foundation engineering.
Both consumed Phase3 holdouts remain permanently unavailable for selection/reuse.

Optional real-source smoke: NOT PERFORMED. Zero OI endpoint calls; synthetic fixtures
prove engineering only. No empirical result/price alpha/value/qualification claim.
PHASE6_FORWARD_CLOCK=ZERO; persistent collector/task NOT REGISTERED/NOT STARTED.
Phase2/4 full operational OPEN, current genuine counts/span/replay UNKNOWN; Phase5
commissioning NOT STARTED/DS03 BLOCKED. No later DS04 family, macro/news/agents, broker,
MT5/Exness/account/key/order/money/live permit or withdrawal capability.
