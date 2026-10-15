# Phase 1 Windows development and recovery

Scope: local synthetic DEV/TEST only. No trading account, terminal, market feed, paid service,
Docker, WSL, global PATH change, Windows service or firewall change is required.
Use PowerShell from the repository, including paths containing spaces. Keep the same Windows
user for setup and checks. Mixing sandbox and owner identities can make test caches unwritable;
an explicit `pytest -o cache_dir=.local/pytest-owner` changes only the cache location.

This machine's default PowerShell policy blocks local scripts. Use the reviewed scripts with
process-only RemoteSigned policy, for example
`powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File tools/dev.ps1 doctor`.
Apply the same invocation to bootstrap and other dev actions below. No persistent user/machine
execution policy is changed; if an organization enforces a stronger policy, obtain its approved
script-signing path instead. The direct Python commands in verification are also available.

## Install

Prerequisites: Windows x64, Git, Node 24.20.0 for document checks, HTTPS access to official
Python/uv/PyPI/EDB release hosts, and unused localhost ports 55432 and 8765. Provisioning uses
approximately 1.1 GiB including archives and caches, before optional clean-clone duplication.

```powershell
Set-Location -LiteralPath 'C:\Users\AR TRADERS\Desktop\Auvexo Alpha'
.\tools\bootstrap.ps1
.\tools\dev.ps1 start-db
.\tools\dev.ps1 migrate
.\tools\dev.ps1 check
.\tools\dev.ps1 doctor
```

Bootstrap verifies fixed SHA256 archives, installs Python 3.13.16 locally through uv 0.13.1,
and synchronizes `uv.lock`. PostgreSQL extraction selects server/client files and notices,
excluding pgAdmin/StackBuilder. If a download/hash check fails, stop and investigate the
official source; do not disable verification. A partial download may be removed manually
from the specifically named `.local/toolchains` archive and retried. No global install occurs.

Expected checks: Ruff format/lint pass, mypy strict pass for production source and migrations,
all pytest tests pass including mandatory real PostgreSQL tests, and docs PASS. Missing DB
setup fails the suite; tests are not silently skipped. `doctor` exits zero only for actual
schema/policy/least-privilege readiness, with `execution_enabled: false`.

```powershell
.\tools\dev.ps1 serve
# In another PowerShell window, use the commands above for doctor/check.
# Stop the foreground server with Ctrl+C.
.\tools\dev.ps1 recover
.\tools\dev.ps1 measure
.\tools\dev.ps1 stop-db
```

The API binds literal 127.0.0.1:8765 only. Its five GET routes are `/api/v1/live`, `/ready`,
`/version`, `/policy`, `/metrics` under that prefix. Every route requires the random bearer
token. No browser UI, OpenAPI HTTP endpoint, public registration or order endpoint exists.
Readiness and liveness differ. `auvexo validate-config`, `health`, `doctor`, `version`, `serve`
are the installed CLI commands; the harness supplies local settings for doctor/serve.

## Credentials and identities

`start-db` creates random local admin/app passwords and a diagnostic token in ignored
`.local/dev-secrets.json`. ACLs are restricted to the invoking Windows account before writing
secret contents; initdb's temporary password file is similarly protected and then removed.
These are development credentials, never broker keys. Do not print them, paste them into a
terminal command/history, commit them, or upload `.local`. An administrator can still access
local files. This is ACL protection, not encryption or a completed production secret store.

`auvexo_admin` owns only this local cluster and runs migrations/recovery. `auvexo_app` is a
non-superuser without create-role/create-database rights and can SELECT the foundation tables.
The API receives only app credentials. No API operation runs migrations or starts PostgreSQL.
No fixture can enable trading. CI uses explicitly synthetic ephemeral service passwords.

Allowed environment keys are explicit in [config](../../src/auvexo_alpha/config.py). Unknown
`AUVEXO_*` keys fail, including execution/account/permit overrides. No automatic dotenv load.
The migration-only DSN is accepted only by Alembic and never passed into application config.
CLI failures report a generic code without input values; SQL parameters and DSNs are hidden.

Future persistent secrets should use Windows Credential Manager/DPAPI under a dedicated
least-privilege service account, with recovery/key access tested. This phase does not implement
that store, WebAuthn, step-up, or live permit signatures. Maintained `py_webauthn`/`fido2` remain
candidates for the separately authorized client/security phase, with release/license review
at adoption; neither is installed. Current authentication uses stdlib `hmac.compare_digest`.

## Migrations and recovery

Revision `0001_foundation` creates only immutable disabled policy and append-only developer
event metadata plus Alembic version identity. No balances/orders/fills/outbox/job tables.
The PostgreSQL server binds 127.0.0.1, uses SCRAM, 64 MiB shared buffers, 20 connections;
app pool is 2 with zero overflow, connect/pool/statement waits are bounded. Server logs rotate
daily or at 5 MiB, using a seven-weekday filename cycle. Under error floods multiple rotations
within a weekday append to that weekday file, so 5 MiB is a rotation threshold, not a hard cap;
monitor the existing Phase 0 storage ceilings and stop investigation workloads before exhaustion.
API access logging is disabled; normal CLI diagnostics write only sanitized stdout.

`recover` creates two unique TEST/RESTORE databases, applies migrations twice, inserts one
synthetic event, verifies destructive downgrade refusal with unchanged data, dumps in custom
format, restores transactionally to the other DB, compares all three tables and checks restored
triggers. It removes only its generated DBs/dump on success, retaining failures for diagnosis.
It never overwrites DEV. A superuser can deliberately bypass SQL triggers; append-only tests
prove ordinary SQL mutation refusal, not tamper resistance against a malicious administrator.

Do not edit a merged migration. Forward-fix in a new revision after backup and compatibility
checks. Destructive downgrade is intentionally unavailable. Recovery means validate an isolated
restore, then choose a documented forward repair; no automatic replacement of source data.
Off-device encrypted backups, broker reconciliation and live recovery remain future closed gates.

## Audits and clean clone

```powershell
$uv = '.\.local\toolchains\uv-wheel\uv-0.13.1.data\scripts\uv.exe'
& $uv export --frozen --all-groups --no-emit-project --output-file requirements-audit.txt
& $uv run --frozen pip-audit --disable-pip --require-hashes -r requirements-audit.txt
& $uv run --frozen python tools/secret_scan.py
node tools/check-docs.mjs
git diff --check
```

`requirements-audit.txt` is a generated audit projection of the uv lock, not a second editable
dependency system. Full Gitleaks 8.30.1 also scans exported tracked/untracked source and history;
use `--redact`, never print matched secret text. Preserve wheel/binary LICENSE/NOTICE files.

A clean clone must have a fresh `.venv` and install the exact lock. It may use the already
verified external toolchain, but must not copy installed site-packages or working-tree code.
Set `TEST_PG_DATABASE` to a newly created `auvexo_test_<suffix>` DB and inject synthetic local
passwords through process environment; migrate the clone's revision there before running all
tests. [Verification](VERIFICATION.md) records the actual commit and commands used.
