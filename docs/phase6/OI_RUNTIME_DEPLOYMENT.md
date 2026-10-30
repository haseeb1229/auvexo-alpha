# OI runtime commissioning contract

Status: commissioning requirements retained; 2026-10-29 founder-authorized readiness
hardening fixes the production DB identity and three CurrentUser slots as described in
the [readiness correction](OI_COMMISSIONING_READINESS.md). Real commissioning/START
requires separate authorization, independent implementation acceptance and native clock trust.
Date: 2026-10-28 Asia/Karachi. This document provisions nothing and grants no START.
PR #10 implementation remains OPEN/UNMERGED pending independent exact-SHA acceptance.
Accepted source/feature design remains 887b6ac38636e07ff922d2ba2d0ec7b2063edd4f;
[OI-FWD-v1](EXPERIMENT_PREREGISTRATION.md), [rights](SOURCES_AND_RIGHTS.md) and OI-16
are unchanged. Current PHASE6_FORWARD_CLOCK=ZERO.

## Dedicated pinned runtime source

After executable implementation acceptance and verified merge only, create the third
checkout at `C:\Users\AR TRADERS\Desktop\Auvexo Alpha OI Runtime`, pinned to the exact
independently accepted implementation release/merge tree. Record the exact commit/tree,
source/build/lock/preregistration hashes, clean Git state and reviewed configuration.
Do not create that checkout during PR #10 remediation.

The OI campaign MUST NOT execute from either existing checkout:

- `C:\Users\AR TRADERS\Desktop\Auvexo Alpha`: immutable Phase 2/4 operational release,
  pinned at 9b9038b; no OI writes, tests, installs, DB/service/task/config/activation changes.
- `C:\Users\AR TRADERS\Desktop\Auvexo Alpha Development`: mutable engineering source,
  unsuitable for an active 90-day campaign because code/config/build changes break pinning.

The third checkout is runtime-only, clean and never a development workspace. No pull,
checkout, package sync, self-update or code mutation during the fixed study. Reviewed
same-evidence continuity/config updates preserve the original study ID/T0/window and
must follow their explicit external acceptance; they do not authorize source updates.
Any required code change pauses admission for separate review without rewriting evidence
or manufacturing a fresh study ID to reuse confirmation observations.

## Independent Python and immutable dependencies

Before START prove the runtime venv and its base interpreter are independently owned in
this OI runtime or a dedicated immutable toolchain location. Resolve the venv base path,
executable paths and hashes; neither base nor environment may depend on files under the
Phase 2/4 operational checkout or mutable Development checkout. Use accepted Python and
hash-pinned dependencies, including filelock 4.2.1; do not recreate or alter operational
Python. Record installed/locked equality and a clean build-binding proof. No paid service
or GPU is required. The existing pinned `psutil==7.2.2` is an explicit runtime dependency
for fail-closed resource measurement; DPAPI adds no dependency.

## Dedicated persistent PostgreSQL

Future OI persistence requires a separate PostgreSQL 17.11 accepted immutable toolchain,
bound only to 127.0.0.1:55433, unless an exact reviewed nonconflicting replacement is
accepted. Use its own persistent data directory and service/process identity; never
reuse, start, stop, repair, connect to or share the operational 55432 instance or volume.
The production database is exactly `auvexo_dev_oiresearch`, with port exactly `55433`
bound into the reviewed config hash/START. The collector and task have no independent
database/port override. A different production target needs separately reviewed scope.
Prove the actual server address/port, dedicated name and current migration head 0005
under the accepted release, with all immutable data-table grants/triggers preserved.
Do not create the persistent server/database/data directory in this remediation.

Use distinct randomly generated admin, app and data-writer secrets, handled in-process
and protected with owner-current-user OS encryption under separately reviewed purposes.
Never print, serialize on a command line or put them in plaintext files/environment.
The collector's sole database identity is `auvexo_data_writer`, inheriting only required
`auvexo_ingest` privileges; no superuser, CREATEDB or CREATEROLE. Foundation state stays
execution_enabled=false; the collector receives no financial tables, policy writes,
permit, order or money authority. Administrative provisioning is separate from collection.

