# DS-03 synthetic read-only implementation

Status: ENGINEERING_ONLY implementation; independent exact-SHA acceptance pending.
Authority: owner macro dated 2026-11-02; PR #10 verified normal merge at
f47770d7886d12240e24390e23f939cb49535a31. Design/requirements/runbook/provider review
were frozen before code in commit66af7b683b9140bd91826f5faab5296b13403914.

## Implemented boundary

| Concern | Source / behavior |
| --- | --- |
| Strict DTOs | domain/ds03.py: immutable request/reply union, exact boolean/Decimal/integer validation, UTC/digest/source/spec bindings, explicit unknown coverage and gaps |
| Application | application/ds03.py and ds03_ports.py: fresh pre/post DEMO/read-only identity, rights and remaining monotonic lifetime, discovered-symbol/spec checks, immutable facts/first-seen and replay/time/coverage denial |
| Synthetic terminal | infrastructure/ds03_fake.py: two explicitly synthetic suffixed symbols; no assumed actual broker availability, provider networking or SDK |
| IPC/process | infrastructure/ds03_ipc.py and ds03_process.py: fixed isolated installed-package child, inherited anonymous pipes, ephemeral authentication, source/interpreter binding, bounded frames/sequences/requests/deadlines, redacted failure and fresh-bootstrap recovery |
| Outer tool | tools/ds03_connector.py: no provider/account/credential/backend/path arguments; emits only a fixed synthetic success/error code |
| Secrets | infrastructure/ds03_secrets.py: fixed CurrentUser DPAPI purpose/UUID test leaf/provider syntax; production operations inert until separately accepted onboarding; no general vault |
| Native reuse | oi_secrets.py adds only protected _DPAPI._purpose() and calls it; unchanged OI return value/slots/envelope/path/error behavior; fixed DS-03 subclass overrides its own purpose and reuses inherited file/ACL/atomic mechanics |

No SDK dependency/import, terminal launch, actual account/session/credential or money path.
The candidate wheel was downloaded for metadata/license/hash inspection only, not installed.
Read-only observed order/position/deal facts expose no execution capability. Each such fact
requires the exact previously discovered symbol-spec hash; a batch never inherits an
unproven spec. Synthetic release/identity labels are fixtures. The process source/interpreter
handshake binds actual bytes for engineering proof; fixtures confer no actual release authority.

A request may cover at most366days, with bounded records and caller batching. This is an
IPC/request resource bound, never a fixed research-history lookback or aggregate history cap.
Availability remains first-seen causal; repeated/conflicting facts cannot silently refresh
first acquisition. Bars require explicit interval and closed-bar/cadence/gap consistency;
finite tick samples cannot claim complete interval coverage. Unknown sessions/history stay
unknown. All current synthetic envelopes are STRUCTURAL_ONLY_CLOCK_BLOCKED.

## Verification and review

[D3 requirements](DS03_ACCEPTANCE.md) trace the adversarial matrix; frozen
[runbook](DS03_RUNBOOK.md), [ADR-028](../adr/028-ds03-synthetic-readonly-foundation.md) and
[provider/package review](DS03_PROVIDER_REVIEW.md) retain original bytes.
Tests cover strict malformed input, REAL/unknown/mismatched/missing evidence, swaps,
rights/clock/expiry, process/profile/spec drift, future/duplicate/regressing/gapped data,
IPC authentication/replay/correlation/limits, crash/timeout/clean recovery, fixed-purpose
secret failures/atomicity and static/dynamic denial of all requested trade operations.
Exact committed verification counts/logs, scans, audits, fresh clone and hosted CI are
reported in the local-only consolidated handoff and PR review evidence; no fixture result
is actual source qualification. Earlier failed draft checks remain retained as failures.

The PR remains OPEN/UNMERGED for fresh independent exact-SHA review. PUBLIC sanitized
engineering does not authorize actual onboarding. PRIVATE return and separately accepted
actual account/source/spec/history/rights/security onboarding remain required. No Phase 5
actual orders before full Phase 4 closure, accepted actual DS-03 and explicit authority.
Operational release/tasks/config/activation/schedules remain untouched; genuine Phase2/4
credit remains UNKNOWN unless independently proven. PHASE6_FORWARD_CLOCK remains ZERO;
no OI commissioning/START, promotion, consumed OOS reuse or money authority is granted.
