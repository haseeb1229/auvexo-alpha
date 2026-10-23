# Phase 7 read-only foundation acceptance requirements

Status: FROZEN before executable implementation, 2026-10-20. See [ADR025](../adr/025-read-only-private-operator-terminal.md)
and the [static-shell clarification](../reference/PHASE_7_STATIC_SHELL_CLARIFICATION.txt).
The [owner brief](../reference/PHASE_5_ACCEPTANCE_AND_PHASE_7_READ_ONLY_BRIEF.txt) remains authority.

| ID | Requirement and concrete proof |
| --- | --- |
| RO-01 | Separate development clone from verified PR7 normal merge; unchanged pinned runtime/task/config/activation; fixtures NON_COUNTING. |
| RO-02 | Strict version1 explicit presentation DTOs for system, qualification, PAPER, research and journal; schema tests and no raw domain/DB serialization. |
| RO-03 | Narrow application read ports and infrastructure fixed scoped SELECT-only adapters; isolated real-PG least-privilege/read-only/no-mutation proof; safe unavailability. |
| RO-04 | All data APIs bearer-protected, loopback peer/Host only, exact approved Origin policy, no public docs/OpenAPI; unauthorized and malformed auth/method negatives. Only approved data-free shell/assets may omit bearer; every /api/v1 endpoint remains protected. |
| RO-05 | No command/order/activation/kill/resume/gateway/SQL/file/withdrawal/transfer endpoints; no broker dependencies/credentials/network; inherited financial rules and execution-disabled guards unchanged. |
| RO-06 | Memory-only runtime diagnostics token; exact loopback Authorization header only; no URL/history/log/browser storage/static config/cache/worker; signout/unauthorized clears session. |
| RO-07 | Five read-only views: Command Center, Risk/PAPER, Research, Journal/evidence, System Health. Visible engineering/qualification/authority distinction. |
| RO-08 | Truth-preserving UNKNOWN/INCOMPLETE/BLOCKED/STALE/disconnect/loading/error; no empty-success account after DB failure; four INCONCLUSIVE/OOS consumed/no candidate; Phase4 OPEN; Phase5 commissioning NOT STARTED. |
| RO-09 | No exposed secrets/DSNs/paths/raw restricted archives/activation material; strict bounded safe fields, hash/reason-code timeline; redaction/injection/XSS negatives. |
| RO-10 | React/TypeScript-strict/Vite dark terminal; semantic labels, keyboard/focus/contrast/responsive/reduced-motion; component and accessibility verification. |
| RO-11 | Exact supported direct dependencies, committed npm lock, Node24.20.0, npm ci/build clean tree, third-party notices and transitive audit; high/critical finding stops review. |
| RO-12 | Security headers/no-store on data and safe errors, CSP/frame-ancestors/nosniff/no-referrer, no public listener/wildcard CORS/telemetry/CDN/service-worker cache. |
| RO-13 | Focused backend/schema/frontend/accessibility/security + affected isolated PG, full unskipped inherited Python, Ruff/mypy/TS/lint/build/docs/equal instructions/scans/locked audits and exact-final Windows clone. |
| RO-14 | One founder branch/PR OPEN/UNMERGED, exact-head push+PR jobs/logs PASS; no CI rerun hunting, force/history rewrite/settings changes, no weakened inherited gate. |
| RO-15 | Phase4/Phase2 clocks and source gates unchanged; no development calendar credit; PUBLIC October24/DS02 November16/DS03 blocked/private-return gates, no candidate/commissioning/money retained. |

No requirement changes canonical phases0-9, numeric gates or financial authority. Full Phase7
operational acceptance and Phase5 actual commissioning remain separate, unstarted dispositions.
