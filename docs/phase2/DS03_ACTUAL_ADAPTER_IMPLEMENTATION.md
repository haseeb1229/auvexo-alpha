# DS-03 actual MT5 read-only adapter implementation

Status: ENGINEERING_ONLY; INDEPENDENT_REVIEW_PENDING; NO_ACTUAL_ACCOUNT_SESSION.
Date: 2026-11-03. [Frozen ADR-029](../adr/029-ds03-mt5-readonly-adapter.md),
[requirements](DS03_ACTUAL_ADAPTER_REQUIREMENTS.md), [provider review](DS03_ACTUAL_ADAPTER_PROVIDER_REVIEW.md)
and [runbook](DS03_ACTUAL_ADAPTER_RUNBOOK.md) retain original bytes.

## Accepted predecessor and design freeze

PR11 normal merge fa0915130c9572c9c2a4a260b20abeaefc2c62f5 was verified with ordered parents
f47770d7886d12240e24390e23f939cb49535a31 and f9a860916405a49c875ee07b54c5ea6531675b6e.
Administrative CI41516596112/job125521626311 passed all actual executable steps, 2455 Python
and31 frontend tests; merge/admin tree9a5ea762c3d7e5498440c37f5fc9b0cf5b550123 matched.
The accepted ba66 implementation remains an ancestor; four original DS03 and five OI freezes
are unchanged. New four-file design was committed BEFORE executable code at
aa1c5f4b4f003b660bd1a584647e62093894bb6c, tree07c000754767983436552ded0044ee6aceaea019.
No new acceptance is inferred for this executable PR12 branch.

## Code and interfaces

- domain/ds03_actual.py adds strict actual DTOs, protocol family, digest references, exact
  symbol names, owner-only account-type provenance, raw provider enums, per-record first-seen,
  bar interval identity, millisecond tick fields and explicit provider-time provenance.
  Original domain/ds03.py synthetic constructors/codecs/serialized fields remain unchanged.
- application/ds03.py contains one shared private typed causal session. Fixed synthetic and
  actual wrappers/ports select closed codecs. Application has no SDK/infrastructure imports.
  Catalog paging, rights, pre/post identity, record/batch hashes, overlap, spec/time/deadline,
  duplicate/gap checks and final cancellation gate apply before returning data.
- infrastructure/ds03_mt5.py is the ONLY Windows SDK import site, inside a verified loader.
  Fixed explicit initialize and narrow read calls expose no SDK object or trade dispatch.
  Public verification uses FakeSdk. Exact boolean/integer/finite Decimal(str) mapping and
  float-hex projection hashes preserve source meaning; no account name/comment logging.
- infrastructure/ds03_mt5_process.py is a separate fixed isolated child. Anonymous HMAC pipes
  carry only authority/digest/bindings, never password/raw login/server; no listener or backend/
  executable selector. It composes the strict actual reader and fixed native provider after
  static admission, protected metadata verification and password loading inside the child.
- infrastructure/ds03_mt5_binding.py fixes home-derived runtime/terminal/profile, package
  bytes, source closure, effective interpreter and native process/Job evidence. The child is
  CREATED_SUSPENDED, assigned to the 1GiB kill-on-close Job, then its single primary thread
  resumes. This prevents venv redirector descendants escaping before assignment. Provider
  terminal must belong to the exact fresh session Job, including nested descendants; a
  pre-existing/uncontained terminal cannot be adopted. Its opaque local kernel-object name is
  authenticated in the pipe context; the child opens JOB_OBJECT_QUERY only. It is no listener
  or caller-selected backend. Parent disposal explicitly terminates its owned Job before closing,
  so a transient read-only query handle cannot prolong any descendant. No security-policy change is used.
- domain/ds03_authority.py separates static authority admission from metadata-bound credential
  admission. No authority issuer exists. Separate independent accepted digest, exact release/
  tree/source/runtime/package/terminal/rights bindings, PRIVATE attestation and24h expiry are
  mandatory. Fixed store gates also remeasure current source/package/interpreter/terminal bytes before any native access. Immutable-model bypasses are revalidated. Owner product account type is explicitly
  NOT_EXPOSED_BY_MT5, never guessed from server or suffix.
- infrastructure/ds03_secrets.py and ds03_metadata.py implement the two fixed CurrentUser
  DPAPI slots using accepted native owner ACL/no-follow/hardlink/atomic machinery. OI source,
  slots/purposes/paths/errors are unchanged. Raw account metadata is encrypted and repr-hidden.
  No generic path/vault, env/argv/plaintext/password JSON/log/exception channel is present.

## Dependency and runtime contract

