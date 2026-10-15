# Client and UX direction

Status: FROZEN boundary; visual/component choices DEFERRED to Phase 7. No UI implemented now.

One backend serves a private web terminal, Windows desktop client, Android sideloaded APK
and voice interface. All business decisions live in the backend. Clients use versioned
OpenAPI/event contracts and presentation adapters; no broker credentials, direct venue
execution, engine imports or independent risk implementations. A presentation redesign
must pass the same API contracts without altering trading behavior.

Direction: dark-first professional terminal, clear hierarchy, dense but legible tables,
keyboard navigation/shortcuts, responsive layouts, accessible focus/contrast and screen-reader
labels, reduced-motion preference, restrained animation. No casino styling or unexplained
AI confidence meters. Mode/account/permit/risk/health and freshness are continuously visible.
NO TRADE and missing evidence are useful outcomes, not errors to conceal.

Planned areas: Command Center; BTC/ETH/Gold desks; Market/Chart workspace; News/Event
intelligence; Macro; Signals/Candidates; Positions; Risk; Strategy Lab; Backtests; Journal;
Research; System Health; Settings/Policies. Start a minimal operational view as needed for
demo safety; rich terminal work follows research proof. Each decision has a why/evidence
view. Stale realtime state is visibly stale; reconnect uses sequence-resume and snapshots.

Voice may request briefings, state, decision explanations, open risk or pause-new. Voice
recognition is not identity. CLOSE ALL, ENABLE LIVE, risk increases and venue activation
require authenticated action-specific visual confirmation and step-up, with replay expiry.
No accidental wake-word live activation. Mobile/desktop credentials use platform secure
storage and scoped sessions; no execution secrets are distributed with app bundles.

Price charts may use [Lightweight Charts](https://www.tradingview.com/lightweight-charts/);
verify license/NOTICE and attribution requirements at integration. Research charts may use
ECharts if it adds a distinct capability. Desktop/mobile/voice libraries are evaluated for
maintained versions, signed packaging, permissions and resource use in Phase 7.
