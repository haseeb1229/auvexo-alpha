# Decision and external gate register

Phase4 engineering is independently accepted; actual-feed observation is ACTIVE on the
separate pinned operational checkout at `9b9038b6966843805c99f15e1c37cdba7c026679`.
Full Phase4 remains OPEN pending genuine dates/span/replay/zero mismatch. The separate
development clone is authorized only for Phase5 OFFLINE/PRE-COMMISSIONING engineering
under [ADR-024](adr/024-parallel-operational-release-and-engineering.md) and [offline requirements](phase5/OFFLINE_ACCEPTANCE.md).
Actual Phase5 commissioning and sustained-demo evidence are NOT STARTED. Broker
SDK/session/order capability is absent; no credentials or money authority. Phase2 full
operational OPEN/DS03 BLOCKED; Phase3 four INCONCLUSIVE outcomes, both OOS consumed,
no candidate/champion. PUBLIC governance review due2026-10-24 and DS02 rights review
due2026-11-16 remain unwaived. Never alter/repoint the operational checkout/task/config/
activation from this development lane. Dated handoffs retain their original historical facts.

Phase 4 Checkpoint A engineering is independently ACCEPTED/PASS at
`e3f39e0397e1846c37febcebc246ea91c9f2eb78` by GPT-5.6 Sol. See the
[acceptance record](reviews/PHASE_4_CHECKPOINT_A_INDEPENDENT_ACCEPTANCE.md) and
[Checkpoint A handoff](phase4/HANDOFF.md). ADR-015 through ADR-022 are ACCEPTED/FROZEN
for this engineering scope. ADR-022 retains the 272.4386 ms concurrent stress tail
as THROTTLE_REQUIRED evidence; no benchmark rerun is authorized.

Full canonical Phase 4 remains OPEN pending >=14 actual-feed PAPER calendar days,
replay evidence and zero unexplained ledger mismatches. Observation is ACTIVE on the
separately pinned operational checkout; this development lane earns no qualifying dates. PR #5 merged normally at dbe3cd6f47bf5a48c044df2f36cba5ea7081ca09
after exact-head administrative CI. Checkpoint B engineering is independently
ACCEPTED/PASS at `527bd23ce434fee557f6f1414bf5b43d7c3c3f21`; see its
[acceptance record](reviews/PHASE_4_CHECKPOINT_B_INDEPENDENT_ACCEPTANCE.md).
[ADR-023](adr/023-paper-observation-qualification.md) and its requirements/runbook are
ACCEPTED/FROZEN; original bytes retained. PR #6 merged normally at
`9b9038b6966843805c99f15e1c37cdba7c026679`. Preparation and separate owner START have
completed; the operational campaign and registered task remain pinned there. ADR-024
permits only separate-clone offline engineering; actual Phase 5 commissioning, broker
capability and money authority remain blocked.

Phase 2 B/C remains OPEN: October 18/19 INCOMPLETE, genuine qualified scheduled dates
zero, DS-03/Exness blocked. Phase 3 remains independently accepted at bb692208 with
four INCONCLUSIVE outcomes, both OOS holdouts consumed and no candidate/champion.
PUBLIC exception review remains due 2026-10-24; repository settings are unchanged.
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
