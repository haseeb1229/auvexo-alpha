# DS-03 provider and transport decision review

Review date: 2026-11-02. Scope: generic/synthetic engineering only under ADR-027/028.
No material contradiction with the owner-supplied DS-03 provider contract was found.
Actual account/source/terms/security qualification remains OPEN.

## Official provider facts

- Exness supports DEMO accounts, excluding Standard Cent from DEMO availability:
  [account creation](https://get.exness.help/hc/en-us/articles/4408633634322-How-to-create-trading-accounts).
- A separate read-only access password disables trading. Current provider syntax uses
  8–15 characters, uppercase/lowercase English letters, numbers and a special character.
  It must differ from a trading password. No PA, trading, email or recovery password is
  accepted by this foundation: [password types](https://get.exness.help/hc/en-us/articles/360013783060-Exness-password-types).
- Investor authorization permits account/price inspection with trading unavailable:
  [MetaTrader authorization](https://www.metatrader5.com/en/terminal/help/startworking/authorization).
  A false trade_allowed field alone does not prove investor-password provenance; future
  actual onboarding must establish both credential provenance and observable disabled
  trading with exact DEMO/account/server/profile binding.
- The Exness MT5 support notice names build 4755 or later. Actual chosen terminal and
  Python adapter compatibility require separate empirical onboarding proof:
  [Exness desktop MT5 guide](https://get.exness.help/hc/en-us/articles/360011514572-MT5-Trading-guide-Desktop).
- The Python integration exposes trade operations, including order_send. The package is
  not a read-only security boundary: [official API](https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py).
- Initialization may launch a terminal and reuse its last account/stored credentials when
  parameters are omitted. This sprint introduces no such initialization:
  [initialize](https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py).
- Available bars depend on terminal chart history; provider bar/tick timestamps and request
  times are UTC-oriented. Unknown history depth remains unknown, with explicit gaps:
  [history](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrom_py).
  Symbol metadata does not establish every session/history fact automatically:
  [symbol information](https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfo_py).

These are paraphrased provider statements, not copied provider content or a legal opinion.
Package permission does not confer rights to broker/account data, redistribution or research.
Current provider/terms/source rights must be rechecked before actual onboarding.

## Exact package candidate: reviewed, not adopted

Official source: [MetaQuotes PyPI package](https://pypi.org/project/metatrader5/) and
[version metadata](https://pypi.org/pypi/MetaTrader5/5.0.6231/json).

| Item | Evidence / limit |
| --- | --- |
| Candidate | MetaTrader5 5.0.6231; registry release date 2026-09-27; maintainer MetaQuotes |
| Wheel | metatrader5-5.0.6231-cp313-cp313-win_amd64.whl; 47,964 bytes |
| SHA-256 | 3a8c8349ce691a4ef05e314afc034ad82f4dbb19415efc7442af5ea075d5e797 |
| Download verification | Exact official registry URL; downloaded bytes match registry SHA-256; ZIP CRC PASS; no installation/import/binary execution |
| License | Registry MIT metadata and bundled LICENSE.txt inspected; MetaQuotes copyright 2000–2025; preserve notice if later adopted |
| Dependency | Wheel METADATA declares numpy>=1.7; no dependency/lock modification in this sprint |
| Python/architecture | cp313-cp313-win_amd64 wheel; metadata Python>=3.6,<4; Windows x64 Python 3.13 packaging compatibility, not empirical terminal proof |
| Publishing provenance | Registry reports no Trusted Publishing; registry hash is not an independent binary security audit |
| Vulnerability/compatibility limit | Full adoption audit and actual selected Exness terminal compatibility remain later gates; no absence-of-bugs/security claim |

Decision: **SDK NOT ADOPTED, INSTALLED OR IMPORTED**. Use the complete fixed synthetic
transport/process boundary for this public sprint. No unofficial credential wrapper.
A later actual adapter decision needs current package hash/notice/dependency audit,
terminal compatibility proof, PRIVATE return and independently accepted onboarding.
The inherited locked dependencies remain the audited project dependencies.

Local-only downloaded wheel/metadata/receipt are retained as review evidence outside public
source. No real account, server assignment, login, credential or broker session was used.