Windows x64-only MetaTrader5==5.0.6231 and NumPy==2.4.6 add exactly two distributions without
changing unrelated locked distributions. Exact official MT5 CP313 wheel SHA256 is
3a8c8349ce691a4ef05e314afc034ad82f4dbb19415efc7442af5ea075d5e797. NumPy is a supported
CP313 maintenance release satisfying the SDK ABI dependency; no new NumPy feature is required.
MIT/BSD notices and native bundled notices are retained. PyPI has no Trusted Publishing/
provenance for the reviewed SDK; package review does not certify the binary or broker rights.
The installed init/core/license files and actual directory inventory are checked; unlisted
code and pyc caches refuse because -B alone does not prevent cached-code reads.

Future runtime is Path.home()/Desktop/Auvexo Alpha MT5 Readonly Runtime; terminal/terminal64.exe,
portable=True, profile=terminal.parent; interpreter exactly .venv/Scripts/python.exe and project
normal wheel in that venv's Lib/site-packages. Effective base Python must reside under the
same runtime's .local/python, with loaded python313.dll beside it. Source binding includes
venv launcher, base executable, loaded Python DLL, pyvenv.cfg, exact sys.version and transitive
project source closure. Static package/source/interpreter/terminal bytes and process/profile
identity are remeasured around reads. No current runtime/terminal installation is performed.
All initialize arguments are explicit: fixed path, exact login/read-only password/server,
timeout5000ms, portable=True. No login switch, discovery or fallback.

## Data semantics and conservative refusals

Exact ASCII nonspace broker names are preserved without suffix assumptions; unsupported Unicode/
space names refuse. Stable catalog is at most4096,128/page; discovery completes before specs/reads.
Reported spread is explicitly MT5_POINTS, never an unlabeled price amount. Spec snapshot retains initial quote fields while static contract projection detects financial
spec drift; quote_at is LAST_QUOTE_TIME, not a claim of specification publication history.
Closed half-open bars are bounded before native call; gaps/history depth remain unknown.
Actual bars bind timeframe independently, including records sharing an open timestamp.
Ticks use count-bounded copy_ticks_from, validate full raw batch then explicitly project to
[start,end); no in-range loss/overflow/ambiguous same-ms/unknown-flag acceptance or complete
coverage claim. Actual account history preserves known raw enums and nonmarket variants;
unsupported/contradictory facts refuse the whole batch. Missing provider event timestamps are
explicitly LOCAL_OBSERVATION_NO_PROVIDER_TIMESTAMP. First-seen is response acquisition time,
never request-start time; overlapping records keep it. Separate historical query scopes permit
older requests without weakening per-record causality or same-query progress checks.
All evidence remains STRUCTURAL_ONLY_CLOCK_BLOCKED with ZERO qualification credit.

## Verification and residual gates

Focused retained/actual contracts, reader, authority, disposable native storage, fake SDK and
actual IPC tests are required alongside full inherited checks. Native tests verify suspended
launcher/base/descendant Job containment,1GiB policy and bounded complete cleanup. Exact Windows
import-only proof loads the reviewed extension with zero initialize/login/shutdown/session calls,
unchanged terminal process inventory and Python process/socket effects denied. Final fresh committed
normal-wheel Windows, twelve isolated native OI PG proofs, hosted full Linux PG/Python/frontend,
strict Windows/Linux types, Ruff/docs/equal agents, lock/audits and full source/history scans
are recorded by exact SHA/tree in the local consolidated handoff and review packet.

PR12 supersedes inert-entrypoint verification: denial/no-effects is exercised at the shared private
admission gate; static tests prove all named production wrappers gate before native access.
Native lifecycle uses IDENTICAL classes in disposable UUID leaves. No production API is invoked
in public verification. Future cleanup deletes password BEFORE metadata because each password
effect verifies persisted metadata; creation checks both slots absent, creates metadata then password.
Python immutable strings cannot promise forensic memory erasure; references are not retained after init.

This branch requires fresh external GPT-5.6 Sol exact-SHA review and remains OPEN/UNMERGED.
Actual terminal compatibility, account/source/spec/history/security/rights qualification remains OPEN.
No actual account session/credential/data, OI DB/secrets/config/task/START or money action occurred.
Operational pin9b9038b and OI Runtime pinf47770d stay unchanged; Phase2/4 genuine credit UNKNOWN,
OI clock externally blocked/forwardZERO; no backfill/catch-up/retime. Four Phase3 results INCONCLUSIVE,
both OOS consumed, no candidate/champion. No Phase5 before fullPhase4 + actualDS03 + owner authority;
Phase6/value/fullPhase7 OPEN; Phase8/9 NOT STARTED. PRIVATE return follows PR12 acceptance before
separately authorized actual onboarding. LIVE_RELEASE_INTEGRITY_CONTROL_REQUIRED_BEFORE_PHASE8.

Native regression note: in this nested Windows environment a NULL Job query reported outer
host flags12288/memory0 while the exact provider handle reported flags8704/1GiB. The failed
receipt is preserved. Exact fresh Job-name/QUERY-only membership replaces ambiguous NULL/any-Job
inference; this is an implementation correction under the unchanged frozen containment contract.
