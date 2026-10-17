# Phase 2 sources and rights

Reviewed 2026-10-16; next runtime review due 2026-11-16. No account or paid entitlement
is inferred. Source metadata is evidence, never instructions. The source registry
allows personal nonproduction research only and fails closed when its review expires.

| Source | Official evidence and permitted scope | Limits and uncertainty |
| --- | --- | --- |
| DS-01 | [Vision terms v1, updated 2026-08-26](https://github.com/binance/binance-public-data/blob/master/TERMS_AND_CONDITIONS.md); CC BY-NC-SA 4.0 subject to supplementary terms; personal nonproduction research | Commercial/live proprietary execution and compensated redistribution prohibited; derivatives carry restrictions. Repository README's MIT label is not a dataset license. No external redistribution is performed. |
| DS-02 | [Market-data-only endpoints](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md), [REST reference](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md), [terms](https://www.binance.com/en/about-legal/terms), effective 2026-07-21 clause 27 | Noncommercial personal/internal use; no redistribution entitlement asserted. Research collection does not grant later live-use rights. Dedicated public host exposes no account APIs and requires no keys. |
| DS-03 | [MT5 copy_rates_range](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py) | EXTERNALLY BLOCKED. No owner demo profile, encrypted broker credential store, process isolation or genuine terminal identity. No SDK installed or broker terms/access certification claimed. |

Terms SHA-256 (exact downloaded bytes, retained locally under `.local/source-review`):
Vision `dcf358e9d18f598a7a635fac80f6e643fa24a0e111a4d39bda47f1e246b31eb1`;
general terms PDF `bf4879710c904b991848972ec4818ba2cf9e4ce314c09adae84fa2750d3477f7`.
The latter is linked from the current terms page. Copyrighted full terms are not copied
into Git. Operational use must stop for expired/revoked rights or source restrictions.

DS-01 URLs are constructed solely under `https://data.binance.vision/data/spot/` for
daily/monthly BTCUSDT/ETHUSDT 1m/1h klines, with the corresponding `.CHECKSUM` required.
[Archive documentation](https://github.com/binance/binance-public-data) specifies daily
publication the following day, monthly publication on the first Monday, possible later
corrections and the 2025-01-01 transition from milliseconds to microseconds for spot.
Actual access, coverage and checksum outcomes belong in the pilot receipts.

DS-02 uses only `https://data-api.binance.vision/api/v3/klines`, `exchangeInfo`, and
the allowlisted `time` endpoint. Klines are keyed by open time, at most 1,000 per
request; default REST timestamp unit is milliseconds. Kline request weight is 2;
exchangeInfo weight is 20. Source rateLimits and used-weight headers can change.
The local budget is deliberately much smaller: one request at a time, at least two
seconds between attempts, at most 128 requests/64 MiB per invocation, three attempts
for network/5xx failures, 15-second socket timeout and 30-second body deadline.
No request is retried on 429/418 or access restriction; persistent Retry-After cooldown
survives restart. Unknown cooldown defaults to three days. No region/IP bypass,
credential fallback, redirect following or alternate-host fallback is implemented.

Archive responses are limited to 16 MiB compressed/32 MiB expanded, one exact CSV
member, 50,000 rows, 4,096 bytes per line and 200:1 expansion. These are batch budgets,
not historical horizon limits. Missing files or publication delays remain unknown.
REST is asynchronous; publication latency and historical first-seen are not guaranteed.

[Websocket documentation](https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams)
was reviewed; no stream is adopted. REST restart/backfill fits the current closed-bar
scope. No claim of complete trades/ticks, L2 data or seconds-level quote service.

Dependency adoption: Polars 2.0.0 and its exact 2.0.0 CPU runtime are pinned and locked.
[PyPI metadata](https://pypi.org/project/polars/2.0.0/) supports Python 3.13 and Windows;
[Parquet API](https://docs.pola.rs/api/python/stable/reference/api/polars.DataFrame.write_parquet.html)
provides Zstandard without PyArrow/Pandas. This follows the canonical Polars direction;
no GPU/cloud extras are adopted. MIT license and bundled distribution notices must
remain with installed wheels. The Windows runtime wheel is 54,229,989 bytes, locked
SHA-256 `7da1caf3c7b4f397fb213c984013a0c755557619a2d511899a1ff74392484078`.
The installed license inventory, audit and measured footprint are recorded at verification.
