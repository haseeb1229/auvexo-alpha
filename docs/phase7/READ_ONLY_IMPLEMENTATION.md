# Read-only operator terminal implementation checkpoint

Status: read-only engineering foundation implemented and locally verified, NOT independently
accepted. Delivery requires exact-final Windows clone and exact-head hosted push/PR evidence
in the accompanying handoff. All development is in the separate clone. This
checkpoint does not claim full Phase7 acceptance, operational integration or money authority.
See [frozen ADR025](../adr/025-read-only-private-operator-terminal.md), [requirements](READ_ONLY_ACCEPTANCE.md),
[runbook](READ_ONLY_RUNBOOK.md) and the [explicit static-shell exception](../reference/PHASE_7_STATIC_SHELL_CLARIFICATION.txt).

## Presentation architecture

[Strict DTOs](../../src/auvexo_alpha/application/terminal_models.py) are bounded version1 presentation
contracts. [Application query ports](../../src/auvexo_alpha/application/terminal_reads.py) import no
infrastructure. [Routes](../../src/auvexo_alpha/api/terminal.py) assemble typed system, qualification,
PAPER, research and journal read models; they never query arbitrary tables. Local diagnostics
map actual configured mode, version/policy, API liveness and database readiness, separately from
source UNKNOWN, financial authority DISABLED/LOCKED and the reviewed synthetic gateway state.
The four reviewed research outcomes remain INCONCLUSIVE/OOS consumed/no candidate/champion.
This is a generic acceptance summary; raw experiments/alpha are not bundled or exposed.

Operational qualification/task/PAPER/journal integration defaults to explicit UNCONNECTED/
UNKNOWN. No fixture or development count can masquerade as genuine observation. Safe PAPER
balance/equity/positions/reservations/pending/kill/reconciliation projections are implemented in
[one query-only adapter](../../src/auvexo_alpha/infrastructure/terminal_paper.py), restricted to
isolated synthetic test namespaces and SELECT-only read identities. Fixed account scope,
repeatable-read/read-only transactions, privilege refusal, bounded lists and statement timeout
prevent arbitrary table selection or mutation. There is no operational observation-DB wiring.
Financial values are mapped from accepted snapshots/reservations, not recalculated. The adapter
normalizes journal timestamps to UTC and exposes only safe hashes/reason metadata. No raw rows,
account identity, payloads, DSNs, paths, activation secrets or archive downloads. Missing/failing
read state returns UNAVAILABLE with null values; it never returns a successful empty account.
No new schema/durable state, broker dependency, risk/store/truth change or permit authority.

## Local web and authentication

[FastAPI](../../src/auvexo_alpha/api/app.py) serves the generated production SPA same-origin.
Only data-free root/index and bounded allowlisted JS/CSS assets omit bearer, exactly as approved.
Every /api/v1 data route remains bearer-protected. Loopback peer and Host checks apply even to
static assets. Unknown/remote origins and query strings are denied. Dev-origin5173 is explicit
factory opt-in; preflight returns only CORS metadata for GET/Authorization, never data. No
credentialed/wildcard CORS or public listener. Public docs/OpenAPI remain disabled.
All responses receive no-store, nosniff, no-referrer, frame denial and strict self-only CSP.
Unexpected presentation failures emit only a stable redacted alert and safe unavailable response;
financial exceptions and accepted core behavior are untouched.

The [React client](../../web/operator-terminal/src/App.tsx) has five read-only views and no
financial controls. Its [runtime validator](../../web/operator-terminal/src/contracts.ts) rejects
unknown fields/versions/authority labels/malformed bounded financial strings/hashes/timestamps.
[HTTP reads](../../web/operator-terminal/src/client.ts) target only exact loopback, timeout after
five seconds, omit cookies, refuse redirects/cache and send bearer only in Authorization.
The owner supplies the token at runtime; memory-only state is cleared on signout/unauthorized.
Late responses cannot restore a cleared session. No URL/storage/config/log/worker token path.
Disconnect preserves retained data only with visible STALE/UNKNOWN; no current-data claim.

