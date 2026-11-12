# Decision and external gate register

> Current status is kept in one place: [STATUS](STATUS.md). This document holds
> standing content only. Dated status text that used to be stacked here is preserved
> verbatim in the [history log](history/README.md).

All statuses have an owner and decision point. Owner labels refer to future accountable
roles, not additional people appointed in Phase 0. No ordinary engineering choice is sent
to the founder merely to avoid making a decision.

| ID | Status | Decision / current safe default | Owner | Closure evidence / deadline |
| --- | --- | --- | --- | --- |
| OD-01 | FROZEN | Foundation toolchain pinned and measured. Later adoptions: Parquet stack (Phase 2), React/Vite terminal (Phase 7), and the Windows-only MetaTrader5 5.0.6231 and NumPy 2.4.6 pins for the isolated read-only DS-03 provider (ADR-029). No other quant or broker library is adopted | Implementer | [Release/license matrix](phase1/TOOLCHAIN.md), hashed lock, hosted CI; [lock maturity exception](amendments/DEPENDENCY_MATURITY.md) review due 2026-11-16 |
| OD-02 | PROVISIONAL | Python-first MT5 gateway, EA/hybrid deferred | Execution maintainer | Real demo disconnect/latency/recovery matrix; decide before Phase 5 exit |
| OD-03 | EXTERNAL | Exness demo symbols, contracts, terms and history unverified; no account connected. Read-only adapter code exists (ADR-028, ADR-029, ADR-030) | Owner provides demo authentication after the gates in OD-18 and OD-19; maintainer verifies | Read-only demo attestation, spec snapshot and accepted source rights under a PRIVATE onboarding ADR; execution permission is Phase 5 |
| OD-04 | EXTERNAL | Live capital and all live numerical limits unset; current allocation zero | Founder | Signed absolute/percentage capital/loss/leverage policy; before Phase 8 activation |
| OD-05 | EXTERNAL | Instrument/venue financial/religious/legal/jurisdiction/data-use eligibility; tax/statement/recordkeeping responsibility remains owner/professional | Founder with chosen qualified advice | Dated evidence and explicit policy decision; before any affected live eligibility; Binance live derivatives stay BLOCKED_BY_POLICY |
| OD-06 | EXTERNAL | Off-device encrypted backup and reliable runtime/owner-response plan not proven | Owner + operations maintainer | Recovery medium/key access, restore/uptime/incident drills; before Phase 8 |
| OD-07 | PROVISIONAL | Local bearer auth, redaction, Windows ACL-protected DEV credentials, authenticated bounded IPC and CurrentUser DPAPI secret slots are implemented and tested; WebAuthn, service identity and permit signing are not | Security maintainer | [Phase 1 mechanisms](phase1/SETUP.md); client step-up in Phase 7 and independent review in Phase 8 |
| OD-08 | PROVISIONAL | Phase 1 idle measured: API 86.15 MiB, PostgreSQL 134.55 MiB RSS; 3.899 s API-to-DB readiness. PAPER transaction budget set by ADR-022 (P95 <= 100 ms, P99 <= 250 ms). Other workload budgets remain estimates | Platform maintainer | [Measurements](phase1/VERIFICATION.md); Phase 5 concurrent load and failure qualification still required |
| OD-09 | DEFERRED | Redis/NATS/Timescale not installed | Platform maintainer | Revisit Phase 6 capacity review or measured persistent bottleneck; ADR and migration/rollback proof |
| OD-10 | DEFERRED | Premium sources, paid LLMs, local heavy models, richer on-chain/ETF data disabled | Research maintainer + owner for spending | Paired value experiment and rights/footprint review before Phase 6+ adoption; explicit purchase authorization |
| OD-11 | DEFERRED | Tauri, Expo and voice clients, and chart libraries. The read-only web terminal uses React, TypeScript and Vite with no other runtime dependency | Client maintainer | Phase 7 contract, security, accessibility and license review |
| OD-12 | DEFERRED | Full Binance account/execution adapter; Bybit/OKX execution out of scope | Execution maintainer | Explicit later scoped phase, capability/contract tests and eligibility; cannot inherit Exness permit |
| OD-13 | DEFERRED | External engines/libraries for reuse not adopted | Implementer | Exact revision license/NOTICE/dependency/security scan before import/copy/sidecar installation; Phase 3 or later |
| OD-14 | FROZEN | CLOSED for reviewed Phase 0 SHA `745be5b0779f685f731167c0c981d74caae307cf`; independent PASS supplied with explicit Phase 1 prompt | Founder / independent reviewer | [Acceptance record](reviews/PHASE_0_INDEPENDENT_ACCEPTANCE.md); normal PR #1 merged at `eafec07ee7c7a98c9cca17b5f8665494bd650751`; no runtime/live certification |
| OD-15 | FROZEN | Phase 3 thresholds were preregistered in the data plans and used once; four outcomes INCONCLUSIVE and both holdouts consumed. Any new study needs a new preregistration on unconsumed evidence; edge-decay settings remain undecided | Research maintainer | [Phase 3 acceptance](reviews/PHASE_3_INDEPENDENT_ACCEPTANCE.md); never relax after results |
| OD-16 | EXTERNAL | Evidence campaigns are registered but not accruing: the operational database is down, the laptop is often unavailable at trigger time, and the pinned release cannot complete either campaign | Owner | Decide to restart on a corrected release; see [evidence campaigns](runbooks/EVIDENCE_CAMPAIGNS.md) |
| OD-17 | EXTERNAL | Host clock is unsynchronised and measured about 33 s slow | Owner | Elevated resync or NTP path; [clock trust](runbooks/CLOCK_TRUST.md); required for PAPER qualification and any open-interest START |
| OD-18 | EXTERNAL | Repository is temporarily PUBLIC (ADR-027) | Owner | PRIVATE before any actual account, session, credential or confidential alpha work |
| OD-19 | EXTERNAL | DS-03 source rights: the Exness client agreement restricts collecting or storing quotes and automated access to platform information | Owner with chosen qualified advice | Dated evidence and an explicit decision, possibly written broker consent, in a PRIVATE onboarding ADR (ADR-030) |
| OD-20 | EXTERNAL | DS-01 and DS-02 rights review due 2026-11-16; DS-04-A1 due 2026-11-27. Enforced in code | Owner confirms terms; maintainer records | [Rights review](runbooks/RIGHTS_REVIEW.md); a renewal is a new release |
| OD-21 | PROVISIONAL | Open-interest value gate: no honest outcome-blind mechanism from open interest to a candidate exists (VALUE_ABLATION_PREREGISTRATION_BLOCKED_MECHANISM). A predictability pass proves no price, trading, filter or safety value | Research maintainer | A separately preregistered paired ablation on unconsumed evidence |
| OD-22 | EXTERNAL | Release integrity: no branch protection, ruleset, signed tag or release manifest exists | Owner | Protected main or equivalent reviewed control and a CI-bound manifest before Phase 8 |
| OD-23 | PROVISIONAL | Engineering findings from the 2026-11-12 rebaseline that were recorded but not fixed, most of them in the PAPER kernel and database roles | Implementer | [Rebaseline audit](reviews/AUVEXO_FULL_A_TO_Z_REBASELINE_2026-11-12.md); close before the phase each one blocks, at the latest before any Phase 5 demo order |

Frozen decisions are catalogued in [ADRs](adr/README.md): private standalone repository,
agentic/deterministic authority, shared gated modes, modular backend/clients, PostgreSQL/
Parquet direction, durable jobs, source provenance, free-first, research promotion and
local-first security. A change requires a superseding ADR with requirement impact and
proof, plus owner policy approval where financial authority changes.

