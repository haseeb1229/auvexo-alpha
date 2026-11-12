# Local verification

Run everything from the Development checkout. Never from the Operational or OI Runtime
checkouts. See [checkouts and tasks](CHECKOUTS_AND_TASKS.md).

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

The 500-odd tests marked `integration` need PostgreSQL 17 on loopback port 55432. On this
laptop that port belongs to the Operational cluster, so do not run them locally. Hosted
CI runs them on every pull request to `main` in an isolated container. A pull request is
not verified until that run has passed on its exact head commit, with real steps: check
the step list and the pytest summary line, not only the green mark.

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
