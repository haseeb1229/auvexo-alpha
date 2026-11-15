# Binance DS-01 / DS-02 rights renewal, 2026-11-14

> Dated record. The current state is in [STATUS](../STATUS.md).

## Owner decision

On 2026-11-14 at 23:07 Asia/Karachi the owner chose option **R1** of the
[owner packet](BINANCE_DS01_DS02_RIGHTS_OWNER_PACKET_2026-11-13.md), in these words:

> R1 — renew both DS-01 and DS-02 for the existing Auvexo Alpha scope only: personal,
> non-commercial, non-production research.
>
> I accept the documented DS-02 residual ambiguity described in the owner decision packet
> for this narrow research use. This does NOT authorize redistribution, commercial use,
> live execution, real-money trading, or any broader Binance entitlement.
>
> Set the next review date to 2027-02-16, with an earlier review if the relevant Binance
> terms change.

## What changed in code

`src/auvexo_alpha/domain/source_reviews.py` now holds every owner-confirmed review, oldest
first. The registry returns the review in force at a given instant.

| Source | Prior review (kept byte-identical) | New review |
| --- | --- | --- |
| DS-01 | `review.2026-10-17.v2`, 2026-10-17 to 2026-11-16, Vision terms `99c4921d…14ee0` | `review.2026-11-14.v1`, 2026-11-14T18:07Z to 2027-02-16, same Vision terms hash, CC BY-NC-SA 4.0 |
| DS-02 | `review.2026-10-16.v1`, 2026-10-16 to 2026-11-16, `bf487971…77f7` | `review.2026-11-14.v1`, same window, Terms of Use PDF `f7c3c8a8…c7de`, NOT_AUTHORIZED redistribution |

Scope is unchanged: permitted use `PERSONAL_NONPRODUCTION_RESEARCH`, the same
redistribution value per source, the same retention text. Evidence URLs now name the
retrieved Terms of Use PDF and the Prohibited Use Policy.

Two behaviours follow, both tested in `tests/test_source_reviews.py`:

- **Collection** labels data with the review in force when it was received, and refuses
  once no review is in force. After 2027-02-16 both sources refuse again.
- **Research** may use data received under the prior review only while a later recorded
  review with exactly the same use, redistribution and retention is in force. A forged,
  unrecorded or widened record never continues.

The pinned Operational release is not changed. It still expires on 2026-11-16 and only a
re-pin to a release containing this change brings the renewal into operation.

## Next review

2027-02-16, or earlier if any of the referenced Binance documents change.
