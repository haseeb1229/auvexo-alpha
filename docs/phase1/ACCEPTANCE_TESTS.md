# Phase 1 child requirements and acceptance tests

Authorized by the supplied Phase 1 prompt after normal Phase 0 PR #1 merge.
These stable child IDs refine existing parents before implementation. They do not certify
future risk, execution or live trading. Original R-000..R-039 remain unchanged.

| ID | Current-phase invariant | Executable proof |
| --- | --- | --- |
| R-003-P1-01 | Parse seven modes; none enables execution | Parameterized all-mode refusal tests; config elevation rejects |
| R-004-P1-01 | Binance live derivatives explicitly BLOCKED_BY_POLICY | Versioned policy and direct disabled-port test |
| R-022-P1-01 | No executable order route, broker SDK or successful fill | Import/dependency scan; arbitrary order endpoint 404; all money actions denied |
| R-022-P1-02 | Missing permit, wrong account, unsupported instrument, malicious payload cannot grant capability | Port/config/API negative tests; no permit issuer |
| R-022-P1-03 | Repeated command ID never changes denial or creates execution | Duplicate-call test; no risk authorization implementation |
| R-014-P1-01 | Financial values reject floats, nonfinite/oversized/malformed decimals and invalid units | Unit/Hypothesis tests; precision and canonical hash cases |
| R-014-P1-02 | Timestamps aware UTC; availability and expiry chronology validated | Naive/non-UTC/future-availability/expired envelope negatives |
| R-019-P1-01 | Domain/application have no inward dependency on API/storage/broker | AST import-boundary tests and schema snapshot check |
| R-023-P1-01 | Loopback-only authenticated diagnostics; no public bind or leaked secrets | API wrong/missing auth, host/origin/client-IP and bind negatives; sanitized error tests |
| R-023-P1-02 | Configuration refuses account credentials, execution and policy elevation | Unknown environment/config keys and prohibited fields tested |
| R-025-P1-01 | Reproducible supported locked dependency install | Windows clean clone; frozen sync; Ruff/mypy/tests; lock and advisory scan |
| R-025-P1-02 | Real PostgreSQL constraints, rollback and append-only metadata | Real DB integration negatives; migration clean-upgrade and restore comparison |
| R-027-P1-01 | Readiness reflects real DB schema/policy health; bounded safe diagnostics | DB-unavailable/schema-drift/policy checks; structured sanitized diagnostics |
| R-024-P1-01 | Actual foundation footprint is measured separately from future trading budgets | Windows process idle RAM/CPU/startup/disk evidence |
| R-031-P1-01 | Accepted Phase 0 merged normally; Phase 1 unmerged PR with CI | GitHub PR/ref/check-run evidence, owner identity and secret scan |

Implementation test files are mapped in [inventory](IMPLEMENTATION.md), with actual results
and the CI proof blocker in [verification](VERIFICATION.md). Full broker risk/reservations/
dispatch stay assigned to Phases 4/5.
