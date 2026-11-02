# Phase 6A1 inherited dependency security remediation

Date: 2026-10-27. Scope: filelock 4.2.0 -> 4.2.1 only, plus generated audit-export hashes.
The consolidated engineering brief authorizes ordinary same-run remediation and full
inherited verification; no security/audit gate was skipped or weakened.

The initial hash-required locked audit found six filelock advisories:
CVE-2026-112906/GHSA-2g95-wg33-c5x2,
CVE-2026-112940/GHSA-v4x8-3wr5-3wq8,
CVE-2026-112914/GHSA-crv4-6mhj-j5jh,
CVE-2026-112913/GHSA-9vhv-jxww-xfm5,
CVE-2026-112937/GHSA-jqc4-5cvw-7w85,
CVE-2026-112907/GHSA-567q-5qvw-pf92.
All named 4.2.1 as fixed; verified against the [maintainer release](https://github.com/tox-dev/filelock/releases/tag/4.2.1)
and [maintainer advisories](https://github.com/tox-dev/filelock/security/advisories).

No new dependency was introduced. This existing transitive build/development dependency
remains non-financial tooling; no age-only upgrade, broker library or paid service.
The 71-package lock diff changes filelock alone; uv.lock and requirements-audit.txt retain
exact versions/hashes. The fixed hash-required audit reports no known vulnerabilities.
The existing separate Development venv received only the hash-verified fixed wheel;
no venv recreation/sync, shared/base Python write or operational environment mutation.
Original failed audit and fixed reports remain ignored/local for reviewer inspection.
Review with this exact implementation SHA, or at the next dependency adoption/security
notice; inherited maturity review due 2026-11-16 remains unextended.

## PR #10 scheduled-runtime security remediation

Independent review of exact 9e330e00384d4e22bfa09e9fdc7f6fb125fd6c05 identified a material
persistent-secret defect: scheduled collection relied on an interactive plaintext process
environment value. The remediation removes that production dependency entirely and uses
only a fixed-purpose Windows DPAPI CurrentUser store outside Git checkouts, restrictive
ACL/path handling and a non-echo owner tool. Decryption follows all early authority/build/
clock gates and precedes database connection. Missing/corrupt/wrong-user secrets fail
closed generically; tests inject a loader explicitly, never a production fallback.

Dedicated OI database attestation now rejects foreign manifests, checkpoints, events and
source-review rows instead of trusting the database name alone. No schema/migration or
financial permissions change. The [runtime commissioning contract](OI_RUNTIME_DEPLOYMENT.md)
requires a third pinned checkout and independent Python/database/recovery proof before
separate START. Real deployment, persistent secret provisioning, task registration, endpoint
calls and calendar credit remain absent. The narrow filelock 4.2.1 fix above is preserved;
no DPAPI dependency, broader upgrade or source-rights/statistical change is introduced.
Actual native disposable DPAPI and inherited verification receipts are reported with the
final corrected exact SHA; no hosted PASS is inferred from local evidence.
