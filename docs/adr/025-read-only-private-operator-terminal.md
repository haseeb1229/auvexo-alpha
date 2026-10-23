# ADR-025: read-only private operator terminal foundation

Status: FROZEN before executable implementation, 2026-10-20; independent review pending.
Requirements: R-003, R-006, R-018, R-019, R-022, R-023, R-024, R-025, R-027, R-029, R-031, R-035.

## Context

The [owner brief](../reference/PHASE_5_ACCEPTANCE_AND_PHASE_7_READ_ONLY_BRIEF.txt) records independent
Phase 5 offline acceptance at 82601fa80a711ce3de66b4b8289ac0f9b679b298. PR7 normal merge is verified
at 1d6b08fc36884f1bc4845ac54111776d80df056b, ordered parents 9b9038b then administrative1425417.
ADR013 permits scoped non-money surfaces while operational qualification continues. ADR024's
operational/development separation remains mandatory. Phase 7 foundation is engineering-only;
actual Phase 5 commissioning and full Phase 7 operational acceptance remain closed.

## Decision

Frozen engineering scope only, with the narrow owner-approved static-shell exception below.

Use one contained React/TypeScript-strict/Vite application at web/operator-terminal and the
existing loopback FastAPI process. Versioned explicit presentation DTOs and narrow application
query ports separate clients from domain/storage. Browser imports no Python/domain/risk code.
Backend read models map allowlisted fields; they never expose raw rows, DSNs, paths, secrets,
activation material, broker account IDs or restricted archives. All data endpoints require the
existing random bearer token with constant-time comparison and no public docs/OpenAPI endpoint.
No cookie/session expansion, public signup, generic command, policy activation, order, kill,
resume, gateway dispatch, transfer or withdrawal route. execution_enabled remains false.

Five read areas: Command Center, Risk/PAPER, Research, Journal/evidence and System Health.
Engineering state, operational qualification and financial authority remain separate. Research
records four reviewed INCONCLUSIVE outcomes, consumed OOS and no candidate/champion; no raw
research results or alpha. Qualification counts/freshness are UNKNOWN when not connected to
an authorized read projection. No static engineering acceptance can imply operational readiness.

Default operational projections are unavailable, explicitly UNKNOWN/INCOMPLETE. Test fixtures
use only isolated resources. No development test connection to the pinned observation database,
no task or activation integration; actual runtime integration needs separate owner authority.
PAPER adapters accept only fixed account scope and fixed named queries; explicit database read-only
transactions, bounded results/timeouts and least-privilege query identities, with no schema change.
No PaperStore command or duplicated risk calculation in the presentation path. Permission or
schema/database failures produce safe unavailable read models, never empty-success portfolios.

The UI stores the owner diagnostics bearer token in memory only. It is sent solely in the
Authorization header to the exact 127.0.0.1 API origin, never URL/log/storage/static config/cache.
Sign-out/unmount clears token and all retained data; unauthorized responses clear the session.
Network failure preserves any retained snapshot only with visible STALE/disconnected state.
Source timestamps, provenance and UNKNOWN states remain explicit. No telemetry/CDN/fonts/
service worker or persistent offline cache. UI adds presentation only, no financial decision logic.

Use pinned Node24.20.0 and built-in npm/package-lock.json. Exact direct versions from authoritative
registry metadata; justify dependencies and retain full third-party license notices. React19.3.1/
ReactDOM19.3.1, Vite8.3.4, TypeScript7.0.2, Vitest5.0.5, jsdom30.1.3, TestingLibraryReact16.3.3,
user-event14.6.8, axe-core4.14.0, Biome2.5.15 and matching React types19.3.0 plus Node24 types24.19.2 are selected. No Next.js, charting, router, state-query framework,
CSS framework or component library is justified for these five local views. Registry adoption,
lock integrity, supported engines, transitive licenses and vulnerabilities must pass before use.

## Owner-approved browser bootstrap

