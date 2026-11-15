# Binance DS-01 / DS-02 rights: owner decision packet, 2026-11-13

> Dated record. The current state is in [STATUS](../STATUS.md). This packet describes what
> the documents say. It is not legal advice and it decides nothing. Only the owner can
> confirm a rights review.

## Decision needed and deadline

The rights reviews for DS-01 (Binance Vision spot archives) and DS-02 (keyless spot REST
market data) are compiled into the code with `review_due = 2026-11-16T00:00Z`, which is
05:00 on 16 November in Pakistan. From that instant both sources refuse, by design.

The owner chooses one of:

| Option | Effect |
| --- | --- |
| **R1. Renew both, scope unchanged** | Personal, non-production research only; no redistribution; DS-01 under CC BY-NC-SA 4.0. A reviewed pull request records the new review version, the evidence below and a new due date. Phase 2 collection and the PAPER campaign can then restart on a new release. |
| **R2. Renew DS-01 only** | Archives stay usable for backtesting. DS-02 refuses, which also stops Phase 2 live collection and the PAPER observation feed, both of which read DS-02. |
| **R3. Renew neither** | Both refuse on 16 November. Research on already-downloaded archives keeps the rights recorded at download time (Vision terms 1.4), but nothing new is collected. |

A renewal is a code change and therefore a new release: it does not reach the pinned
Operational checkout until the owner re-pins. Nothing restarts automatically.

## What was retrieved

All from official Binance sources, fetched 2026-11-13 without signing in or accepting
anything. Hashes are SHA-256 of the bytes retrieved.

