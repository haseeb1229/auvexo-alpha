# Decision and external gate register

All statuses have an owner and decision point. Owner labels refer to future accountable
roles, not additional people appointed in Phase 0. No ordinary engineering choice is sent
to the founder merely to avoid making a decision.

| ID | Status | Decision / current safe default | Owner | Closure evidence / deadline |
| --- | --- | --- | --- | --- |
| OD-01 | PROVISIONAL | Python/FastAPI/Pydantic/PostgreSQL/quant toolchain versions unpinned | Phase 1 implementer | Supported official release matrix, Windows wheels incl. MT5 compatibility, lockfiles, clean install/test; Phase 1 exit |
| OD-02 | PROVISIONAL | Python-first MT5 gateway, EA/hybrid deferred | Execution maintainer | Real demo disconnect/latency/recovery matrix; decide before Phase 5 exit |
| OD-03 | EXTERNAL | Exness actual demo symbols/contracts/terms/history unverified; no account connected | Owner provides demo authentication, maintainer verifies | Read-only demo attestation/spec snapshot/source rights; Phase 2; execution permission Phase 5 |
| OD-04 | EXTERNAL | Live capital and all live numerical limits unset; current allocation zero | Founder | Signed absolute/percentage capital/loss/leverage policy; before Phase 8 activation |
| OD-05 | EXTERNAL | Instrument/venue financial/religious/jurisdiction eligibility | Founder with chosen qualified advice | Dated evidence and explicit policy decision; before any affected live eligibility; Binance live derivatives stay blocked until separate review |
| OD-06 | EXTERNAL | Off-device encrypted backup and reliable runtime/owner-response plan not proven | Owner + operations maintainer | Recovery medium/key access, restore/uptime/incident drills; before Phase 8 |
| OD-07 | PROVISIONAL | WebAuthn implementation, permit signing and OS secret-store integration | Security maintainer | Maintained library choice/auth negatives in Phase 1; client step-up Phase 7; independent review Phase 8 |
| OD-08 | PROVISIONAL | RAM/disk/latency budgets are estimates | Platform maintainer | Hardware measurements Phase 1/2, concurrent load and failure proof Phase 5 |
| OD-09 | DEFERRED | Redis/NATS/Timescale not installed | Platform maintainer | Revisit Phase 6 capacity review or measured persistent bottleneck; ADR and migration/rollback proof |
| OD-10 | DEFERRED | Premium sources, paid LLMs, local heavy models, richer on-chain/ETF data disabled | Research maintainer + owner for spending | Paired value experiment and rights/footprint review before Phase 6+ adoption; explicit purchase authorization |
| OD-11 | DEFERRED | Tauri/Expo/voice and final chart/UI library versions | Client maintainer | Phase 7 contract/security/accessibility and license review |
| OD-12 | DEFERRED | Full Binance account/execution adapter; Bybit/OKX execution out of scope | Execution maintainer | Explicit later scoped phase, capability/contract tests and eligibility; cannot inherit Exness permit |
| OD-13 | DEFERRED | External engines/libraries for reuse not adopted | Implementer | Exact revision license/NOTICE/dependency/security scan before import/copy/sidecar installation; Phase 3 or later |
| OD-14 | EXTERNAL | Independent Phase 0 review pending | Founder supplies handoff to reviewer | Reviewer disposition on final SHA, critical findings closed and explicit Phase 1 prompt; before Phase 1 |
| OD-15 | PROVISIONAL | Alpha sample/threshold and edge-decay study settings | Research maintainer | Preregister before looking at held-out data in Phase 3; never relax after results |

Frozen decisions are catalogued in [ADRs](adr/README.md): private standalone repository,
agentic/deterministic authority, shared gated modes, modular backend/clients, PostgreSQL/
Parquet direction, durable jobs, source provenance, free-first, research promotion and
local-first security. A change requires a superseding ADR with requirement impact and
proof, plus owner policy approval where financial authority changes.

No credentials or financial decisions are needed to finish Phase 0. The immediate human
action after delivery is independent review and the next-phase prompt. Future external
gates remain deliberately closed and are not defects hidden by the verdict.
