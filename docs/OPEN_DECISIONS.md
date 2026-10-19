# Decision and external gate register

Current Phase 4 engineering checkpoint: Phase 3 independently accepted at
`bb69220818a519e122d2cd9b1cad75559c2fa244`; documentation-only acceptance commit
`5a3c03f58dbcc351c85ac799800fed74c01ebce3`, normal PR #4 merge
`b24c42bc07dcd9bc1b62b04d32cc92f047116125` with verified parents. Four empirical
outcomes remain INCONCLUSIVE, both OOS consumed, no champion. See
[acceptance](reviews/PHASE_3_INDEPENDENT_ACCEPTANCE.md),
[frozen requirements](phase4/ACCEPTANCE_TESTS.md) and [ADR-015](adr/015-paper-risk-core.md).
Only virtual PAPER core engineering is authorized on `phase-4/strategy-risk-paper`.
Persistent observation and Phase 5 remain closed; Phase 2 B/C remains OPEN.
Earlier dated wording below describes historical entry/acceptance transitions.

Dated 2026-10-17 [Phase 2 evidence closure](phase2/closure/HANDOFF.md): retrospective
coverage passed, actual scheduled dates zero, Exness DEMO blocked. PUBLIC hosted CI
rerun succeeded; PRIVATE allocation remains unproven. Owner approved a temporary
[public-source exception](phase2/closure/PUBLIC_VISIBILITY_PROPOSAL.md), independent
governance review due October 24, and the bounded local daily task after verification.
Current governance/schedule review is [ADR-013](adr/013-source-specific-acceptance.md) and the
[dated baseline amendment](amendments/BASELINE_CORRECTION_HANDOFF.md). Independent source-specific
acceptance at `bdae1a1` is recorded in [acceptance](reviews/PHASE_2_RESEARCH_ACCEPTANCE.md);
Phase 2 full operational status remains OPEN. Earlier receipts remain historical.

All statuses have an owner and decision point. Owner labels refer to future accountable
roles, not additional people appointed in Phase 0. No ordinary engineering choice is sent
to the founder merely to avoid making a decision.

| ID | Status | Decision / current safe default | Owner | Closure evidence / deadline |
| --- | --- | --- | --- | --- |
| OD-01 | FROZEN | Phase 1 foundation toolchain pinned and measured; quant/broker libraries not adopted | Phase 1 implementer | [Release/license matrix](phase1/TOOLCHAIN.md), hashed lock, 145-test fresh Windows clone, real PostgreSQL and hosted CI proof; Phase 1 independently accepted at `295ded25afdd5a95ee0585b41da9966e45812bcf`; [current-lock maturity exception](amendments/DEPENDENCY_MATURITY.md) independently accepted with ADR-013 at bdae1a1 |
| OD-02 | PROVISIONAL | Python-first MT5 gateway, EA/hybrid deferred | Execution maintainer | Real demo disconnect/latency/recovery matrix; decide before Phase 5 exit |
| OD-03 | EXTERNAL | Exness actual demo symbols/contracts/terms/history unverified; no account connected | Owner provides demo authentication, maintainer verifies | Read-only demo attestation/spec snapshot/source rights; Phase 2; execution permission Phase 5 |
| OD-04 | EXTERNAL | Live capital and all live numerical limits unset; current allocation zero | Founder | Signed absolute/percentage capital/loss/leverage policy; before Phase 8 activation |
| OD-05 | EXTERNAL | Instrument/venue financial/religious/legal/jurisdiction/data-use eligibility; tax/statement/recordkeeping responsibility remains owner/professional | Founder with chosen qualified advice | Dated evidence and explicit policy decision; before any affected live eligibility; Binance live derivatives stay BLOCKED_BY_POLICY |
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
Phase 1 hosted CI and independent acceptance are complete. Current PUBLIC Phase 2 hosted CI
passed at the reviewed entry SHA; PRIVATE allocation remains unproven. Future private Actions allowance
is unverified and must be checked before subsequent workflow runs; no paid usage is authorized.
Future external gates remain deliberately closed.

## Phase 2 gate update (2026-10-16)

Phase 1 independent acceptance and normal merge are recorded in the
[acceptance record](reviews/PHASE_1_INDEPENDENT_ACCEPTANCE.md). OD-01 extends only to
the audited pinned Parquet dependency; OD-03 remains externally blocked, OD-07 still
does not establish broker encrypted-store/service isolation, and OD-08 needs actual
Phase 2 workload receipts. [Source rights](phase2/SOURCES_AND_RIGHTS.md) restrict
public data to research; no live-use entitlement. Seven real scheduled days and
private hosted CI remain separate evidence gates in the [handoff](phase2/HANDOFF.md).

## Baseline amendment review gates (2026-10-17)

ADR-013 is independently accepted/FROZEN at exact `bdae1a1` by GPT-5.6 Sol's disposition
supplied in the owner-authorized Phase 3 prompt. The acceptance/status-only commit implements
no Phase 3 behavior; normal merge/new branch remain required before implementation. OD-03 stays blocked; R-035 scheduled evidence stays OPEN at zero dates. The new
23:00 Pakistan schedule begins no earlier than October 18; no old archive/pilot date transfers.
OD-01's explicit current-lock maturity exception has no auto-upgrade and is reviewed at next
dependency adoption (broker/financial-critical libraries at their adoption phase), or 2026-11-16,
whichever occurs first. OD-06 still requires off-device encrypted recovery and owner-response proof.

R-031's temporary PUBLIC source exception requires independent review by 2026-10-24 and before
broker credential/session integration or proprietary alpha work. Resolve return to PRIVATE or
an owner-approved independently reviewed permanent-public superseding ADR first; expiry is not
approval to continue publicly or authority for an agent to flip visibility. Release integrity
(protected main/release or equivalent and CI-bound manifest/tag) is required before Phase 8.
Tax/statement/recordkeeping and current legal/data-use eligibility require external owner/professional
disposition, without agent legal, tax or religious conclusions.