Before START attest every generic data table as OI-only: exact DS-04-A1 manifests,
checkpoint keys, allowed event namespaces/payloads and accepted base/same-evidence review
rows. Unknown/foreign rows cause OI_DEDICATED_DATABASE_REQUIRED without deletion or
silent ignoring. A database-name prefix alone is insufficient dedication evidence.

## Scheduled-runtime database secret

All three fixed purposes and KnownFolder-relative paths are listed in the
[readiness correction](OI_COMMISSIONING_READINESS.md). Admin/app owner APIs are separate
from the collector. The collector password is loaded only by the narrow [OI secret module](../../src/auvexo_alpha/infrastructure/oi_secrets.py),
using Windows DPAPI CurrentUser, UI forbidden and exact OI database-password purpose.
Its deterministic encrypted location is under the current owner's LocalAppData, outside
all Git checkouts; fixed-purpose entropy and restrictive Windows ACLs defend its boundary.
Use the same Windows owner identity as the future InteractiveToken task. Machine-wide
DPAPI, alternate-user recovery, arbitrary secret names/paths and plaintext exports are
prohibited. Windows-user compromise remains a residual risk; no broker secret manager
or general account credential facility is introduced.

The [owner secret tool](../../tools/oi_secret.py) obtains store/rotation input through
non-echo interactive input. Verify reports decryptability only; delete/revoke is explicit.
There is no secret CLI argument, task XML credential, config-file secret, environment
fallback, interactive collector prompt or automatic plaintext/synthetic production backend.
Missing, corrupt, wrong-user or failed OS protection returns a generic unavailable code.
Before START prove native store/verify/load/rotation/delete behavior using a disposable
synthetic secret, separately from provisioning any real future writer credential.

Before decryption, the collector checks that collection is enabled and the launch is
scheduled, outside protected windows and timely. It also verifies source rights,
independently accepted START, the exact clean build, trusted clock and database scope.
Decryption precedes the first database connection.
Unauthorized/manual launches must not even decrypt the persistent writer credential.
No real future OI password is stored by this PR correction.

## Recovery and continuity proof before START

The later commissioning record must prove clean OI-server shutdown/start and bounded
backup/restore or equivalent same-machine recovery appropriate to this nonproduction study.
Retain immutable source/manifest/ledger hashes and externally accepted review records;
verify restored rows, artifacts, role privileges, build pinning and clock/source rights.
Backups and distinct administrative secrets require protected storage and explicit access.
There is no plaintext secret export or automatic recreation if the DPAPI blob is missing.

After destructive recovery, leave the task disabled pending explicit review. Never
silently clear unknown transport outcomes/cooldowns, repair qualification receipts,
backdate acquisition or catch up missed hourly slots. Preserve explicit gaps and the
original fixed study window. Missing secret or trust proof fails closed; restoration
never creates owner START, review acceptance, calendar credit or financial capability.

## Future task binding and final START gate

Only after independent implementation acceptance/merge and separately authorized
commissioning may a task definition bind all of:

- Pinned third-checkout Python/base runtime and collector script, owner InteractiveToken,
  LeastPrivilege and exact reviewed build/config hashes.
- Exact owner START envelope and externally accepted digest, immutable source/rights/
  preregistration/review-chain inputs, dedicated database name/port and storage roots.
- Hourly slots with protected-window exclusion, staggering, one instance, finite resource
  budgets, no wake, no catch-up and no secret argument or environment dependency.

Rendering XML grants no activation. A future task remains disabled until explicit later
START authorization. This remediation creates no runtime checkout, persistent OI server,
real secret, task registration/enablement, owner START or accepted START digest. It calls
no Binance endpoint and earns zero forward days. Source/value/operational gates remain
open; OI-FWD predictability cannot satisfy the canonical Phase 6 incremental-value exit.
