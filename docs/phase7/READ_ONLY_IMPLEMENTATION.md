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


## Independent review correction: actual read identity

Review of source260f0ce found that the synthetic PAPER adapter checked its configured
DSN and too narrow a privilege set; that did not prove the identity of an acquired
PostgreSQL session or the absence of additional application reads and writes. The
reviewed source, dirty correction, failed audit and recovery inventories are retained
locally. The frozen ADR025, acceptance requirements, runbook and shell exception remain
unchanged. This correction does not wire the operator terminal to the campaign.

Each connection acquisition now checks one coherent catalog snapshot before any
projection query: session_user and current_user must both equal the expected dedicated
LOGIN, actual database and server address/port must match the isolated configuration,
and UTC, repeatable-read, read-only and public-only search path must hold. URL overrides,
unsupported drivers, missing credentials and engine execution overrides are refused.
The login must have no elevated role attributes, inheritance, memberships, ownership,
schema CREATE or database CREATE/TEMP capability. All application relations are checked:
only the four required public PAPER tables may have SELECT, all four must have it,
and additional table/column reads, mutations, grant options, sequence privileges and
executable application security-definer functions are refused. Projection SQL explicitly
qualifies public tables. Every acquisition rechecks; no cached verdict survives pool
reuse, privilege changes or reconnect. Refusal returns the existing safe UNAVAILABLE
shape before any projection SQL and exposes no database details.

Fifty additional real-PostgreSQL tests exercise actual session/admin/SET ROLE deception,
wrong databases despite a plausible engine URL, role flags, memberships, missing SELECT,
extra table/column/view/materialized-view/PUBLIC reads, writes, schema/object ownership,
sequence privileges, UTC/search-path drift, pool reuse, rollback and reconnect. Existing
good-path projections and no-mutation checks remain. Focused verification passed151 tests
(58 real-PG,59 API/security,34 configuration/boundary); the inherited full suite passed1711
without skips before the security dependency update, then passed1711 again with the fixed
certifi environment. Final release verification still requires a new exact-commit clone
and corrected exact-head hosted CI; prior-head evidence cannot satisfy those gates.

The required hash-verified audit then reported certifi2026.7.22 affected by
[GHSA-6q48-6c7w-9gw2](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2).
Publication stopped. The owner explicitly authorized a certifi-only security resume:
update only certifi and its lock hashes, preserve the failure, and rerun the required
gates without weakening them. No other dependency or operational authority is included.
The corrected lock installs certifi2026.10.19; all other locked values are identical.
The repeated hash-required Python audit checks69dependencies with zero vulnerabilities;
the repeated frontend audit also reports zero. Official PyPI artifact hashes were verified.

A prepublication check identified a separate authority conflict: the strict actual server
loopback/port attestation required by the correction brief is incompatible with the inherited
hosted PostgreSQL service's bridged55432:5432 topology. On2026-10-22 the owner explicitly
approved the prepared CI-only resume, superseding only ADR025's inherited CI-service clause.
The original frozen documents remain byte-identical. The workflow now runs the same pinned
PostgreSQL17.11 image with host networking and PostgreSQL bound only to127.0.0.1:55432,
with bounded readiness and always-run cleanup. All existing tests, pinned actions, permissions,
runner and timeouts remain unchanged. The strict server attestation remains intact.

Local verification passed1711Python tests,31frontend tests, statics/docs/scans and zero-vulnerability
audits after the certifi-only update. The corrected committed source still requires its own
hosted push/PR jobs and fresh Windows clone; prior-head results are not release evidence.
PR8 remains OPEN/UNMERGED for independent review; Phase5 commissioning and Phase6 remain
NOT STARTED. The protected operational windows govern remaining local heavy verification.


The first corrected hosted runs at6df5634 exposed a CI authentication regression: both
reported2failed/1709passed because inherited wrong-password rejection tests did not raise.
The loopback topology selected initdb's default trust host rules. Both failed runs/logs and
the stopped commit are preserved; temporary containers were removed. On2026-10-22 the
owner explicitly authorized the prepared CI SCRAM security resume. The one-line fix sets
POSTGRES_INITDB_ARGS=--auth-host=scram-sha-256, initializing host rules with SCRAM while
retaining the pinned image, endpoint, cleanup and every test. No assertions or inherited
security gates are weakened; a new forward commit requires fresh hosted events and final
Windows clone verification. The old failed CI events must never be reported as passing.
