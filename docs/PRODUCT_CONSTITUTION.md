# Product constitution

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

Status: Phase 0 architecture baseline independently accepted; Phase 1 accepted and merged.
The 2026-10-17 [ADR-013](adr/013-source-specific-acceptance.md) amendment is independently
accepted at `bdae1a1978ecfe26c201074fe12e81f2c654a4af`; see the
[source-specific acceptance](reviews/PHASE_2_RESEARCH_ACCEPTANCE.md). Phase 2 full operational
status remains OPEN. Private-first remains the baseline; source is temporarily PUBLIC under
the owner-approved exception, review due 2026-10-24. No permanent public approval is inferred.

Auvexo Alpha is a private, single-owner, always-on alpha research and validation desk
with gated autonomous trading. Initial assets are BTC, ETH and XAU/gold. Its purpose
is to discover reproducible edges and preserve capital, including by returning NO TRADE.
Profitability is an empirical question; no strategy is assumed profitable. Agent count,
indicator count, dashboard complexity, model confidence and backtest profit alone are
not success criteria. Success is reproducibility, honest OOS evidence, correct execution,
bounded losses/exposure, useful attribution and safe operation under failure.

Auvexo is an umbrella identity. Alpha is its first separate repository, not a generic
client-management, messaging or multi-product platform. Future ClientOps, Comms and
Research systems integrate through scoped versioned APIs/events, never shared tables.

The core rule is **agentic outside, deterministic inside**. Agents investigate, select
allowlisted research tools and propose hypotheses or candidates. Deterministic services
own features, experiment accounting, risk limits, order construction, reconciliation,
policy enforcement and emergency controls. A risk critic is advisory, never the kernel.

One production-quality domain model serves RESEARCH, BACKTEST, PAPER, DEMO, SHADOW,
LIVE_LIMITED and LIVE. Different clocks, data feeds and execution ports do not create
different risk implementations. SHADOW cannot submit orders. A credential change never
changes an environment's authority. LIVE requires independent signed release permission,
step-up owner activation, account attestation and all readiness gates.

Initial execution target is future Exness MT5 demo qualification. Exness real remains
locked. Binance public spot/derivatives intelligence is allowed; virtual PAPER is implemented;
full account adapter is later scope; Binance live derivatives are BLOCKED_BY_POLICY.
Bybit/OKX are optional intelligence sources. No financial or religious conclusion is
embedded in domain code; eligibility lives in a versioned policy registry.

Core operation cannot depend on paid APIs, paid cloud LLMs, a GPU or a free cloud tier.
The supplied 16 GB laptop and approximately 300 GB free disk are planning constraints,
not measured capacity. Aim for <=120 GB managed footprint with a 150 GB hard quota.

Phase 0 delivered documents only. Phase 3 correctness/research is independently accepted
at bb69220818a519e122d2cd9b1cad75559c2fa244; four empirical outcomes INCONCLUSIVE and
no tradable champion. Phase 4 Checkpoint A engineering is independently accepted at
e3f39e0397e1846c37febcebc246ea91c9f2eb78; see its
[acceptance record](reviews/PHASE_4_CHECKPOINT_A_INDEPENDENT_ACCEPTANCE.md).
Full Phase 4 remains OPEN for >=14 actual-feed PAPER calendar days and replay/ledger proof.
Checkpoint B engineering is independently accepted at
527bd23ce434fee557f6f1414bf5b43d7c3c3f21; see its
[acceptance record](reviews/PHASE_4_CHECKPOINT_B_INDEPENDENT_ACCEPTANCE.md).
PR #6 merged normally at `9b9038b6966843805c99f15e1c37cdba7c026679`.
Preparation and separate owner START have completed; the operational campaign and
registered task remain pinned there. Full Phase 4 remains OPEN and development earns
no qualifying dates. ADR-024 permits only separate-clone offline engineering; actual
Phase 5 commissioning, broker account/credentials/transport, DEMO/REAL orders, live permit
issuer, runtime agents, frontend or paid service remain blocked. All money modes remain denied.

Decision meanings: FROZEN means an accepted design requiring a superseding ADR to change;
PROVISIONAL means a selected direction with a named validation gate; DEFERRED means no
implementation until its trigger; EXTERNAL means owner/provider/reviewer evidence is
required. A frozen design is not an implemented or certified control. The roadmap gates
remain closed until demonstrated. Independent review can amend this baseline.

Canonical precedence within the project: constitution and requirement IDs, then specific
risk/security/venue policies, then ADRs and architecture, then implementation plans.
Contradictions block affected work and require a documented resolution, not silent choice.
The [requirements register](REQUIREMENTS_REGISTER.md) maps all 40 brief sections.

Engineering/research-unblocking acceptance is a reviewed permission to use specified qualified
inputs/contracts in later NON-MONEY engineering under a new prompt. It never declares earlier
operational/source gates complete. Full operational/activation acceptance requires all applicable
real-environment, calendar, source, rights and security evidence. The [roadmap](ROADMAP.md)
defines these two dispositions; phase numbers 0-9 and financial gates remain unchanged.
