# ADR-029: DS-03 actual MT5 read-only adapter engineering

Status: FROZEN_BEFORE_IMPLEMENTATION; ENGINEERING_ONLY; NO_ACTUAL_ACCOUNT_SESSION.
Date: 2026-11-03. Owner: founder. Decision scope: generic code and synthetic/native proofs.

Requirements: M5-01 through M5-15; [requirements](../phase2/DS03_ACTUAL_ADAPTER_REQUIREMENTS.md).

## Context

### Authority and predecessor

The owner supplied the 2026-11-03 macro accepting exact ba66f44/tree d57091a and authorizing
PR11 acceptance, administrative CI and NORMAL merge, then this PR12 engineering sprint.
[Acceptance](../reviews/PHASE_2_DS03_SYNTHETIC_READONLY_INDEPENDENT_ACCEPTANCE.md) is recorded.
Administrative f9a860916405a49c875ee07b54c5ea6531675b6e passed run 41516596112/job125521626311,
including all executable steps, 2455 Python tests and 31 frontend tests. Verified normal
merge fa0915130c9572c9c2a4a260b20abeaefc2c62f5 has ordered parents f47770d then f9a8609,
and equal admin/merge tree 9a5ea762c3d7e5498440c37f5fc9b0cf5b550123.
This branch starts from that merge. ADR-028 and its three companion design documents,
plus the five frozen OI documents, retain original bytes. This ADR supersedes only
synthetic-only package/admission limitations for the separate actual adapter described here.

## Decision

Adopt the exact official Windows CPython 3.13 x64 MetaTrader5 5.0.6231 wheel with SHA256
3a8c8349ce691a4ef05e314afc034ad82f4dbb19415efc7442af5ea075d5e797.
Recheck official metadata/artifact immediately before adoption. Pin a supported NumPy
version for this Windows provider only; no unrelated upgrades. Preserve MIT license
and inspect wheel/package bytes; absence of Trusted Publishing is recorded. The SDK
has trade functions and is NOT a read-only security boundary. Linux must never import it.
Scoped boundary tests replace the blanket package prohibition only for this fixed provider.

Keep accepted synthetic constructors/codecs/port/canonical bytes synthetic-only. Add a
closed actual DTO namespace (domain.ds03_actual) with exact broker symbols, digest-only
account/server/process references, actual protocol family DS03_MT5_READONLY_V1 and
synthetic=False. Reuse base validators where sound. Actual envelope/rights/reply are
strict siblings; no passing actual facts as synthetic. Actual records carry their own
first_seen_at; keep synthetic serialized fields unchanged. One shared private typed read
session implements all TTL, rights, pre/post attestation, monotonic deadlines, request
uniqueness, discovery/spec/causality/gap/duplicate/first-seen and fail-close checks. Public
synthetic and actual readers bind fixed typed codecs, with no arbitrary codec argument.
Application ports expose only attest/execute/disconnect and strict DTOs, no SDK imports.

Use an actual sibling child with fixed isolated interpreter/module, inherited anonymous
pipes, fresh 32-byte HMAC key/session, closed actual protocol, canonical JSON, exact sequence/
request/direction/source binding, 64KiB frames, 256 requests, 256 records, 128 symbols per
page, 10-second immutable UTC plus monotonic read budget and 30-second attestation age.
No listener, shell, caller-selected module/backend/executable/path or ambient Python env.
Reuse authenticated IPC and bounded pipe/lifecycle primitives rather than duplicate them.
A Windows Job Object limits the provider child and descendants to 1GiB and kills them
on boundary disposal; no escape/breakaway relaxation. Provider incompatibility with these
bounds is a future qualification refusal, never a silent resource/profile fallback.

## Dedicated runtime and connection

