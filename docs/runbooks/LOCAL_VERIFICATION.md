# Local verification

Run everything from the Development checkout. Never from the Operational or OI Runtime
checkouts. See [checkouts and tasks](CHECKOUTS_AND_TASKS.md).

## Environment

Development owns its interpreter (CPython 3.13.16 under `.local\python`) and the pinned
uv 0.13.1 (`.local\toolchains\uv-wheel\uv-0.13.1.data\scripts\uv.exe`). To rebuild the
virtual environment, set these for the session and run uv from the checkout root:

```text
UV_PYTHON_INSTALL_DIR=.local\python
UV_CACHE_DIR=.local\uv-cache
UV_PYTHON_DOWNLOADS=never
UV_LINK_MODE=copy
UV_NO_CONFIG=1

uv venv --python .local\python\cpython-3.13.16-windows-x86_64-none\python.exe .venv
uv sync --locked --group provider
```

Copy mode matters: the DS-03 provider binding refuses hard-linked package files. The
`provider` group holds the Windows-only MetaTrader5 and NumPy pins that only the isolated
read-only provider child imports; without it, a plain `uv sync --locked` removes them and
the native exact-package tests fail. Never point Development at the Operational
interpreter or virtual environment.

## Every change

```text
.venv\Scripts\python.exe -m ruff format --check src tests tools migrations
.venv\Scripts\python.exe -m ruff check src tests tools migrations
.venv\Scripts\python.exe -m mypy
.venv\Scripts\python.exe tools\run_tests.py -q -m "not integration"
node tools\check-docs.mjs
.venv\Scripts\python.exe tools\secret_scan.py
git diff --check
```

The non-integration suite includes the native Windows proofs (DPAPI, ACL, Job Objects,
process identity, exact provider package) that hosted Linux CI skips. Do not pass
`-p no:cacheprovider`; the runner relocates the cache itself.

Frontend, in `web\operator-terminal`:

```text
npm ci --ignore-scripts --no-fund
npm run typecheck
npm run lint
npm test
npm run build
npm audit --audit-level=high
```

## PostgreSQL-backed tests

Tests marked `integration` need PostgreSQL 17. Run them, and the whole suite, only
against a throwaway cluster:

```text
.venv\Scripts\python.exe tools\disposable_pg.py test -q
.venv\Scripts\python.exe tools\disposable_pg.py test -q tests\test_postgres.py
.venv\Scripts\python.exe tools\disposable_pg.py run -- .venv\Scripts\python.exe tools\verify_paper_recovery.py
```

The tool creates a cluster in a new directory under the user's temp folder, on a random
port that is never 55432 or 55433, with a random superuser password and a server marker
(`auvexo.disposable_cluster` plus a start-only `cluster_name`). It passes the port and
marker to the tests through `TEST_PG_PORT` and `TEST_PG_CLUSTER_ID`, and destroys exactly
that directory afterwards, whether the tests pass or fail. Every test helper refuses the
two reserved ports and checks the marker before writing. Without the tool, integration
tests fail with "Disposable PostgreSQL test cluster required". The full suite takes about
25 minutes; keep it outside the protected windows.

Hosted CI runs the same suite on every pull request to `main`, in a container on port
45432 with a per-run marker. A pull request is not verified until that run has passed on
its exact head commit, with real steps: check the step list and the pytest summary line,
not only the green mark.

## Before any public push

```text
gitleaks git . --config .gitleaks.toml --redact --staged
gitleaks git . --config .gitleaks.toml --redact
```

Also read the staged diff for anything that identifies the machine, the user account or a
broker account. Public copies cannot be withdrawn.

## Fresh clone

To prove that the committed source alone is sufficient: clone the exact commit into a new
directory, create a new virtual environment, install with
`pip install --require-hashes -r requirements-audit.txt`, install the project without
dependencies, then run the checks above. A fresh clone must end with a clean tree.

## What local checks do not prove

They do not prove operational evidence, source rights, provider compatibility, clock
quality, profitability or any live readiness.
