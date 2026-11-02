# DS-03 actual adapter provider/package review

Status: FROZEN_BEFORE_IMPLEMENTATION; ENGINEERING_ONLY; NO_ACTUAL_ACCOUNT_SESSION.
Date: 2026-11-03. [ADR-029](../adr/029-ds03-mt5-readonly-adapter.md).

Official public facts rechecked before this freeze; raw package adoption recheck follows immediately
before installing. No provider account connected and no actual account rights accepted.

| Source | Fact / consequence |
| --- | --- |
| [PyPI exact metadata](https://pypi.org/pypi/MetaTrader5/5.0.6231/json) | MetaQuotes official owner, Windows, MIT metadata, numpy>=1.7, CP313 x64 wheel 47964 bytes and SHA256 3a8c8349ce691a4ef05e314afc034ad82f4dbb19415efc7442af5ea075d5e797; no Trusted Publishing/provenance. Registry is no binary security certification. |
| [Initialize](https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py) | Can launch terminal; omitted values can discover terminal/reuse last account/stored password. Freeze all explicit arguments; path positional; 5000ms and portable=True. |
| [Portable start](https://www.metatrader5.com/en/terminal/help/start_advanced/start) | Dedicated writable non-Program-Files terminal/profile; empirical Exness compatibility remains future private proof. No ambient fallback. |
| [Account](https://www.mql5.com/en/docs/python_metatrader5/mt5accountinfo_py) | trade_mode/login/server/currency/leverage/trade_allowed exposed; broker Standard/Pro product account type not exposed. Owner metadata only, no inferred observation. |
| [Terminal](https://www.mql5.com/en/docs/python_metatrader5/mt5terminalinfo_py) | connected/trade_allowed/build/path/data_path; no trustworthy PID/executable hash. Independent native OS attestation required. |
| [Version](https://www.mql5.com/en/docs/python_metatrader5/mt5version_py) | Terminal build/version distinct from installed Python package version. |
| [Specs](https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfo_py) | Preserve exact symbol, currencies, tick/volume/contract/stops/freeze/modes/swaps; raw order/filling bitmasks and trade_calc_mode meanings, not synthetic enum guesses. |
| [Tick](https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfotick_py) | time_msc/flags and finite numerical conversion retained; legitimate same-ms multiplicity must not be silently deduplicated. Ambiguous batches refuse. |
| [Bars range](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py) | Inclusive endpoint, chart-limited history, no count argument; bound interval count before call, half-open closed bars and honest unknown gaps. |
| [Counted ticks](https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksfrom_py) | Count-bounded copy_ticks_from instead of unbounded range allocation; request.limit+1 max257; UNKNOWN coverage, no completeness proof. |
| [Account history](https://www.mql5.com/en/book/advanced/python/python_history_deals) | Orders have pending/partial/rejected/expired states; deals include balance/credit/commission with empty symbol/zero volume. Preserve exact enums/variants or refuse whole batch; never cast to synthetic BUY/SELL. |
| [Exness password types](https://get.exness.help/hc/en-us/articles/360013783060-Exness-password-types) | Separate read-only password, 8–15 upper/lower/digit/special, differs from trading password. Selection provenance plus observed disabled flags required; syntax alone insufficient. |
| [Exness desktop MT5](https://get.exness.help/hc/en-us/articles/360011514572-MT5-Trading-guide-Desktop) | Supported MT5 baseline build4755; real dedicated portable compatibility remains unproven until private onboarding. |
| [NumPy releases](https://numpy.org/doc/stable/release.html) | Native array dependency required by exact SDK; supported CP313 Windows pin reviewed at adoption, narrowly scoped marker, no unrelated updates. |

Independent ZIP review before freeze: init.py SHA256 2e3bc321ab35b5c9e6c777665f381bc686bbf60791160838a0e84406dc0052cf;
_core.cp313-win_amd64.pyd SHA256 b92756775337aff9c82cac078099da63c4486884539708ae0fbda3a7000b991d;
LICENSE.txt SHA256 76bb8db55f77cab31d293ed3c7059ed5623e9c54714f0857e0d92e0783571860.
CRC passed, bundled MIT notice MetaQuotes copyright2000–2025. Preserve notice at adoption.
Package import-only proof may load the binary but never initialize/login/session.

Exact owner legal entity, current Client Agreement/General Business Terms/platform/data/API terms,
jurisdiction eligibility and personal/internal storage/retention/derived research/redistribution rights
remain UNKNOWN and unaccepted. MIT package license grants no broker data rights. Actual rights
ambiguity blocks source qualification. No XAU/BTC/ETH/suffix availability assumption.