Derive only Path.home()/Desktop/Auvexo Alpha MT5 Readonly Runtime. Terminal is fixed at
terminal/terminal64.exe beneath it. portable=True, installation and data/profile directory
are terminal.parent. No automatic download, install, launch or real session in this sprint.
Future connection requires explicit initialize(fixed_path, login=..., password=...,
server=..., timeout=5000, portable=True). No missing argument, discovery, last account,
stored password or subsequent login switch. SDK import alone cannot initialize.

Runtime binding includes accepted release SHA/tree, fixed source inventory/interpreter hash,
installed package version and exact init/pyd/license hashes, accepted wheel hash and future
terminal hash/build/version/fixed path/profile identity. Source inventory excludes dynamic
release/authority/metadata to avoid self-reference. Future outer composition supplies exact
accepted release/tree independently; measured bytes must match authority. Unique OS process
identity uses exact executable, PID/creation time and owner, independently of SDK tuples;
no command-line/account-name collection. Canonical path, no reparse and binary/profile
identity are checked pre/post; unexpected updates/profile/process swaps close the session.
No new local machine identifiers enter public evidence.

## Staged authority, metadata and credentials

A strict local authority binds accepted PR12 release/tree, source/interpreter/package/wheel/
installed manifest, terminal hash/build/version/fixed path/profile, metadata digest, DEMO
account/server digest, account type/currency/leverage, rights review/expiry, fixed credential
purpose/version, owner read-only selection reference, PRIVATE attestation and owner authority.
The independently accepted authority digest is supplied separately by trusted outer composition;
no issuer, self-acceptance, enable boolean, environment fallback or real authority is created.
Authority lifetime and PRIVATE attestation age are each at most 24 hours, bounded by rights.
Every effect revalidates exact bindings, nonfuture UTC and expiry. Local same-owner Python/OS
compromise is outside this process boundary; digest shape is not independent acceptance.

AUTHORITY_ADMITTED permits fixed metadata/password lifecycle and one explicit initialization
attempt, without asserting observed read-only state. Only afterward can observed DEMO/login/
server/currency/leverage, connected=true, account_trade_allowed=false and terminal_trade_allowed=false,
credential provenance and exact OS/SDK identity admit a read. REAL/CONTEST/unknown/missing flags
refuse; tradeapi_disabled alone is insufficient. Refresh all evidence before and after every
read. Shutdown/invalidate/clear credential and session references on any mismatch; Python immutable
strings cannot promise forensic memory erasure. Do not retain passwords after initialize.

MT5 exposes trade_mode, not the broker Standard/Pro/Zero/Raw Spread product account type.
Record account type as OWNER_METADATA_ONLY_NOT_EXPOSED_BY_MT5; do not infer it from server
or symbol. Compare any future actually observable field before claiming it observed.

Use named production password require_absent/create/load/verify/rotate/delete APIs, all
requiring current typed admission before native construction/effect. Fixed CurrentUser DPAPI
purpose auvexo-alpha:phase2:ds03:mt5-demo-readonly-password:v1, fixed LocalAppData/AuvexoAlpha/
phase2/ds03/mt5-demo-readonly.v1.dpapi, existing provider 8–15 ASCII password rules. A distinct
fixed DPAPI metadata slot mt5-demo-account.v1.dpapi uses purpose
auvexo-alpha:phase2:ds03:mt5-demo-account-metadata:v1. No arbitrary path/purpose/vault.
Raw login/server/type/currency/leverage and terminal identity are encrypted and owner protected;
no password in metadata/authority/env/argv/task/log/JSON/plaintext file/error/repr. Reuse native
owner/SYSTEM ACL, no-follow handles, hardlink/reparse checks and atomic lifecycle without OI changes.
Public tests use identical private native mechanics under mandatory disposable UUID leaves,
never production APIs/paths or actual credentials. No public CLI creates an authority or secret.

## Provider allowlist and honest source mapping

