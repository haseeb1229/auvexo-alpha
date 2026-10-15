# Open-source reuse review

Reviewed 2026-10-15 using upstream repositories, selected implementation files, license
text and GitHub metadata. This is architectural due diligence, not a full code/security
audit or certification. No upstream package was installed, no source copied, no repo forked
or vendored. Project root is new. References below can change; adoption must pin and review
the exact revision, all file headers, dependency licenses, NOTICE and vulnerability results.

## Findings and disposition

| Project | Problem/architecture evidence | Maintenance/dependencies/security considerations | License evidence and decision |
| --- | --- | --- | --- |
| Hummingbot | Crypto connectors/market making; inspected [order tracker](https://github.com/hummingbot/hummingbot/blob/master/hummingbot/connector/client_order_tracker.py): distinct in-flight/cached/lost orders and trade updates | Unarchived, API pushed_at 2026-10-15; Python/Cython and broad connector surface increase dependency/credential exposure. Connectivity quality is venue-specific, not guaranteed by activity | [Apache-2.0](https://github.com/hummingbot/hummingbot/blob/master/LICENSE). REFERENCE for order lifecycle; optional benchmark later. Do not copy its risk assumptions or adopt its bot as root |
| Freqtrade | Crypto research/backtesting; inspected [lookahead analysis](https://github.com/freqtrade/freqtrade/blob/develop/freqtrade/optimize/analysis/lookahead.py): compares full vs cut indicator frames | Unarchived, pushed_at 2026-10-15; Python/Pandas/exchange integrations; strategy plugin code and exchange credentials are privileged surfaces. One leakage check is not a complete validity proof | [GPL-3.0 text](https://github.com/freqtrade/freqtrade/blob/develop/LICENSE). BENCHMARK as separate optional research tool; no linked/copied engine without license review. Do not inherit its strategy profitability claims |
| QuantConnect LEAN | Multi-asset engine; inspected [transaction handler](https://github.com/QuantConnect/Lean/blob/master/Engine/TransactionHandlers/BrokerageTransactionHandler.cs): brokerage abstraction and account/order events | Unarchived, pushed_at 2026-10-15; C#/.NET with Python integration adds runtime/data operational weight; brokerage plugins need independent credential/behavior review | [Apache-2.0](https://github.com/QuantConnect/Lean/blob/master/LICENSE). REFERENCE and possible independent simulator benchmark; not core runtime or mandatory cloud subscription |
| TradingAgents | Research orchestration; inspected [graph](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/graph/trading_graph.py): provider selection, checkpoints, memory and reporting | Unarchived, pushed_at 2026-10-03; LLM/data-provider dependencies introduce prompt injection, latency, cost and reproducibility risks; apparent debate does not validate an edge | Current [Apache-2.0](https://github.com/TauricResearch/TradingAgents/blob/main/LICENSE), not assumed from older versions. REFERENCE for bounded investigation; no live authority, mandatory provider or wholesale graph adoption |
| OpenBB | Provider normalization; inspected [fetcher abstraction](https://github.com/OpenBB-finance/OpenBB/blob/develop/openbb_platform/core/openbb_core/provider/abstract/fetcher.py): transform/extract/transform and optional dependencies | Unarchived, pushed_at 2026-10-15. Repository redirects to openbq-org/OpenBB. Python/provider ecosystem can require independent paid data rights. GitHub license metadata returned NOASSERTION | Inspected [root license](https://github.com/OpenBB-finance/OpenBB/blob/develop/LICENSE) explicitly declares Apache-2.0; metadata discrepancy requires revalidation at adoption. REFERENCE, optional isolated data sidecar only after rights/dependency review |
| CCXT | Unified exchange API library; inspected [package manifest](https://github.com/ccxt/ccxt/blob/master/package.json) and license; adapter may reduce future Binance normalization work | Large multi-language/exchange surface; rapid release churn and exchange-specific semantics require pinned tests. No claim that a unified API normalizes precision, client IDs or order guarantees perfectly | [MIT](https://github.com/ccxt/ccxt/blob/master/LICENSE.txt). DEFERRED dependency candidate for future exchange adapter; direct official endpoints sufficient for first data sources; not MT5 replacement |

Maintenance signals are only activity indicators, not security findings. No vulnerability
scan was run on uninstalled upstream code, and no project is declared vulnerability-free.
Before reuse: enumerate the exact dependency graph and build hooks, run current advisory/
secret/SAST checks appropriate to that package, inspect permission/credential paths, verify
release provenance and benchmark our failure contracts. Reject code that needs broader
authority than its task. No benchmark tool may receive live credentials.

## Evidence and license handling

GitHub API branch snapshots observed during review (not installed dependency pins):

- Hummingbot master: `9af100d6822da7d2d0291a906c730ef172284ee2`.
- Freqtrade develop: `b33068949fc16e69e288e0a5bef5bd1f086f0a27`.
- LEAN master: `154e50720c430c14c83669d2ba7f9b715f0e76d2`.
- TradingAgents main: `1394a3f72aa4393e1a98f51b382434c4b4c2d972`.
- OpenBB develop: `7c9d4221bdf66965e3f6c7f4dc6ee848073e5ae2`.

OpenBB LICENSE blob metadata: `8e8cca33304520693be306cad3b55cba0c358676`.
CCXT API metadata: unarchived, pushed_at 2026-10-15, SPDX MIT.

Selected files were read through upstream branch URLs in the same session; branch
movement and web-cache timing mean these metadata SHAs are not claimed to be exact content
hashes for every viewed file. Adoption must fetch the chosen commit directly and hash it.
This limitation is acceptable for reference-only Phase 0 and prevents false reproducibility.

Apache-2.0 reuse must retain applicable license/copyright/NOTICE and identify modifications;
MIT requires its copyright/permission notice when applicable. GPL redistribution/combination
obligations require assessment before any copied or linked implementation. A private repo
does not erase license obligations. Separate execution is an engineering isolation choice,
not a claim that it automatically resolves every licensing question. No source is adopted
here, so no fabricated third-party inventory/NOTICE is added. Future inventory records
package/version/hash, license, origin, use, modifications, notices and review owner.

Architecture conclusion: borrow proven concepts and benchmark correctness; retain our own
policy, risk authority, market-state schema and Exness reconciliation semantics. Plain
libraries with a narrow purpose are preferred over embedding complete trading platforms.
