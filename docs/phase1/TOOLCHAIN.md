# Phase 1 toolchain, compatibility and third-party notices

Adoption checked 2026-10-16. One Python dependency system: uv and its hash-bearing lockfile.
Runtime dependencies serve implemented diagnostics/contracts/persistence only. Build backend
is also in the development lock/audit to avoid an unaudited isolated-build dependency.

| Component | Pin | Purpose / license |
| --- | --- | --- |
| CPython Windows x64 | 3.13.16 | Supported 3.13 line; PSF |
| uv | 0.13.1 | Local Python/install/lock/build; MIT OR Apache-2.0 |
| PostgreSQL Windows x64 | 17.11 | Native transactional test target; PostgreSQL License and bundled notices |
| FastAPI / Starlette | 0.143.2 / 1.8.0 | Minimal HTTP diagnostics; MIT / BSD-3-Clause |
| Pydantic / core | 2.14.1 / 2.50.1 | Single strict contract definition; MIT |
| SQLAlchemy | 2.0.54 | Established 2.0 line, bounded connection pool; MIT |
| Alembic | 1.20.0 | Versioned real DB migration; MIT |
| psycopg / binary | 3.3.6 | Windows CPython/PostgreSQL driver; LGPL-3.0-only, bundled library notices |
| Uvicorn | 0.54.0 | Local ASGI server; BSD-3-Clause |
| Hatchling | 1.32.4 | Package build backend; MIT |
| pytest | 9.1.1 | Unit/integration negatives; MIT |
| Hypothesis | 6.169.4 | Decimal and untrusted payload properties; MPL-2.0 |
| Ruff | 0.17.1 | Formatting/lint; MIT |
| mypy | 2.4.0 | Strict production/migration typing; MIT |
| httpx2 | 2.13.1 | Current Starlette test client; BSD-3-Clause |
| pip-audit | 2.10.1 | Public advisory lookup; Apache-2.0 |
| psutil | 7.2.2 | Actual Windows process measurements; BSD-3-Clause |
| Node | 24.20.0 | Existing dependency-free document checker; MIT and bundled notices |
| Git / GitHub CLI | 2.55.0.windows.5 / 2.102.0 | Existing developer tools; GPL-2.0 / MIT |
| Gitleaks | 8.30.1 | Existing independent source/history scanner; MIT |

Python 3.13 was selected for mature Windows wheels, not newest-language features. Official
[Python releases](https://www.python.org/downloads/windows/) and
[support lifecycle](https://devguide.python.org/versions/) were checked. Future MT5 binary
compatibility is packaging evidence only: [MetaTrader5 5.0.6231](https://pypi.org/project/MetaTrader5/5.0.6231/)
publishes a cp313 Windows x64 wheel. MT5 was not installed, imported, connected or tested;
terminal/vendor compatibility remains OD-02/03 and cannot be inferred from the wheel.

[PostgreSQL version policy](https://www.postgresql.org/support/versioning/) and
[Windows distribution page](https://www.postgresql.org/download/windows/) identify the
supported 17 line and EDB distribution. SQLAlchemy 2.0 is used rather than adopting the new
2.1 line for this small adapter. Real tests, not version numbers alone, establish this stack's
foundation compatibility. [Starlette's current test-client documentation](https://starlette.dev/testclient/)
requires httpx2 for warning-free current use; the initial legacy httpx selection was corrected
without suppressing deprecation warnings. No unused quant/ML/broker packages are installed.

## Provenance and reproducibility

uv's Windows wheel came from PyPI's official package files, SHA256
`4f693cd4feb52f08f30474c4612f24be2050472609be65b9960b635f286da284`.
Python came from uv's managed distribution. All resolved package wheels/sdists are pinned
and hashed in [uv.lock](../../uv.lock); bootstrap pins the manager and interpreter patch.
See [uv installation documentation](https://docs.astral.sh/uv/getting-started/installation/).

The EDB PostgreSQL archive is 340,719,294 bytes, observed SHA256
`6eabdf00d2893713b75db4336a23c3fdf505f056e217ec6e2e95d901750cfea3` from the official HTTPS
distribution URL in bootstrap. This is a recorded download hash, not a claim that an
independent signed vendor checksum was verified. Bootstrap enforces that observed artifact
for repeat installs. EDB's server/binary bundled licenses remain with the extracted toolchain.

GitHub Actions are pinned to exact commit SHAs, have `contents: read`, disabled checkout
credential persistence and a 15-minute job timeout. The PostgreSQL service uses exact 17.11
version and immutable official-registry manifest digest
`sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3`. Local
Windows real-DB proof uses the fixed archive hash. CI uses ephemeral synthetic credentials,
no repository secrets, deployments, external account access or paid runtime services.

## License and advisory review

[Installed dependency inventory](DEPENDENCIES.json) records exact runtime/dev/build package
versions, upstream metadata licenses and official PyPI links, including transitives. Metadata
is evidence rather than a legal opinion. All installed entries have recognized license
metadata; no code was copied from a third-party project. Retain installed distribution
LICENSE/NOTICE files. PostgreSQL and Python/uv archives also retain their notices.

Unmodified psycopg is dynamically imported; its LGPL and bundled binary library obligations
must be reviewed again before redistribution. MPL packages (Hypothesis/certifi/pathspec) and
dual-license/PSF/BSD/Apache/MIT transitives retain upstream notices; no vendor files were edited.
This private source repository does not redistribute their wheels/binaries. Any future public
bundle, modified dependency or broker SDK needs a fresh distribution/terms review. Conditional
`httpx2-jsfetch` is lock-resolved only for Emscripten and not installed on Windows/Linux; browser
runtime is outside Phase 1 and would require separate adoption review.

The full current-platform hash-locked dependency set is audited with pip-audit; results and
count are in [verification](VERIFICATION.md). No known advisories is time-specific, not proof
of absence of vulnerabilities. Re-audit at review/adoption; do not silently suppress findings.