The [explicit owner clarification](../reference/PHASE_7_STATIC_SHELL_CLARIFICATION.txt) permits
only the loopback SPA shell and allowlisted HTML/CSS/JS assets without bearer authentication.
They contain no operational data, secrets, tokens, credentials, runtime status or sensitive
configuration. Every /api/v1 endpoint retains bearer protection without exception. No URL,
cookie/session, browser-storage, service-worker, source-file or log token persistence.
The token is entered at runtime, held in memory and sent only in Authorization to exact API.
No public listener or wildcard CORS. Static routes cannot select arbitrary files or fall through
to API data. Production build is served same-origin by FastAPI; no runtime data is baked into it.

## Validation

FastAPI binds127.0.0.1. Deny nonloopback peer/Host/proxy spoofing and remote Origin. Dev Vite binds
exact127.0.0.1 fixed strict5173, API8765; only exact dev-origin allowlist if enabled, never wildcard.
Canonical production is same-origin where the approved bootstrap permits it. Apply no-store,
CSP default-src self/connect-src exact loopback/frame-ancestors none, nosniff and no-referrer to
success/error responses. XSS-safe React text, no arbitrary HTML, file/table selectors or raw errors.

Verify every data route auth/malformed-auth/method negatives, bounded strict DTOs, redaction,
stale/unknown/incomplete and safe dependency-failure mapping; isolated PostgreSQL SELECT-only
adapter proof, import direction, no broker dependencies and no hidden mutations. Frontend checks
cover loading/error/disconnect/unauthorized, keyboard/focus/responsive/reduced-motion, labels,
XSS/injection and token leakage/storage negatives. Run full inherited Python, strict types/lint,
frontend npm ci/type/lint/component/accessibility/build/audit, docs, equal instructions, redacted
source/history scans, Python hash-required audit, diff and exact-final Windows clone before PR.
CI may add only this branch and deterministic frontend gates; inherited gates/actions/permissions/
timeout/services remain unchanged. No benchmark or MT5/broker test.

## Operational and governance constraints

Active runtime stays9b9038b, original task/config/activation untouched. Phase4 ACTIVE/full OPEN,
>=14 genuine dates AND span>=14 calendar days/replay/zero unexplained mismatch unchanged.
Phase2 full OPEN/seven genuine dates and DS03 BLOCKED; fixtures never count. Phase4 protected
window20:45-22:15Pakistan on/afterOctober21; Phase2 window22:45-23:20 daily. Tonight stop before
any long heavy step that cannot finish by22:45; record PROTECTED_WINDOW_PENDING safely.
PUBLIC temporary exception dueOctober24 remains active until independently verified owner
PRIVATE return. PRIVATE is selected long-term; no settings changes or permanent-public ADR.
DS02 review dueNovember16. No broker SDK/session/credentials/DS03/proprietary alpha work.
No candidate/champion, runtime AI, paid service, money authority or Phase5 commissioning.

## Alternatives

Unauthenticated operational APIs, URL tokens, browser persistent credentials, CORS wildcards or
unreviewed cookies/sessions violate scope and are rejected. A data-free local sign-in shell
uses the explicit narrow owner exception; a separate launcher is unnecessary for this scope. React/Vite remains frozen client direction;
Next.js/extra chart/state frameworks and duplicated risk logic are unnecessary for this scope.

## Consequences

Engineering visibility grants no financial authority or qualification date. Unconnected views
stay UNKNOWN and fixtures stay NON_COUNTING. Frozen design must precede executable adoption;
the owner bootstrap clarification resolves freeze without granting data access or money authority.
The active campaign release and prior frozen file bytes remain untouched.

## Review point

This ADR/acceptance/runbook are frozen before implementation. Exact-final source, receipts and OPEN/UNMERGED single Phase7 PR
require GPT-5.6 Sol independent review. This prompt authorizes no Phase7 merge or commissioning.