| Document | Version or date | SHA-256 |
| --- | --- | --- |
| Terms of Use (PDF embedded at binance.com/en/terms, served from Binance's static CDN) | Effective 27 October 2026 | `f7c3c8a8fbda48eaa272ff503b8c2e54c6c98ad4f0f2a1e5da3667af5962c7de` |
| Prohibited Use Policy | Last updated 5 January 2026 | `3c287bd60863eccef6a16b8580190c96d4c9414931928d7fafdb227bf967cd63` |
| API Keys Product Terms ("API Terms") | Version 2.0, effective 9 July 2026 | `33c4b5249d6f9155e7b2dd5fa1f50b022be1ce933371bf2b301af5f723b14dad` |
| List of Prohibited Countries | Updated 5 January 2026 | `2dead3dd5d9bccb32694e2f0fe5c7f2c6b583e7a6f851296edef7088340e6df5` |
| Exchange Procedures | Undated | `f17508249557e6e94d5a3f319bf5fd30f2b3ccc81b89ade40d0e2cf064cb44b1` |
| Binance Vision Dataset Terms (data.binance.vision PDF) | Version 1.0, last updated 26 August 2026 | `0ec62cd26207f8be17f424d83240f671280ec4b17f7ef9a0026e7b6e0258121f` |
| Same terms, `TERMS_AND_CONDITIONS.md` in binance/binance-public-data | Version 1.0 | `99c4921dbe023cd68c1a447775707d621453cc78aec6ac0bfe2e6c06a5114ee0` |
| Spot API "market data only" FAQ | Last commit 2026-10-15 | `b4aa5cc3f918f9a72c3d055bd4a36d9b8a77c1020cd253458ba573e328cb7997` |
| Spot API REST reference | Last commit 2026-11-11 | `f1500faf7ede9e1b24087e31e3d2517eb56db28f1d936fdfde845ce418ae3ca8` |
| Spot API "Terms of Use" page | Points to the Terms of Use only | `0c1540d4e05fa2bd5bade07a32252f36d9a9403d266de8d2b5dc14339cdcc735` |

**DS-01 terms are byte-identical to the recorded review.** The registry's `terms_hash` for
DS-01 is `99c4921d…14ee0`, the same as the GitHub terms file fetched today.

The HTML pages of the Terms of Use are behind a web-application firewall; the clause text
was taken from the official PDF those pages embed. That gap from the 2026-11-12 review is
now closed.

## Who the contracting party is

The 2026-11-12 brief asserted that Binance moved to an ADGM structure in 2026. The text
confirms the structure, not the date. The Terms of Use are an agreement with three
"ADGM Binance Entities", each regulated by the FSRA of Abu Dhabi Global Market: Nest
Exchange Limited (operator of Binance RIE), Nest Clearing and Custody Limited and Nest
Trading Limited, governed by ADGM law (clause 38). The Vision terms name Nest Exchange
Limited as the dataset provider. No retrieved document dates the change. Whether any
"Local Terms" apply to a resident of Pakistan is not stated; Pakistan is not on the
prohibited-countries list.

## What the text says about the narrow use

### DS-01, Vision archives

- Licence: CC BY-NC-SA 4.0 plus the Vision terms; where both impose an obligation, the
  stricter applies (3.1, 3.3).
- Expressly permitted: "algorithmic historical backtesting for purely personal
  non-production research" (4.1).
- Prohibited: "live proprietary trading execution, automated commercial order generation,
  or signal distribution to third parties for direct or indirect compensation" (4.2);
  hosting or commercially exploiting the datasets (4.3); commercial trading bot platforms
  (4.4). Redistributed derivative works need attribution and the same licence (4.5).
- Rate limits and download protocols must be respected (7.1, 7.2).
- Amendments apply prospectively and do not affect datasets already downloaded (1.4).

This matches the recorded DS-01 scope. One point for the future: 4.2 restricts
"live proprietary trading execution". If Vision-derived research ever informs live
decisions, that clause needs its own review before then.

The repository README says "Licence MIT" while its terms file says CC BY-NC-SA 4.0; the
README does not say what the MIT licence covers. The terms file is the data licence.

### DS-02, keyless REST market data

- The API documentation publishes `data-api.binance.vision` as the base endpoint "for APIs
  that only send public market data", with no API key, and lists klines, time and
  exchangeInfo. Limits are per IP: 6000 request weight per minute; 429 means back off;
  repeated violation leads to automated IP bans from 2 minutes to 3 days.
- No document grants a licence specific to keyless market data. The API Keys terms cover
  keys only. The spot API "Terms of Use" page just points to the general Terms of Use.
- Terms of Use clause 27 grants a non-exclusive licence to use Binance IP "solely as
  necessary to allow you to receive the Binance Services for non-commercial personal or
  internal business use". Binance IP includes database rights.
- Prohibited Use Policy §I prohibits bots, scripts or programs used "to access, obtain,
  copy, monitor, replicate ... Binance Services, except as expressly permitted". §D
  prohibits resale or commercial use without written authorization.
- **The main open point:** the documents do not say whether publishing keyless
  market-data endpoints with rate limits counts as "expressly permitted" under §I. The
  text alone does not resolve it. The project's use is a few units of request weight per
  poll (time 1, klines 2 per symbol), in a short daily window, orders of magnitude below
  the posted limit.
- No clause addresses private storage of market data specifically.

DS-04-A1 (futures open interest, due 2026-11-27) rests on the same Terms of Use and
Prohibited Use Policy, with no futures-specific data licence found.

## What the owner is asked to confirm for R1

1. I have read Terms of Use clauses 27 and 31 and Prohibited Use Policy §I and §D myself.
2. The use stays personal, non-commercial, non-production research. Nothing is
   redistributed, published, sold or used for live execution.
3. I accept that DS-02 rests on the general licence in clause 27 and on the published
   keyless endpoints, without an express data licence, and that §I leaves that open.
4. The new due date. Suggested: 2027-02-16, three months, consistent with earlier
   reviews. Any change to the terms before then triggers an earlier review.

The owner can also choose to contact Binance for written confirmation. This run did not
contact anyone.

## Not verified

Local Terms for Pakistan; the date of the ADGM restructuring; whether REST responses are
"Datasets" under the Vision terms; what the README's MIT licence covers; versions of the
Exchange Rules and Exchange Procedures.
