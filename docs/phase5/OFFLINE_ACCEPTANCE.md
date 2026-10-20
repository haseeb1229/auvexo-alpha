# Phase 5 offline foundation requirements

Status: FROZEN before implementation, 2026-10-20; ADR-024; ENGINEERING_ONLY.

| ID | Requirement / concrete proof |
| --- | --- |
| OF-01 | Separate sibling clone; pinned runtime/task/activation unchanged; no development dates. |
| OF-02 | Strict version1 bounded JSON protocol with discriminated DTOs, canonical payload hashes, IDs, correlation/causation, source/account/mode/epoch, release/config/authorization/reservation and expiry binds; malformed/oversize/replay negatives. |
| OF-03 | Separate Windows-capable synthetic gateway process; authenticated inherited local pipes, no public listener/provider networking; safe bounded errors and redacted output. |
| OF-04 | Typed synthetic account/server/kind/currency/account-mode/capability attestation; DEMO/REAL mismatch, unknown identity and drift pause/refuse. Credentials alone confer no authority. |
| OF-05 | Inert offline DEMO permit design binds account/server/product/instrument/release/config/notional/risk/validity/revocation/commands; tampered/missing/expired/wrong-mode denies; no operational signer/issuer or live permit. |
| OF-06 | Thin port/adapter delegates unchanged accepted PAPER risk/reservation/claim/outbox/truth/reconcile/kill rules, all PAPER_NONEXTERNAL; no new financial state machine. |
| OF-07 | Durable claim precedes fake send; timeout/crash/duplicate/restart reconcile first, never blind resend; no exactly-once broker claim. |
| OF-08 | Synthetic reject/late/partial/cancel-fill/external-trade/mismatch/stale-writer/reconnect/restart matrix with authoritative facts and retained capacity. |
| OF-09 | Narrow future transport connect/attest/spec/submit/cancel/query/health shape; fake-only registry, no SDK/terminal/provider/broker credentials, no withdrawal/transfer capability. |
| OF-10 | Offline operations startup/attestation/reconcile-only/disconnect/UNKNOWN/restart/manual mismatch/failed protection/kill/revocation/shutdown; all synthetic, no Exness evidence. |
| OF-11 | Focused/property/PG/inherited full tests, statics/docs/equal instructions, source/history/redacted scans, hash-locked audit, recovery/restart and exact-final Windows clone/hosted CI logs. |
| OF-12 | Phase4 ACTIVE/full OPEN; Phase5 commissioning NOT STARTED; Phase2 full OPEN/DS03 BLOCKED; no alpha/promotion/money; PUBLIC Oct24 and DS02 Nov16 gates retained. |

These requirements do not enable DEMO/REAL account execution or start sustained-demo
qualification. Existing PAPER fixture contracts stay PAPER-only. No raw/owner/broker data
may enter public history; no new dependency is justified or introduced by this scope.
