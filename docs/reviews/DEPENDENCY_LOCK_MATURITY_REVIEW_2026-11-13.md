# Dependency lock maturity review, 2026-11-13

> Dated record. The current state is in [STATUS](../STATUS.md).

This is the scheduled review of the [current-lock maturity exception](../amendments/DEPENDENCY_MATURITY.md)
(R-018-BA-01, due 2026-11-16). It also covers the secret-scan allowlist review that was due
on the same day.

## Decision

The exception is **renewed unchanged** until the next dependency adoption or 2026-12-16,
whichever comes first, with immediate review on any advisory that affects a locked version.
No version in `uv.lock` changes. No auto-upgrade. No downgrade.

The SC-3 change in this run moves `metatrader5` and `numpy` from the main dependency list
into a `provider` dependency group with the same exact pins and platform markers. That is a
grouping change, not an adoption: the locked versions and hashes are identical.

## Evidence (collected 2026-11-13, lock at main `0617c78`)

| Check | Result |
| --- | --- |
| `pip-audit --disable-pip --require-hashes` on the committed `requirements-audit.txt` (sha256 `df38b48e…7c9f66`), 71 pinned distributions | No known vulnerabilities, 0 skipped |
| GitHub advisory database, advisories published since 2026-06-01 for the direct pins and the main transitive packages | Five packages have recent advisories (starlette, httpx2, anyio, Mako, certifi). Every locked version is outside the affected range: starlette 1.8.0 (affected < 1.3.1), httpx2 2.13.1 (< 2.12.0), anyio 4.15.1 (< 4.14.2), Mako 1.4.3 (≤ 1.4.1), certifi 2026.10.19 (< 2026.10.18). |
| `npm audit --package-lock-only` for `web/operator-terminal`, 150 packages | 0 findings at any level |
| Yanked releases among direct pins | None |

Release age of the direct pins against the newest release on PyPI the same day:

| Package | Locked (released) | Newest (released) | Note |
| --- | --- | --- | --- |
| fastapi | 0.143.2 (2026-10-15) | 0.162.5 (2026-11-11) | Fast release cadence; read-only loopback terminal only. |
| pydantic | 2.14.1 (2026-10-11) | 2.14.3 (2026-11-05) | Patch releases only. |
| sqlalchemy | 2.0.54 (2026-09-15) | 2.1.8 (2026-11-04) | 2.0 remains the maintained line we test. A move to 2.1 is an adoption, not a renewal. |
| alembic | 1.20.0 (2026-09-11) | 1.20.1 (2026-10-22) | |
| psycopg | 3.3.6 (2026-09-18) | 3.3.9 (2026-11-12) | Patch releases only. |
| uvicorn | 0.54.0 (2026-09-25) | same | |
| polars | 2.0.0 (2026-10-06) | 2.1.0 (2026-10-25) | Replay hashes are pinned to the locked version; changing it needs a replay re-verification. |
| psutil | 7.2.2 (2026-01-28) | same | |
| metatrader5 | 5.0.6231 (2026-09-27) | same | Broker SDK. Read-only provider child only. Adoption review stays mandatory before any onboarding. |
| numpy | 2.4.6 (2026-05-18) | 2.5.4 (2026-10-10) | Needed only by the provider child. |
| pytest, hypothesis, ruff, mypy, hatchling, httpx2, pip-audit | | | Test and build tools; newer patch or minor releases exist. None carries a known advisory for the locked version. |

The full per-package table and the raw audit outputs were kept locally and are not in Git.

## Why renewal rather than an upgrade

- No locked version has a known advisory. The reason to move would be age alone, and the
  exception says age is not correctness evidence in either direction.
- The locked set is the one every acceptance in this repository was tested against: the
  PostgreSQL suites, Parquet replay hashes, the provider binding's exact-file hashes and the
  native Windows proofs. An upgrade invalidates some of that evidence and needs its own
  re-verification, which is a separate, reviewable change.
- The two packages whose upgrades would matter most for financial semantics (polars for
  replay, sqlalchemy/psycopg for the ledger) would each need replay and PostgreSQL evidence
  re-run under the new version.

## Secret-scan allowlist

The single `.gitleaks.toml` allowlist (public Binance dataset identifiers in three evidence
files, `generic-api-key` rule only, path and whole-line regex both required) was re-reviewed
on 2026-11-12 with a clean full-history scan, and its next review is 2026-12-12. No change.

## What this review does not establish

It does not show that these versions are free of undiscovered defects, that they are
suitable for broker or financial-critical use, or that a later advisory will not apply.
An advisory against a locked version triggers an immediate review regardless of the date.
