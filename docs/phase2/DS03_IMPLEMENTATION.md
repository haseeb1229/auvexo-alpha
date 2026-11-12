# DS-03 synthetic read-only implementation

## CURRENT IMPLEMENTATION STATUS — 2026-11-03

PR11 is verified NORMAL MERGED at `fa0915130c9572c9c2a4a260b20abeaefc2c62f5`, following
all-step passing administrative CI41516596112 at f9a8609. Original DS03/OI design freezes
remain unchanged. ADR029/actual requirements/provider/runbook froze BEFORE code at
`aa1c5f4b4f003b660bd1a584647e62093894bb6c`. Actual MT5 read-only CODE, Windows-only pinned
SDK/NumPy, fixed native DPAPI/metadata/authority and isolated provider child are implemented
on `phase-2/ds03-mt5-readonly-adapter`; fresh independent executable review remains pending.
See `docs/phase2/DS03_ACTUAL_ADAPTER_IMPLEMENTATION.md` (repository-root path). Keep new PR
OPEN/UNMERGED. No actual SDK initialize/login/session, production credential API or broker
account data in public verification. SDK import-only and synthetic/native proofs confer no
actual qualification or trading authority. All existing operational, PRIVATE-onboarding,
OI clock/START, phase/value/live and money gates below remain unchanged.

## CURRENT STATUS SUPERSESSION — 2026-11-03

The latest owner-supplied macro records GPT-5.6 Sol's fresh independent acceptance of
`ba66f44fd38c761821913f5b9ef6c7dcf485ed2a`, tree
`d57091a9a488744b1050d652d876f94253b11656`:
PHASE2_DS03_SYNTHETIC_READONLY_ENGINEERING_ACCEPTED_PASS. See the acceptance record
at `docs/reviews/PHASE_2_DS03_SYNTHETIC_READONLY_INDEPENDENT_ACCEPTANCE.md` (repository-root
path). This accepts generic/synthetic engineering only. Actual DS-03 account/source/rights/
terminal/history qualification, Phase 2 exit, Phase 4 closure and Phase 5 commissioning
remain OPEN or NOT STARTED as applicable; synthetic evidence earns ZERO genuine credit.

PR #10 normal merge remains verified at `f47770d7886d12240e24390e23f939cb49535a31`.
The owner authorizes a docs-only administrative child on PR #11, actual green public CI,
then NORMAL merge with ordered parents that prior main and exact administrative head,
and equal merge/head trees. Retain frozen ADR-028/DS03 design/provider/runbook bytes and
all five frozen OI research files. No executable/test/dependency/workflow/migration change
in that acceptance step. Do not request another review merely to accept exact ba66.

After verified PR #11 merge only, create `phase-2/ds03-mt5-readonly-adapter`, freeze
ADR-029/actual-adapter requirements/provider review/runbook BEFORE code, and implement
production-capable read-only adapter CODE, fixed production DPAPI/local metadata and
onboarding-authority contracts. Exact official MetaTrader5 5.0.6231 Windows-only package
adoption/import-only proof is authorized; it is not a read-only security boundary.
No actual initialize/login/terminal session, account input, real secret storage or broker
data in this public engineering. Every future initialize requires explicit fixed terminal,
login/read-only password/server/timeout/portable choice; no discovery/account fallback or
trade operation. The new PR stays OPEN/UNMERGED for fresh exact-SHA independent review.

ADR-027 temporary PUBLIC governance continues through sanitized adapter engineering and
free CI. No new machine identifiers, real secrets/private broker data/confidential alpha;
source/history scans before every public push. No settings, billing, runner, permission,
visibility or branch-protection changes. Existing historical metadata retention remains
owner-authorized. PRIVATE return is required only before later actual account/session/
credential onboarding after PR12 acceptance and separate authority; do not ask earlier.
LIVE_RELEASE_INTEGRITY_CONTROL_REQUIRED_BEFORE_PHASE8 remains a future gate.

Operational release/tasks remain pinned to `9b9038b6966843805c99f15e1c37cdba7c026679`
and untouched; current Phase 2 genuine credit and Phase 4 count/span/replay/mismatch UNKNOWN,
not ZERO. Independent OI Runtime stays prepared/pinned to f47770d with Python3.13.16 and
PG17.11; no update, real OI DB/secrets/config/task/START. CLOCK_EXTERNAL_BLOCKED and
PHASE6_FORWARD_CLOCK=ZERO; no deep clock loop, at most one fresh read-only status.
Clock failure does not block this safe engineering. Protect20:45–22:15 and22:45–23:20 PKT.
Four Phase 3 outcomes INCONCLUSIVE, both OOS permanently consumed, no candidate/champion;
OI-FWD-v1/OI-16 unchanged and value gate OPEN. No actual Phase5 orders before full Phase4,
accepted actual DS03 and explicit authority. No REAL/money/live/runtime-AI authority.
Earlier dated sections retain historical facts and are superseded only for current scope.

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
