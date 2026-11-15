# Rights review

Every source has a rights review with an expiry enforced in code. When it expires the
source refuses, by design. A package licence, a public endpoint or a working connection
grants no data rights.

| Source | Scope | Review due | Enforced in |
| --- | --- | --- | --- |
| DS-01 | Binance public spot archives (data.binance.vision), BTCUSDT and ETHUSDT | 2027-02-16 ([renewal](../reviews/BINANCE_DS01_DS02_RIGHTS_RENEWAL_2026-11-14.md)) | `src/auvexo_alpha/domain/source_reviews.py` |
| DS-02 | Binance public spot REST klines, same symbols | 2027-02-16 | same file |
| DS-04-A1 | Binance USD-M futures current open-interest snapshot, same symbols | 2026-11-27 | `src/auvexo_alpha/domain/open_interest.py` |
| DS-03 | Exness MT5 demo, read-only | not accepted | authority contract; see [ADR-030](../adr/030-ds03-adapter-independent-review-corrections.md) |

## Procedure

1. Fetch the current official terms yourself, from the provider's own site. Record the
   URL, the version or date, and a hash of what you read.
2. Compare with the recorded review: permitted use, storage, redistribution, automation,
   retention. Personal, non-production research is the only use ever claimed.
3. If anything is narrower than before, stop and record it. Do not extend.
4. If unchanged, append a new review record (version, review instant, due date, evidence
   URLs and hash) to `domain/source_reviews.py` in a reviewed pull request. Never edit or
   remove an earlier record: stored manifests embed it.
5. Update [STATUS](../STATUS.md).

A renewal is a code change. For a pinned operational release it means a new release, and
for the PAPER campaign a new campaign identity.

## Findings from the 2026-11-12 review

- Binance Vision dataset terms, version 1.0 dated 2026-08-26: CC BY-NC-SA 4.0, personal
  non-production research and historical backtesting permitted, live trading use and
  commercial exploitation prohibited. Consistent with the recorded scope for DS-01.
- The Binance general terms of use could not be retrieved by automation. DS-02 and
  DS-04-A1 depend on them. The owner must read and confirm before renewal.
- The Exness client agreements dated 24 July 2026 contain clauses restricting collection
  and storage of quotes and automated access to platform information. DS-03 rights are
  unresolved and need an owner legal decision.

## Owner packets from 2026-11-13

- [Binance DS-01 / DS-02](../reviews/BINANCE_DS01_DS02_RIGHTS_OWNER_PACKET_2026-11-13.md):
  the general terms of use are now retrieved (official PDF, effective 27 October 2026);
  DS-01 terms unchanged by hash; DS-02 has no express keyless-data licence. Decision due
  before 2026-11-16 00:00 UTC.
- [Exness DS-03](../reviews/DS03_RIGHTS_OWNER_DECISION_PACKET_2026-11-13.md): still
  unresolved; the API terms could not be retrieved.

Automation must not contact a provider, accept terms or decide a legal question.
