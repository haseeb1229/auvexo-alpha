# Phase 4 Checkpoint A frozen child requirements

Frozen before executable implementation on 2026-10-18. Engineering checkpoint inside
canonical Phase 4, not full Phase 4 acceptance. Owner-authorized scope is generic,
CPU-only, zero-cost virtual PAPER core. Changes to these criteria require an explicit
documented amendment; tests cannot tune limits or waive failures. ADR-015 resolves
the separate fixture registry; inherited requirements and denials remain mandatory.

Amendment dated 2026-10-20: owner-authorized [ADR-022](../adr/022-paper-performance-slo.md)
clarifies only R-024-P4-01's percentile and research-throttle semantics before
qualification. The original 2026-10-18 freeze remains historical; its exact
[original bytes](../reference/PHASE_4_ACCEPTANCE_TESTS_ORIGINAL_20261018.txt) have SHA256
051da385ebc22f1c5eb98933c876a2338b7e4005f23913e8ffd0ffa070cf1d1a.
Prior hard-MAX failures and stop receipts remain valid evidence under the superseded
interpretation. No benchmark rerun, numeric P95 increase or safety waiver is authorized.

| Child ID | Parents | Required positive and adversarial evidence |
| --- | --- | --- |
| R-002-P4-01 | R-002, R-003, R-004, R-022-A/D/F | Immutable strict proposal/intent, virtual PAPER identity, canonical hashes; exact decimal/time/mode/account/spec/policy/release bindings; arbitrary payload, float/bool/NaN/Inf/expiry/alteration denied; no external transport or live issuer |
| R-022-P4-01 | R-022-A/E | Pure deterministic loss/exposure; linear quantity * multiplier * abs(entry-stop) * adverse FX + versioned costs/gap; DOWN quantization then minimum/step validation; long SPOT only; unavailable FX/session/DST/freshness and unsupported semantics fail closed; hand calculations and numeric properties |
| R-022-P4-02 | R-022-B | All positions and pending reservations count toward trade/asset/bucket/aggregate/gross/net/position/balance/margin/rate/daily-loss/drawdown caps; strictest wins; zero/lower limits and tiny balances; no recovery sizing; UTC day and observed flows never reset loss history or suspension |
| R-022-P4-03 | R-022-A/B, R-021 | Real PostgreSQL account lock, atomic intent/authorization/reservation/outbox, account+logical action uniqueness; independent threaded/process races cannot oversubscribe or duplicate; amend requires new authorization |
| R-021-P4-01 | R-021, R-022-C/G | Durable fenced dispatch attempt before simulated boundary; SENT_PENDING/ACKNOWLEDGED/REJECTED/UNKNOWN/PARTIALLY_FILLED/FILLED/CANCELED/EXPIRED; lost result/crash/duplicate/out-of-order/partial/cancel-fill/late-terminal injection; UNKNOWN holds worst-case capacity and cannot resend |
| R-021-P4-02 | R-021, R-022-C/E | Independent authoritative virtual truth ledger and local attempt journal; startup reconciliation-only/pause-new, overlapping history/open orders/positions, external facts, append corrections, mismatch quarantine; release only proven terminal residual; partial actual plus residual capacity preserved |
| R-006-P4-01 | R-006, R-003/004 | Append-only RESEARCH->CANDIDATE->VALIDATED->PAPER->SHADOW->LIVE_LIMITED->LIVE plus SUSPENDED/RETIRED history; exact provenance/modes/approvals/time; no agent promotion or auto-resume; production registry starts with no champion and admits no INCONCLUSIVE Phase 3 result |
| R-006-P4-02 | R-006, R-025 | Separate TEST_ONLY/PAPER_QUALIFICATION_FIXTURE registry, ENGINEERING_ONLY evidence and PAPER-only; impossible promotion/SHADOW/DEMO/LIVE; fixed proposals never enter research ledger or claim alpha |
| R-022-P4-04 | R-022-E/G | K0 NORMAL/K1 PAUSE_NEW/K2 CANCEL_PENDING/K3 CONTROLLED_FLATTEN/K4 LOCKDOWN persisted; typed fresh known position-bound reductions/cancels, no bypass/over-close/reversal; stale/unknown/journal-corrupt changes blocked; explicit audited owner PAPER resume only |
| R-008-P4-01 | R-008, R-007, R-027 | NORMAL/WATCH/REDUCE/SUSPEND/INVESTIGATE state plumbing with versioned TEST evidence, no invented alpha thresholds; hard caps dominate; every otherwise-valid denied fixture proposal records intent/evidence/time/ordered reasons/versions; isolated forward outcome only if observed, never overlapping-profit aggregation |
| R-023-P4-01 | R-023, R-025/026/029, R-022-G | Forward migration after 0004, no merged edits; least privilege runtime/truth roles cannot mutate immutable histories, foundation/research, schema or grants; idempotence/constraint/privilege/corruption/DB/disk/epoch failures; isolated backup/restore hashes/totals/triggers/crash/UNKNOWN; downgrade refused; same-disk DEV only |
| R-024-P4-01 | R-015, R-024/027 | ADR-022 amendment 2026-10-20: bounded queues/backpressure, SYNTHETIC three-instrument representative load and 5x burst, research concurrent then throttled; retain actual counts/p50/p95/p99/MAX/CPU/RAM/disk without outlier filtering; kernel p95<=10ms/p99<=25ms and indexed query p95<=50ms/p99<=200ms in both phases; qualified/throttled primary and every admitted transaction wave p95<=100ms/p99<=250ms; concurrent transaction p95>100ms or p99>250ms is THROTTLE_REQUIRED stress evidence, qualification requires subsequent throttled PASS; MAX always reported/investigated, a single >100ms sample alone is not failure; fixed samples/queue/admissions/drain unchanged, missing metrics or queue/drain failure FAIL; no correctness/security/atomicity weakening |
| R-025-P4-01 | R-025/026/031/032/035 | Ruff/strict mypy/full unskipped pytest/docs/links/requirements/equal instruction bytes/inherited denials, real PG/races/recovery/security, source/history redacted scans, hash-locked audit, diff, exact-final Windows clone and push/PR CI; founder commits and one unmerged Phase 4 PR |

The versioned provisional PAPER policy freezes risk <=0.25% equity per intent,
aggregate <=1%, BTC+ETH bucket <=0.5%, daily marked loss <=1%, drawdown <=5%,
positions <=3, gross/net <=1x equity, margin <=20%, new intents <=5/minute.
Per-asset <=0.5% is an additional conservative engineering bound. Fees/slippage/gap,
freshness, queue limits and specification steps must be explicit in versioned fixtures.
No live defaults exist; the foundation disabled policy remains unchanged.

No persistent Phase 4 task, 14-day counter, real-environment PAPER day, Phase 5,
broker SDK/account/credential/order or money capability. Preserve Phase 2 daily task;
no heavy DB/migration/benchmark work 22:45-23:20 Pakistan. Public exception review
due 2026-10-24. Request GPT-5.6 Sol exact-final-SHA review before merge/observation.
