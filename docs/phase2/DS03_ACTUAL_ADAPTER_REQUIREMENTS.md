# DS-03 actual adapter engineering requirements

Status: FROZEN_BEFORE_IMPLEMENTATION; ENGINEERING_ONLY; NO_ACTUAL_ACCOUNT_SESSION.
Date: 2026-11-03. Authority: [ADR-029](../adr/029-ds03-mt5-readonly-adapter.md).

| ID | Required behavior and proof |
| --- | --- |
| M5-01 | Verified PR11 normal merge before this branch; four new design files committed before executable code; original DS03/OI freezes byte stable. |
| M5-02 | Exact Windows-only MetaTrader5 5.0.6231 CP313 x64 wheel/hash, fixed supported NumPy pin, deterministic lock/export, no unrelated upgrades; license/provenance review; installed init/pyd/license hashes; fresh Windows import only with no initialize/login/terminal. |
| M5-03 | Existing synthetic constructors/codecs/canonical bytes/port remain synthetic-only. Closed actual DTOs, strict unknown-field/type/duplicate-key/NaN/oversize/Decimal/UTC validators; single shared typed causal session, fixed public wrappers, no SDK domain/application imports. |
| M5-04 | Dedicated fixed home-derived runtime/terminal/profile, portable=True; no automatic install/discovery/fallback. Explicit fixed initialize path/login/read-only-password/server/5000ms/portable; missing/arbitrary/path/hash argument refusal. No login switch. |
| M5-05 | Separate strict authority and encrypted metadata, independently accepted authority digest, exact release/tree/source/interpreter/package/terminal/account/server/type/currency/leverage/rights/purpose bindings; PRIVATE/owner/read-only provenance, 24h TTL and PRIVATE age; no issuer/enable/env bypass. |
| M5-06 | Staged fixed-slot admission before effects; observed connected DEMO and exact login/server/currency/leverage, owner-only product account type provenance, both account/terminal trading false, independent OS process/hash/path/profile/build>=4755; REAL/CONTEST/unknown/absent/stale/swap/drift refuse. Pre/post refresh, invalidate and shutdown on mismatch. |
| M5-07 | Fixed CurrentUser DPAPI password + separate metadata slots, named require_absent/create/load/verify/rotate/delete, 8–15 provider syntax, native ACL/no-follow/hardlink/reparse/atomic safety. No plaintext/env/argv/config/log/error/repr; no production API in public verification, identical disposable UUID native mechanics only; OI unchanged. |
| M5-08 | Only ADR029 explicit SDK call allowlist; no trade/modify/cancel/select/subscription/arbitrary dispatch. Static AST and dynamic forbidden-operation tests, fake modules only for lifecycle. SDK objects and personal account names/comments never escape/log. |
| M5-09 | Fresh isolated fixed actual child, authenticated inherited pipes/session/sequence/request/direction/source binding; 64KiB/256 requests/256 records/10s/30s age, one pending read, 1GiB kill-on-close Windows Job Object. Replay/duplicate/oversize/broken-pipe/crash/timeout/restart invalidate, clean disconnect and new bootstrap required. |
| M5-10 | Exact suffix discovery; stable bounded catalog pages/digest/total/completion, no silent truncation/mutation. Full available symbol specs and raw bitmasks/provider meanings, explicit unavailable facts, absent symbol/spec drift refuse. |
| M5-11 | Closed bounded bars/unknown gaps/history; count-bounded ticks never complete, preserve time_msc/flags/float identity; account facts preserve enums/zero/nonmarket variants or wholebatch unsupported refusal. Duplicate/conflict/future/regression/spec/first-seen refresh tests, overlap retains record first-seen. |
| M5-12 | Complete source/account/server/DEMO/spec/release/config/rights/provider/raw/normalized/time lineage, rights expiry deny; structural clock-blocked labeling earns ZERO actual qualification. 366-day cap per request only. |
| M5-13 | Account-specific legal entity/terms/platform/API/jurisdiction/storage/retention/research/redistribution rights remain future PRIVATE onboarding; public package facts never grant broker rights. No actual session/secret/broker account input or data. |
| M5-14 | Focused retained DS03/OI tests, native disposable DPAPI and 12 OI PG proofs, full Python/PG hosted Linux, strict Linux+Windows mypy, Ruff/docs/equal agents/diff, full source/history Gitleaks/high-signal, hash-locked audits/frontend, exact committed normal-wheel fresh Windows and source byte stability. No test/workflow weakening. |
| M5-15 | One founder-authored PR12 OPEN/UNMERGED/non-draft with exact SHA/tree/CI/diff/frozen hashes/evidence; fresh external review required. Operational/OI releases and tasks unchanged, Phase2/4 UNKNOWN, forward ZERO, all later gates retained. |

Adversarial coverage includes: REAL/CONTEST/unknown trade_mode; each identity/credential/terminal/
process mismatch; missing connection/read-only flags; authority digest/release/package/private/rights/
expiry drift; malformed requests/replies; all forbidden SDK calls untouched; secret absence/corruption/
wrong-purpose/ACL/reparse/hardlink/plaintext; missing symbols/XAU, unknown/partial history, conflicting
records and overlap; IPC replay, correlation, crash, deadline, oversized frame, fresh recovery.
Ordinary PR12 code/test/lint failures are corrected in scope; no synthetic proof earns actual credit.
