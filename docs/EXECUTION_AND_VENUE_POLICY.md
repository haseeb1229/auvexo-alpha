# Execution and venue policy

Status: FROZEN gates; Python-first MT5 transport PROVISIONAL pending Phase 5 qualification.

## Mode and eligibility matrix

| Mode | Clock/truth | Permitted execution |
| --- | --- | --- |
| RESEARCH | Dataset available-at and experiment metadata | None |
| BACKTEST | Deterministic simulation clock | Simulator only |
| PAPER | Live feeds, virtual account | Simulator only |
| DEMO | Broker-demo truth | Only attested demo account after Phase 5 commissioning preflight |
| SHADOW | Live market/read-only account truth | Record proposals/comparisons; no send capability |
| LIVE_LIMITED | Real broker truth | Phase 8 permit with tiny owner-approved allocation |
| LIVE | Real broker truth | Phase 9 explicitly expanded permit |

Eligibility is keyed by venue, product, instrument, account jurisdiction and operation,
not one misleading venue-wide flag. States: APPROVED, RESEARCH_ONLY, PAPER_ONLY,
REVIEW_REQUIRED, BLOCKED. APPROVED is necessary but never sufficient for real execution.
All executions remain disabled in the current Phase 2/amendment. The matrix describes future gates:

| Venue/product | Data/research | Paper/demo | Real |
| --- | --- | --- | --- |
| Exness MT5 BTC/ETH/XAU products actually available to account | RESEARCH_ONLY until integration/terms verified | DEMO may become APPROVED at Phase 5; paper permitted earlier | REVIEW_REQUIRED; LOCKED pending Phase 8 |
| Binance spot | RESEARCH_ONLY public data | PAPER_ONLY | REVIEW_REQUIRED, adapter deferred |
| Binance derivatives | RESEARCH_ONLY intelligence | PAPER_ONLY | BLOCKED with reason BLOCKED_BY_POLICY |
| Bybit/OKX | RESEARCH_ONLY if useful/permitted | Not initial execution scope | BLOCKED |
| Unknown instrument/venue | No inferred authorization | No | BLOCKED |

Policy changes preserve history, reason, evidence, owner and effective time. No religious
conclusion is encoded in calculations. Broker symbols are discovered and mapped explicitly;
do not assume BTCUSD, ETHUSD or XAUUSD contract details. CFD and exchange spot/perpetual
prices may inform each other but are not interchangeable execution or backtest data.

Phase 5 commissioning preflight is distinct from its sustained-demo exit gate: Phase 4
tests must pass, demo account/server/type and source contracts must be verified, gateway
auth/journal/kill/reconciliation must pass offline negatives, and the authorized Phase 5
release must issue a demo-only qualification permit with bounded test orders. This enables
controlled demo observations needed to qualify the transport; it never enables real money.
Sustained operation is accepted only after the Phase 5 exit evidence is complete.
Phase 2 uses broker read-only/investor access where supported; if unavailable, collect via
a narrowly scoped read-only gateway interface and disclose the underlying terminal rights.
Never claim an SDK lacking an order tool alone cryptographically restricts an account.

## MT5 transport study

| Criterion | Python integration | Thin MQL5 EA bridge | Hybrid |
| --- | --- | --- | --- |
| Connectivity | Official terminal IPC; dedicated process, heartbeat and reconnect | Terminal-native callbacks; bridge transport adds authentication/queues | Two channels with explicit writer ownership |
| Acknowledgment | Request result plus orders/deals/positions polling | Transaction callbacks reduce observation delay | Callback wakeups plus polling reconciliation |
| Unknown/partial | Poll authoritative history; timeout is UNKNOWN | Callbacks can be out of order/lost; still query history | Cross-channel dedupe and history required |
| Idempotency | No assumed broker idempotency; own journal and fencing | Same; magic/comment not unique-order guarantees | Extra risk of duplicate writers unless one writer enforced |
| Reliability | Blocking IPC isolated; crashed call requires reconcile | Short handlers; queue overflow possible | More moving parts; can improve observability after proof |
| Testability | Small transport port and recorded contracts straightforward | MQL compile/terminal tests plus protocol fixtures | Most expensive failure matrix |
| Deployment | Windows terminal+gateway; remote core later | Windows terminal+EA, optional secured remote core | Same Windows dependency, extra release coordination |
| Recovery | Reattest account, query open/history, restore journal | Replay journal and query broker; never trust callback completeness | Resolve conflicts against broker facts |

