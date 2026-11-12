# Phase 2 DS-03 actual MT5 read-only adapter: independent review

Reviewer: Claude, acting as the founder-requested independent auditor (2026-11-12).
Reviewed input: PR #12 at exact head `68dd54ad920fcbdf4375d813c6124e03ef8c7233`,
tree `14f1119491df012dc55287b696c76afa483dc93e`, base
`fa0915130c9572c9c2a4a260b20abeaefc2c62f5`; 3 commits, 47 changed paths.

Disposition: **ENGINEERING ACCEPTED WITH CORRECTIONS**. The reviewed head is not accepted
as it stood. The corrected head, once its exact-commit verification below is complete, is
accepted as generic read-only adapter engineering only. No actual account, session,
credential, source, rights, terminal or history qualification is granted, and no trading
authority of any kind.

Earlier PASS reports for this PR were treated as claims. Nothing here relies on them.

## Method

- Read every changed source file from base to head, and the frozen
  [ADR-029](../adr/029-ds03-mt5-readonly-adapter.md) and
  [requirements](../phase2/DS03_ACTUAL_ADAPTER_REQUIREMENTS.md) they implement.
- Ran native probes on the Windows host: a real child process under the exact production
  environment, a static import-closure computation, and exact installed-package
  verification. No SDK initialize, login or terminal launch occurred. No production
  credential path was called.
- Verified provider facts from official sources on 2026-11-11/12 rather than from memory.

## Defects found and corrected

| ID | Severity | Finding | Correction |
| --- | --- | --- | --- |
| R12-1 | HIGH | The provider child receives only `SYSTEMROOT` and `WINDIR`. `Path.home()` cannot resolve there, so the fixed runtime root raised and the child exited before admission. The production composition could never start. Tests replaced the launcher or the home lookup, so they passed. | Owner profile derived from the process token (Windows known-folder API). Native tests run a real child with the production environment and with poisoned home variables. |
| R12-2 | MEDIUM | `connector_source_hash` omitted four package `__init__.py` files that the child executes; the synthetic binding had the same gap. A hash that omits executed code is not an artifact binding. | Both inventories extended; an AST import-closure oracle checks them in both directions. |
| R12-3 | MEDIUM | The M5-08 static capability proof covered only synthetic files. Nothing statically pinned the SDK calls in the actual adapter. | Three static tests: SDK handle used only as a direct call to the fourteen ADR-029 functions; typed stub exposes exactly those; no trade, selection, subscription, login, dynamic-dispatch call or network import in the actual adapter sources. |

Fail-closed behaviour made R12-1 safe rather than dangerous, but an adapter that cannot
run is not what the earlier reports described.

## Properties verified in source

- The only SDK import site is the verified loader in `infrastructure/ds03_mt5.py`. It
  refuses off Windows, refuses if the module is already loaded, and checks installed
  bytes before and after import.
- Every SDK use is a fixed attribute call. There is no `order_send`, `order_check`,
  `symbol_select`, `market_book_add`, `login`, `getattr`, `eval` or `exec` in the adapter.
- `initialize` is called once, with explicit fixed path, login, password, server,
  5000 ms timeout and `portable=True`. There is no no-argument form, discovery, last
  account or second attempt.
- A read is admitted only when the account is DEMO, login/server/currency/leverage match
  encrypted owner metadata, the terminal is connected, account and terminal trading are
  both false, terminal path and data path equal the fixed portable directory, and the
  terminal process is the unique fixed image inside the session Job. This is re-checked
  before and after every read; any mismatch shuts the session down.
- The SDK is not treated as a security boundary. The layers are the broker's read-only
  password, the observed trade-disabled flags, the closed allowlist, and process
  containment.
- The password travels from DPAPI to `initialize` inside the child only. It is absent
  from argv, environment, pipes, metadata, authority, logs, errors and reprs.
- IPC frames are canonical JSON, at most 64 KiB, HMAC-authenticated, bound to session,
  sequence, request identifier and protocol family, with replay refused.
- Range requests must end at or before their creation time and align to the timeframe,
  so an unclosed bar cannot be returned. Missing intervals become explicit unknown gaps.
- No tool or command creates an authority, a secret or an actual session.
  `tools/ds03_connector.py` drives the synthetic child only.
- The installed `MetaTrader5` 5.0.6231 payload on this host matches the pinned file
  hashes, and PyPI reports the pinned wheel hash for the CPython 3.13 Windows x64 wheel.

## External facts checked (official sources, 2026-11-11/12)

- MetaTrader5 5.0.6231 is the latest PyPI release (uploaded 2026-09-27), Windows x64
  wheels only, no source distribution, MIT, no provenance attestation.
- MQL5 documents that `initialize()` without arguments finds a terminal automatically
  and uses the last account with saved credentials. The adapter never calls that form.
- Exness documents the read-only password as view-only with trading disabled.
- The Exness (SC) and (VG) Client Agreements dated 24 July 2026 contain clauses that
  restrict collecting or storing quotes other than for the client's own trading and
  restrict software that automates obtaining platform information. See ADR-030.

## What this review does not establish

Recorded in [ADR-030](../adr/030-ds03-adapter-independent-review-corrections.md) as
onboarding preconditions: source rights, server-time basis, digest privacy, authority
independence, demo continuity, provider compatibility under containment, refusal
diagnosability and third-party runtime bytes. Each denies qualification until a PRIVATE
onboarding ADR resolves it with evidence.

## Verification of the corrected source

Local Windows host, working tree containing the corrections:

- Focused DS-03 and boundary tests: 512 passed.
- Full Windows non-integration suite: 2238 passed, 1 Linux-only skip, 519 integration
  tests deselected (they require PostgreSQL and run in hosted CI).
- Ruff format and lint clean; strict mypy clean on 97 source files.

Exact-commit hosted results, commit identifiers and the merge are recorded in the
repository-wide rebaseline audit dated 2026-11-12, which is added after this merge
because a commit cannot contain its own identifier or its own CI result.
