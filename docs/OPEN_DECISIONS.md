# Decision and external gate register

All statuses have an owner and decision point. Owner labels refer to future accountable
roles, not additional people appointed in Phase 0. No ordinary engineering choice is sent
to the founder merely to avoid making a decision.

| ID | Status | Decision / current safe default | Owner | Closure evidence / deadline |
| --- | --- | --- | --- | --- |
| OD-01 | FROZEN | Phase 1 foundation toolchain pinned and measured; quant/broker libraries not adopted | Phase 1 implementer | [Release/license matrix](phase1/TOOLCHAIN.md), hashed lock, 145-test fresh Windows clone, real PostgreSQL and hosted CI proof; independent review remains pending |
| OD-02 | PROVISIONAL | Python-first MT5 gateway, EA/hybrid deferred | Execution maintainer | Real demo disconnect/latency/recovery matrix; decide before Phase 5 exit |
| OD-03 | EXTERNAL | Exness actual demo symbols/contracts/terms/history unverified; no account connected | Owner provides demo authentication, maintainer verifies | Read-only demo attestation/spec snapshot/source rights; Phase 2; execution permission Phase 5 |
| OD-04 | EXTERNAL | Live capital and all live numerical limits unset; current allocation zero | Founder | Signed absolute/percentage capital/loss/leverage policy; before Phase 8 activation |
| OD-05 | EXTERNAL | Instrument/venue financial/religious/jurisdiction eligibility | Founder with chosen qualified advice | Dated evidence and explicit policy decision; before any affected live eligibility; Binance live derivatives stay blocked until separate review |
| OD-06 | EXTERNAL | Off-device encrypted backup and reliable runtime/owner-response plan not proven | Owner + operations maintainer | Recovery medium/key access, restore/uptime/incident drills; before Phase 8 |
| OD-07 | PROVISIONAL | Phase 1 local bearer auth, redaction and Windows ACL-protected DEV credentials tested; WebAuthn, permit signing and encrypted OS store unimplemented | Security maintainer | [Current mechanisms and future library candidates](phase1/SETUP.md); credential/service boundary before authorized connections, client step-up Phase 7 and independent review Phase 8 |
| OD-08 | PROVISIONAL | Phase 1 idle measured: API 86.15 MiB, PostgreSQL 134.55 MiB RSS; 3.899 s API-to-DB readiness; future workload budgets remain estimates | Platform maintainer | [Measurements](phase1/VERIFICATION.md); Phase 2 workload and Phase 5 concurrent load/failure qualification remain required |
| OD-09 | DEFERRED | Redis/NATS/Timescale not installed | Platform maintainer | Revisit Phase 6 capacity review or measured persistent bottleneck; ADR and migration/rollback proof |
| OD-10 | DEFERRED | Premium sources, paid LLMs, local heavy models, richer on-chain/ETF data disabled | Research maintainer + owner for spending | Paired value experiment and rights/footprint review before Phase 6+ adoption; explicit purchase authorization |
| OD-11 | DEFERRED | Tauri/Expo/voice and final chart/UI library versions | Client maintainer | Phase 7 contract/security/accessibility and license review |
| OD-12 | DEFERRED | Full Binance account/execution adapter; Bybit/OKX execution out of scope | Execution maintainer | Explicit later scoped phase, capability/contract tests and eligibility; cannot inherit Exness permit |
| OD-13 | DEFERRED | External engines/libraries for reuse not adopted | Implementer | Exact revision license/NOTICE/dependency/security scan before import/copy/sidecar installation; Phase 3 or later |
| OD-14 | FROZEN | CLOSED for reviewed Phase 0 SHA `745be5b0779f685f731167c0c981d74caae307cf`; independent PASS supplied with explicit Phase 1 prompt | Founder / independent reviewer | [Acceptance record](reviews/PHASE_0_INDEPENDENT_ACCEPTANCE.md); normal PR #1 merged at `eafec07ee7c7a98c9cca17b5f8665494bd650751`; no runtime/live certification |
| OD-15 | PROVISIONAL | Alpha sample/threshold and edge-decay study settings | Research maintainer | Preregister before looking at held-out data in Phase 3; never relax after results |

Frozen decisions are catalogued in [ADRs](adr/README.md): private standalone repository,
agentic/deterministic authority, shared gated modes, modular backend/clients, PostgreSQL/
Parquet direction, durable jobs, source provenance, free-first, research promotion and
local-first security. A change requires a superseding ADR with requirement impact and
proof, plus owner policy approval where financial authority changes.

No credentials or financial decisions are needed for the Phase 1 foundation. Independent
Phase 0 acceptance, authorized normal merge and Phase 1 implementation are recorded.
Phase 1 hosted CI passed after the owner's temporary public-visibility change resolved runner
availability for verification; independent review is pending. Future private Actions allowance
is unverified and must be checked before subsequent workflow runs; no paid usage is authorized.
Future external gates remain deliberately closed.