Only explicit initialize, shutdown, version, terminal_info, account_info, symbols_get,
symbol_info, symbol_info_tick, copy_rates_range, copy_ticks_from and justified read-only
orders_get/positions_get/history_orders_get/history_deals_get are permitted. No order_send,
order_check execution, symbol_select, market_book_add, trade constructors, modify/cancel,
arbitrary lookup/getattr dispatch/eval/exec/shell or arbitrary module/file loading.
No SDK objects escape infrastructure; exact bool/int and finite float-to-Decimal(str) mapping,
provider raw float identity/hash and exact enum/bitmask meaning are retained. Unknown/unmodeled
account-history variants refuse the whole batch, never silently drop or coerce balance deals.

Discover exact names without assuming BTCUSD/ETHUSD/XAUUSD/suffix. Symbols use stable catalog
pagination (128/page, maximum 4096, digest/total/offset/complete); no completeness claim for
truncation. Shared reader admits discovered symbols only after consistent catalog completion.
If unavailable without selection mutation, SOURCE_ADMISSION_BLOCKED.
Bars query bounded half-open closed ranges (provider inclusive end normalized to end minus one
second), at most request.limit intervals before native allocation; missing intervals get explicit
UNKNOWN gaps and history depth stays unknown. Ticks use count-bounded copy_ticks_from(limit+1,
COPY_TICKS_ALL), preserve millisecond/flags/volume semantics, explicitly UNKNOWN coverage; no
complete tick claim. Ambiguous same-timestamp ticks or unsupported provider fields refuse a
whole batch instead of deduplication/fabricated ordering. Overlapping accepted history preserves
individual first-seen values and immutable fact identity. No future/time regression/spec drift.
366 days is a per-request resource cap, never an aggregate research-history cap. Record source,
account/server/mode/spec/release/config/rights/raw/normalized/provider/first-seen/received/processed/
available lineage. Untrusted clock remains STRUCTURAL_ONLY_CLOCK_BLOCKED, zero qualification.

## Consequences and review boundary

[Requirements](../phase2/DS03_ACTUAL_ADAPTER_REQUIREMENTS.md),
[provider review](../phase2/DS03_ACTUAL_ADAPTER_PROVIDER_REVIEW.md) and
[runbook](../phase2/DS03_ACTUAL_ADAPTER_RUNBOOK.md) freeze with this ADR before implementation.
Keep PR12 OPEN/UNMERGED/non-draft after exact green CI and fresh Windows verification for fresh
GPT-5.6 Sol exact-SHA review. No actual account/session/credential until PR12 accepted/merged,
PRIVATE return and separately accepted onboarding. Source-specific entity/terms/jurisdiction/
storage/retention/research/redistribution rights remain unaccepted; package MIT grants none.
Operational/OI runtime, tasks/schedules/DBs/secrets/START unchanged. Current Phase2/4 truth UNKNOWN;
OI clock blocked and forward counter ZERO. No Phase5 orders before full Phase4 + actual DS03 +
explicit authority; no REAL/money. LIVE_RELEASE_INTEGRITY_CONTROL_REQUIRED_BEFORE_PHASE8.

## Alternatives

Keep synthetic-only code: insufficient for the authorized next onboarding engineering boundary.
Use SDK in application: violates domain/application dependency and provider-object isolation.
Duplicate causal reader: rejected because controls would drift. Ambient terminal or no-argument
initialize: rejected for account/credential/profile ambiguity. Treat SDK as read-only: rejected;
its trading capability requires the explicit narrow process/interface controls above.

## Validation

M5-14 verification matrix and adversarial cases in the frozen requirements; exact committed fresh
Windows normal wheel/package hashes, disposable native secrets, retained DS03/OI and native PG,
full hosted Linux PG/Python, frontend, types/lint/docs, audits, source/history scans and byte stability.
No tests may initialize the actual SDK or invoke production credential paths in this public sprint.

## Review point

Fresh GPT-5.6 Sol review of final PR12 exact SHA/tree before merge. Actual private onboarding,
terminal compatibility/rights and accepted authority follow only under separate owner instruction.
Unexpected package/provider contradiction, isolation failure or need for actual public credentials
stops this lane for review. Later integrity/live and operational gates remain unchanged.