Select Python-first for bounded minute/hour strategies, with no HFT promise. Keep an
EA transport replaceable behind the same contract; add it only if measured event latency
or recovery gaps fail Phase 5. Reliability comes from journal/reconciliation and failure
tests, not choice of language. No bridge of any kind is built in Phase 0.

Official [Python integration](https://www.mql5.com/en/docs/python_metatrader5) provides
terminal connection, account, order, position and history functions. An
[order_send result](https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py)
must be interpreted with broker state, not treated as final position truth. MQL5
[OnTradeTransaction](https://www.mql5.com/en/docs/event_handlers/ontradetransaction)
documents non-guaranteed arrival ordering and a finite 1,024-event queue. These facts
support reconciliation even when an EA is selected. Documentation is not proof of
actual Exness behavior; account-specific demo tests remain mandatory.

## Submission and reconciliation protocol

Candidate -> validated immutable intent -> atomic risk reservation/outbox -> dispatch claim
-> SENT_PENDING -> ACKNOWLEDGED/REJECTED/UNKNOWN -> PARTIALLY_FILLED/FILLED/CANCELED/EXPIRED.
Terminal statuses may receive late deals; ledger corrections append facts, never erase
history. Cancel-requested is not canceled. A partial fill may coexist with pending remainder.

Persist dispatch attempt before calling broker. One durable writer epoch per account is
checked at the gateway. Native order/deal IDs and unique fill keys deduplicate callbacks
and polls. Map return codes and netting/hedging behavior in contract tests. Compare open
orders, positions and overlapping history windows to the local ledger on startup, after
every ambiguous response/reconnect, and on a bounded schedule. Manual broker trades are
external facts: quarantine new entries and reconcile portfolio risk before resume.

After a timeout/crash between send and persistence, mark UNKNOWN, hold reservation, pause
new orders for the account and query broker truth. Never resubmit because a local timeout
expired. If history cannot prove the result, require owner investigation. A confirmed
rejection with no execution may permit a newly authorized intent; it is not a blind retry.
No end-to-end exactly-once claim is possible without broker support.

Protective orders use broker-side stops where supported; verify acceptance and persistence.
If a required stop fails, follow preapproved cancel/flatten rules with a separate typed
intent; never hide the unprotected exposure. Gap and terminal/network outage risk remains.

## Independent live interlocks

Startup and every send require agreement among: explicit LIVE_LIMITED/LIVE mode; attested
real account/server identity; eligible product policy; signed LiveTradingPermit; qualified
release/config/strategy hashes; current owner step-up activation; unrevoked epoch; fresh
data and reconciled account; active authorization and reservation. Expiry/revocation
denies new exposure immediately, with risk-reducing handling governed by risk policy.

Credentials contain no activation flag. DEMO plus a real account is a hard startup refusal.
Permit revocation cannot recall an order already sent. Serialize new dispatch claims with
permit/epoch checks, mark in-flight attempts for reconciliation on revocation, and apply
authorized cancel/reduction handling to confirmed residual exposure. Never report instantaneous
zero exposure merely because an internal permit was revoked. Pre-live SHADOW uses public
market and demo/read-only simulated portfolio observations; it does not require real credentials.

The gateway validates account mode independently, rather than trusting an environment label.
Separate account profiles and secret namespaces are required. Research/PAPER/SHADOW
processes do not load execution credentials. No trading credential may withdraw; where
a broker's terminal credential lacks granular scopes, document that fact and prevent
portal/withdrawal access at the capability and process boundary. Owner portal credentials
are never loaded into the system. Broker terms/rights must be verified before onboarding.

Source-specific engineering acceptance under [ADR-013](adr/013-source-specific-acceptance.md)
confers no order or permit capability. Every activation/promotion still needs all applicable
operational, source, rights, security and financial gates; incomplete qualifications deny it.
