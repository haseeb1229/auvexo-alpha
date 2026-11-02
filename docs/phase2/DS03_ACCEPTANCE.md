# DS-03 synthetic read-only foundation requirements

Status: FROZEN BEFORE IMPLEMENTATION; 2026-11-02; ADR-028; ENGINEERING_ONLY.
Actual DS-03 account/source/rights/history qualification remains OPEN.

| ID | Requirement and verification |
| --- | --- |
| D3-01 | Verified PR #10 merged base; one review PR OPEN/UNMERGED; Operational release/tasks/config/schedules unchanged, no genuine credit or catch-up. |
| D3-02 | Strict frozen version1 DTOs, unknown-field/type/duplicate-key/oversize/NaN denial, finite exact Decimal, canonical digests and UTC; generic malformed-response errors. |
| D3-03 | Fixed isolated synthetic child, inherited authenticated pipes, session/direction/ordered sequence/request correlation/release/config/expiry; replay and duplicate fail before effects; no arbitrary launch/file/module/method knobs. |
| D3-04 | Explicit read-only union; static/dynamic denial of order_send, order_check execution, trade request, modify/cancel and arbitrary methods; no SDK or execution adapter import/capability. |
| D3-05 | Independent expected DEMO/login digest/exact server/type/currency/leverage/terminal build/version/profile/process/release/config/rights/read-only provenance; REAL/CONTEST/UNKNOWN and mismatch refuse. |
| D3-06 | Fresh pre/post attestation; unknown account, server/login mismatch, absent read-only evidence, enabled trading, swap, stale/restarted terminal, process/profile drift close session. No config-only mode inference. |
| D3-07 | Fixed-purpose CurrentUser DPAPI, provider8–15 rule, fixed owner ACL/location, atomic lifecycle, bounded envelope/generic errors; missing/corrupt/wrong-purpose/leak tests; production inert, synthetic UUID test leaves only. |
| D3-08 | Exact symbol/suffix discovery; typed description/category/digits/point/tick size/value/profit/loss/contract/volumes/stops/freeze/trade/order/fill/margin/execution/currencies/sessions/spread/swaps/quote/history fields as available; explicit unknown; absent symbol, unsupported XAU, spec drift refuse. |
| D3-09 | Immutable typed bars/ticks/orders/positions/deals/history source facts and provider/product/account/server/mode/spec/release/rights lineage; unknown availability/coverage and gaps preserved, no fabricated complete history. |
| D3-10 | Provider vs first-seen/received/processed/available UTC times; monotonic progress, no refreshed first-seen/future leakage/time regression/conflicting duplicates; bounded ranges and explicit gap markers. |
| D3-11 | Exact synthetic rights hash/review/expiry; missing/mismatched/expired rights refuse; clock-blocked evidence STRUCTURAL_ONLY_CLOCK_BLOCKED earns zero source/time/Phase5 qualification. |
| D3-12 | Fixed limits64KiB/256requests/128symbols/256records/10s/attestation30s; one pending read; timeout/crash/broken pipe/restart invalidates session and partial output; clean disconnect and fresh-bootstrap recovery tests. |
| D3-13 | Official provider/package review date/URLs/version/hash/license/architecture/Python evidence and limits; SDK not adopted/installed/imported, no dependency/lock changes/unofficial wrapper/real session. |
| D3-14 | Accepted OI/PAPER behavior retained; tiny protected native reuse preserves slots/purposes/envelopes/paths/errors/platform/collector privilege boundary; inherited security proofs rerun. |
| D3-15 | Focused/inherited Python, applicable PG, Ruff/strict mypy/docs/equal agents/full source+history Gitleaks/high-signal/locked audit/exact committed fresh Windows clone/applicable frontend/actual hosted CI; no relaxed tests to pass. |
| D3-16 | Exact SHA/tree/PR/frozen hashes/evidence/residual gates handoff; independent executable review, PRIVATE return before accepted actual onboarding; no promotion/Phase5/money claims. |

## Macro section 22 traceability

| Adversarial case | Requirements |
| --- | --- |
| Malformed response | D3-02 |
| Unknown/REAL/server mismatch/login mismatch/absent read-only/account swap | D3-05/06 |
| Stale terminal/restart/crash/timeout | D3-06/12 |
| IPC replay/duplicate | D3-03/10 |
| Missing/corrupt/wrong-purpose secret/output leakage | D3-07 |
| Arbitrary method/order_send/order_check execution/modify/cancel | D3-04 |
| Absent symbol/suffix/spec drift/unsupported XAU | D3-08 |
| History gaps/time regression | D3-09/10 |
| Clock blocked/rights expiry | D3-11 |
| Process/profile drift/clean disconnect/recovery | D3-06/12 |

Synthetic evidence earns ZERO genuine dates, actual DS-03 qualification or Phase 5 credit.
