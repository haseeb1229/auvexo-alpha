# Data source register

Status: PROVISIONAL provider candidates; no credentials, signups or feeds connected in Phase 0.
Sources inspected 2026-10-15. Access terms, region, API limits, history depth and account product
availability must be verified at integration. Public documentation is not an access entitlement.

| ID / priority / phase | Source and purpose | Cost/auth/availability | Limitations, failure and acceptance |
| --- | --- | --- | --- |
| DS-01 / P0 / 2 | [Binance public archives](https://github.com/binance/binance-public-data): BTC/ETH spot bars/trades | Public download, no trading credentials | Validate checksums/timestamp units/gaps; preserve retrieval date; does not establish Exness execution prices |
| DS-02 / P0 / 2 | [Binance spot REST](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints) plus documented streams: live quotes/trades | Public market endpoints, current quotas at integration | Snapshot/stream gap recovery, rate-limit backoff; outage marks stale; never silently switch execution venue |
| DS-03 / P0 / 2 and 5 | [MT5 history/ticks](https://www.mql5.com/en/docs/python_metatrader5): Exness executable BTC/ETH/XAU mapping | Existing account/terminal later; history and symbol availability account-dependent | Demo read-only onboarding in Phase 2; no real credential. Validate spreads, sessions, contract specs and history depth; insufficient XAU data blocks XAU claims |
| DS-04 / P1 / 6 | [Binance derivatives market data](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest): OI, funding, basis, mark/index | Public intelligence endpoints where permitted | Historical depth varies; collect forward when missing; liquidation feeds not assumed complete; live derivatives stay blocked |
| DS-05 / P1 / 6 | [BLS](https://www.bls.gov/developers/): labor/CPI; [BEA](https://apps.bea.gov/API/signup/): GDP/PCE | Free options, registration may improve access; no signup now | Release-vintage/first-seen gaps; original vs revised series; official scheduled releases precede news experiments |
| DS-06 / P1 / 6 | [Fed calendar/statements](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm), [FRED/ALFRED](https://fred.stlouisfed.org/docs/api/fred/): rates/yields/macro vintages | Official pages; API key may be required later | Observe source-specific terms/revisions; no invented market consensus, latency or release surprise |
| DS-07 / P2 / 6 | [Bybit API](https://bybit-exchange.github.io/docs/v5/intro), [OKX API](https://www.okx.com/docs-v5/en/): cross-venue intelligence | Public endpoints if allowed; no execution credentials | Revalidate terms and rate limits before use; normalized units and venue-basis tests; optional outage cannot invalidate unrelated strategies |
| DS-08 / P2 / 6 | Official regulators, exchanges, issuer/project announcements | Permitted RSS/API/pages, no mandatory paid wire | Source identity and correction/dedup tests; sandbox browser fallback only where allowed; cannot promise complete or instant news |
| DS-09 / P2 / 6+ | ETF flows, selected on-chain, DXY/real yields, Fed expectations | Provider-specific free coverage uncertain | Defer until legal use, vintage history and incremental value proven. No synthetic substitute passed off as data |
| DS-10 / P3 / 6+ | Professional news, CoinGlass, Trading Economics, X and premium alternative data | OPTIONAL paid/license/credential gate | Require cost-benefit experiment and owner purchase authorization; never mandatory for demo |

Required minimal experiment data: venue/product identity, timestamped OHLCV with known volume
meaning, bid/ask or an explicitly conservative spread model, fee/financing/contract specs and
trading calendar. Required future execution data adds fresh broker quote/account/order/position
truth and reliable reconciliation history. Price-only research may start without macro/news/OI.
Historical uncertainty must be disclosed; it cannot be repaired by an LLM's recollection.

Initial macro priority is Fed/CPI/NFP schedule-aware blackouts and an ablation, then PCE,
labor/wages/claims/JOLTS, GDP/retail/PPI/ISM/PMI, yields/liquidity if evidence warrants.
ECB/BoE/BoJ/PBoC, oil, geopolitics, sanctions/tariffs and banking shocks are later scoped
event categories. Crypto outages/hacks, depegs and regulation are safety intelligence.
No full-depth retention or comprehensive all-news aggregator is an early dependency.

Each integrated source must record owner (data maintainer), exact endpoints/fields, rights,
redistribution restrictions, authentication class, rate budget, expected delay, freshness SLA,
retention, timestamp/vintage behavior, quality tests, fallback and next review date. P0 source
contracts close in Phase 2; P1/P2 close before their Phase 6 experiment. Do not backfill
restricted content by prohibited scraping. Raw article retention defaults to permitted
metadata/hash/excerpts; full content only when rights allow.

## Phase 2 source review

Current DS-01/02 rights, endpoints, limits, hashes and expiry are recorded in
[sources and rights](phase2/SOURCES_AND_RIGHTS.md); implemented access is restricted
to personal nonproduction research. Vision dataset terms take precedence over the
repository README code-license label. No future live-use license is inferred.
DS-03 remains externally blocked pending owner-side demo prerequisites; spot cannot
substitute for broker CFD prices/specs/history. Actual provider evidence is in
[verification](phase2/VERIFICATION.md).

[ADR-013](adr/013-source-specific-acceptance.md) requires source-specific research admission
and future typed experiment/release data-use classification. DS-01/02 selected spot evidence
cannot qualify DS-03 CFDs/XAU, continuous uptime, execution feed quality or production rights.
Full Phase 2 operational status remains OPEN during any later explicitly authorized engineering.
