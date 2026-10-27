# Proposed open-interest runbook and architecture

Status: ACCEPTED/FROZEN for Phase 6A1 source/feature-foundation engineering design at
887b6ac38636e07ff922d2ba2d0ec7b2063edd4f; independent GPT-5.6 Sol acceptance.
Implementation requires the owner-authorized verified PR #9 merge sequence; NO COLLECTION / ACTIVATION AUTHORITY. Date:2026-10-27.
See [ADR026](../adr/026-ds04-open-interest-intelligence.md), [requirements](OPEN_INTEREST_ACCEPTANCE.md),
[rights](SOURCES_AND_RIGHTS.md) and [experiment](EXPERIMENT_PREREGISTRATION.md).
All procedures below describe future work; no executable schema, commands or task XML.

## Point-in-time record proposal

| Fields | Required semantics |
| --- | --- |
| Identity | source_id DS-04-A1; provider Binance; exact Binance RIE/USDⓈ-M product/version; BTCUSDT or ETHUSDT; field_family open_interest_snapshot; source URL/endpoint/document-review version |
| Value | Original openInterest string plus exact nonnegative Decimal; original symbol; unit PROVIDER_NATIVE_OI_UNSPECIFIED, no base/contracts/currency/notional conversion |
| Provider time | Original integer time and milliseconds-to-UTC mapping; publication/schedule time UNKNOWN unless expressly supplied; provider time never becomes first-seen |
| Observation | request_sent, first_seen_at, received_at, processing_at, available_at UTC; available>=processing>=receipt>=first_seen>=request_sent for first acquisition; actual observation, no historical-close fiction |
| Hash/version | Exact raw-byte SHA256; canonical normalized hash; parser/schema/code, source-document/right-review, manifest/dataset version/hash |
| Quality | VALID/STALE/UNAVAILABLE/QUARANTINED/BLOCKED, stable reason, provider-age/clock/gap and unit interpretation |
| Revision | Source/product/symbol/provider-time/parser identity, raw-content version, prior/supersedes hashes, conflict/review disposition; immutable originals |

Receive time is complete response receipt. On first acquisition first_seen is actual local
observation no later than receipt, never backdated. Repeated identical provider fact keeps
earliest first_seen/availability; repeated receipt cannot refresh stale time. Same identity
with conflicting bytes appends quarantine/revision lineage and requires review. Out-of-order
facts cannot rewind features. Raw facts remain distinct from derived features; no LLM values.
No missing-to-zero/flat conversion or silent venue/product substitution. Unit stability is
an explicit unresolved provider-semantics assumption, not established by positive values.

## Future collector boundary

Only GET https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT or ETHUSDT.
No arbitrary path/query/URL/header, credentials/cookies/Authorization/client certificate,
MCP/account/session/testnet or redirects/host fallback. Disable environment proxy/credential
inheritance; unavailable direct access stays unavailable, no region bypass. Fixed safe
User-Agent/Accept application/json only; typed redacted errors, no raw exception/body logs.

Proposed cadence: one hourly snapshot per symbol; BTC at UTC hour h, ETH not earlier
than h+2seconds. One request at a time, >=2seconds between attempts, <=6attempts/hour,
<=144attempts/UTCday; project limits do not override a tighter provider restriction.
Skip an entire slot if [h,h+60seconds] intersects20:45-22:15 or22:45-23:20 Pakistan.
No replacement/wake/catch-up. Future source starts only after separate owner START.

Per attempt connect<=3s, read idle<=3s, total<=10s; aggregate symbol job<=20s and shared
slot<=60s. Raw/decompressed body<=4KiB; refuse excess expansion, bad content type,
duplicate JSON keys, unknown/missing fields, nonfinite/negative OI, wrong symbol/product
or invalid time. Provider age means received_at minus provider_time. Preserve raw zero but denominator
features remain unavailable. Future,
recycled/stale/clock-uncertain facts cannot be current admitted evidence. Trustworthy local
UTC must be verified before START; no extra provider-time route is admitted.
Retry eligible transient network/5xx only, <=2retries with1s/2s nominal backoff;
actual wait=max(nominal backoff, remaining global2second spacing), within all budgets.
Do not retry4xx/schema/rights errors.429/418/access restriction stops and persists cooldown;
honor safe bounded Retry-After, unknown cooldown conservatively3days using accepted
pattern. Restart cannot clear cooldown. No infinite retry or hidden alternate provider.