No external fonts/telemetry/CDN/chart/router/state framework. Dark desktop-first CSS has
responsive layouts, semantic tables/labels/landmarks, focus outlines, keyboard navigation,
skip link and reduced-motion rules. [Dependency/notice inventory](../../web/operator-terminal/THIRD_PARTY_NOTICES.md)
records exact direct/transitive versions/licenses and preserved packaged/upstream notices.
Node24.20.0/built-in npm11.19.0, exact direct versions and committed npm lock are required.
Generated node_modules/dist stay ignored. Scoped Git attributes force LF for frontend
TypeScript/TSX/CSS/HTML on Windows and Linux, matching the unchanged formatter. The first
exact-source Windows clone passed1661Python tests but exposed CRLF checkout lint failures;
its logs/source were retained, and the checkout policy was corrected in a forward commit
before a new exact-final clone. Docs QA now recognizes only the contained frontend
source extensions and rejects tracked generated dependencies/builds; inherited link/requirements/
ADR/phase/size/secret checks remain intact. Existing CI gates/actions/services/permissions/timeout
are unchanged; only this exact push branch and deterministic npm gates were added.

## Concrete tests and limits

[Backend/security tests](../../tests/test_terminal_api.py) cover auth on every read endpoint,
malformed auth, forbidden write methods/commands, strict DTO/schema fixture parity, unknown
operational truth, shell/asset isolation, query/OpenAPI denial, host/peer/origin spoofing,
opt-in exact dev CORS and redacted unexpected failures. [Real PG tests](../../tests/test_terminal_postgres.py)
prove SELECT-only identity, READ ONLY statements, unchanged account/journal, refused writes,
unsafe privileges/operational namespace denial, missing/stale/dependency failure and actual
accepted reservation/pending projection. All resources are isolated synthetic and cleaned.
[Frontend tests](../../web/operator-terminal/tests/terminal.test.tsx) cover strict contracts,
data-free startup, header-only token, no storage/log/URL leakage, loading/auth failure/disconnect,
late-response refusal, five views, four INCONCLUSIVE/no candidate and keyboard/axe semantics.

Focused checkpoint:101 backend/config/boundary/realPG tests passed;31 frontend tests passed.
Ruff/strict mypy70source files, TS typecheck/lint/build pass; initial npm audit150locked package
entries, zero reported vulnerabilities. The complete unskipped inherited Python suite also passed1661tests in495.96s on the
Windows development clone. These are engineering checks, not independent acceptance.
Axe under jsdom excludes color-contrast because jsdom cannot measure rendered contrast; this
is explicitly a semantic test, not complete WCAG certification. Real Chrome inspected data-free sign-in/invalid-token refusal, authenticated five-view
truth labels, keyboard-only sign-in/focus/sign-out, retained STALE state after disconnect and
responsive320/390px layouts without horizontal document overflow. Forty computed rendered
text color pairs had minimum contrast5.88:1; this bounded inspection is not full WCAG
certification. The preview used an ephemeral stdin-only synthetic credential, memory-only
browser entry, no DB/source, and was stopped with its session cleared. No operational UI session or broker/account/source qualification was attempted.
No new durable state needs migration/recovery; inherited recovery gates remain unchanged.

Release verification requires: full unskipped Python suite, current final statics/docs/equal instructions,
source/history scans and hash-required Python audit, npm ci/lock/type/lint/test/build/audit,
exact-final fresh Windows clone and exact-head push+PR jobs/logs. Keep the single new Phase7
PR OPEN/UNMERGED for GPT-5.6 Sol review. Do not count prior Phase5 clone/CI as Phase7 proof.
The protected-window checkpoint retained exact source/evidence hashes before heavy work;
verification resumed after23:20Pakistan without a partial runtime/DB mutation. Future heavy
work must still avoid the frozen protected operational windows.

Phase4 ACTIVE/fullOPEN pinned9b9038b; Phase2 operationalOPEN/seven dates; DS03BLOCKED;
PRIVATE selected/PUBLIC temporary exception October24 until verified owner return; DS02November16;
fourINCONCLUSIVE/no candidate; Phase5 commissioningNOTSTARTED/clock0/moneyDISABLED.
