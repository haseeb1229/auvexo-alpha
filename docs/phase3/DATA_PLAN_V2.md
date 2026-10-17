# Phase 3 data plan V2: explicit provider unavailability

Frozen protocol amendment dated 2026-10-18 under the owner-supplied
[resume brief](../reference/PHASE_3_RESUME_BRIEF.txt). Parent [DATA_PLAN V1](DATA_PLAN.md)
is preserved byte-for-byte with SHA-256
`82d189d51b01457e8141455d02addafcdbd690e8a73f4f4996eefcc7fbd2b8a4`.
No OOS/holdout was opened, no hypothesis result was calculated/inspected, no strategy
threshold/parameter was changed before this amendment. The first acquisition stopped at
the March 2023 coverage gate, before any 2025 input was acquired for this study.
Two pre-existing Phase 2 timestamp-qualification partitions cover January 1, 2025 only;
both end January 2, before the sealed January 3 OOS start. They are not study OOS reads.

Only data-availability treatment changes. All V1 ranges, budgets, two hypothesis families,
72/168h breakout and 24/72h mean-reversion grids, allocation/stops/targets/holding limits,
1/1.5/2 costs, chronological split intent, metrics, selection and candidate screens remain.
V2 is committed before resumed broad acquisition or empirical runs. New unknown gaps stop again.

## Evidence and classification

[Provider/raw diagnosis](evidence/provider-outage-diagnosis.json) records the official URLs,
dated hash-bound fact extracts, separate direct-HTTP limitations, independent issue reports,
checksum-backed original archive identity and one narrow same-provider REST comparison.
The monthly archive has 743 raw March rows, 742 normal accepted hours. Both sources show
that the 12:00 March 24 row
has valid milliseconds but closes at 12:39:41.646 UTC with zero volume/trades, while 13:00
is absent. Neither is a full valid hourly candle. The official provider's physical halt is
11:27-14:00 UTC; a zero-trade row's metadata close does not establish executable trades then.
No price, trade, volume or replacement bar is inferred from the notice.

General categories: COMPLETE, PROVIDER_OUTAGE_CONFIRMED, UNKNOWN_GAP_BLOCKED. A confirmed
outage requires exact source/provider/product/instrument and source-manifest/raw hashes,
bounded unavailable interval, official evidence URL/hash/retrieval/reviewer reference and
raw-byte gap/truncation proof. Unknown units/schema/other gaps stay blocked. Certificates
cannot transfer to another source/instrument or turn DEGRADED into PASS. No other venue,
flat candle, interpolation or forward-fill is allowed. Original raw/manifest bytes remain.

Parser spot.v2 labels valid-unit short intervals TRUNCATED_INTERVAL and other close-boundary
violations INTERVAL_BOUNDARY. TIMESTAMP_UNIT remains for actual unit/open alignment failures.
Exact old spot.v1 replay retains its original semantics; any new parse/publication is a new
parser-version lineage, never an overwrite. No new complete candle is created for a halt.

## Causal simulation and feature rules

An unplanned venue halt becomes physically effective at its start in replay, with no advance
strategy knowledge. Entries before it are evaluated normally. During unavailability there are
no entry/exit/stop/target fills; pending new-entry proposals expire when unavailability becomes
known. Existing spot holdings remain economically open. Last observable marks may be carried
only with STALE_UNAVAILABLE state, never fresh quote/feature/fill authority. Outage exposure
is separately retained. On the first tradable open after resume, a crossed/ambiguous stop uses
the adverse available open or worse stop reference plus the same frozen costs. Stops never
magically execute during a halt. This does not assert real broker/depth execution realism.

Every material price/volatility lookback checks expected wall-clock adjacency and unavailable
interval overlap. Affected features become UNAVAILABLE, then naturally rewarm on complete
post-resume observations. Breakout's original previous-N-hour definition needs N complete
prior hours plus its current decision candle: the existing 24/72/168 settings are unchanged.
No row-count bridging or forward-fill keeps indicators warm. Training medians likewise exclude
windows crossing unavailable time. Publication and earliest fill still obey positive causal lag.

The data-quality evidence is retrospective venue truth, not an alpha feature or invented
contemporaneous news signal. Advance scheduled-maintenance knowledge is a separate future
contract, unimplemented here. Actual 2026 receipts/processing are retained; strict observed-as-of
is unchanged. Final 2025 OOS stays sealed until preregistration, training/validation and
selection/consumption controls are implemented and verified.

No Phase 4, Exness/XAU/CFDs, SDK/account/credential/order, execution enabling or source-rights
waiver. Phase 2 task and all full operational gates remain unchanged and open as applicable.