Reuse existing Phase2 transport/cancellation/quota/cooldown/immutable-publication patterns
in later explicit source-scoped contracts. PublicHTTP currently rejects this host and
Candle/SourceIdentity/manifest/store/research classifiers are spot-specific. Do not claim
existing compatibility, coerce OI into Candle, globally widen spot paths or create a second
unmanaged store. No concrete collector/setup implementation is present in this proposal.

## Storage / retention / lineage

Private/local raw response -> content-addressed immutable artifact/manifest -> typed OI
record -> causal feature manifest -> research ledger. Preserve raw versus canonical hashes,
original timestamps and source/right/parser/code versions at each step. Verify corruption
before admission. Publish immutable artifacts before adopting metadata; orphans never imply
acceptance. Duplicate identity is idempotent; conflict retains originals/review lineage.
Use accepted quota/access/atomic-publication patterns, explicit gaps and rights propagation;
combining lineage cannot upgrade data-use eligibility. Raw/normalized/derived research
artifacts never enter Git. Retain necessary reproducibility evidence under the accepted
rights/necessity inventory, not an invented unrestricted provider retention licence.

Existing generic SQL metadata might suffice. If later proven insufficient, require
MIGRATION_REQUIRED_PROPOSAL with exact need, compatibility, isolated verification,
forward recovery and rollback expectations before any implementation. No migration now,
no use of active Phase4 observation DB. No PRICE_CLOSE_PLUS_CAUSAL_LAG for live OI.

## Initial deterministic feature family

| Version | Formula/unit/history | Invalid/missing/causality policy |
| --- | --- | --- |
| oi.level.v1 | Q[h], native unspecified OI unit; one valid snapshot | Diagnostic only; no cross-symbol level comparison/conversion |
| oi.delta1h.v1 | Q[h] minus Q[h-1]; same native unit; two adjacent hourly slots | Gap/clock/parser/unit drift unavailable; no row-count bridging |
| oi.frac1h.v1 | (Q[h]-Q[h-1])/Q[h-1]; dimensionless; two positive adjacent snapshots | Denominator<=0/invalid/gap unavailable; actual availability by prediction time |

No price/index/funding/basis helper, rolling normalization/log/acceleration variant,
fitted scaler or feature zoo. Within-symbol ratios require stable unit/product semantics;
change/unknown drift blocks interpretation. No future label can enter a feature.

## Future task / disable / independent gates

A later persistent task may be needed: single-instance IgnoreNew, limited identity,
code/config/source/right hashes, no stored password/elevation/wake/power changes, no
catch-up, strict protected-window exclusion. A definition is not START; no XML/setup
code/registration now. CPU-only/one worker/spendUSD0; optional research pauses first under
pressure; no competition with Phase2/4. Retained snapshots keep original time and explicit
stale/blocked disposition. Rights/hash/source/security/clock/unit failure disables admission;
no automatic safe-state/cooldown reset. Preserve evidence pending reviewed lawful disposition,
never patch ledgers, receipts or provider facts. Restart must revalidate current gates.

Independent proposal acceptance -> new owner implementation scope -> isolated accepted
implementation -> current rights/retention/product/unit/clock/security proof -> reviewed
task/config -> separate future owner START. PHASE6_FORWARD_CLOCK=ZERO until all gates.
No software pass/fixture/CI grants dates or operational enablement. Phase2/4 fullOPEN and
current counts/span/replayUNKNOWN; Phase5 commissioningNOTSTARTED/DS03BLOCKED. No broker,
MCP/account/order/money or runtime AI authority. No operational repair/DB startup here.

Proposed [OI-16](OPEN_INTEREST_ACCEPTANCE.md) applies even after a future
PASS_RESEARCH_PREDICTABILITY: OI-FWD-v1 is predictability-only; the canonical Phase 6
incremental-value/module-enable/progression gate remains OPEN. No operational OI or
strategy promotion follows. A separately preregistered future/unconsumed value ablation
under current rights and accepted dependencies is required first, with no consumed
Phase 3 OOS selection/reuse. That later study is not designed or authorized here.
