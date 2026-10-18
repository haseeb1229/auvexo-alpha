# Phase 3 verification and evidence locations

Independent exact-head review remains required. Public source contains the generic
framework, frozen protocol and sanitized provider diagnosis. Actual source archives,
experiment manifests/results, database dumps and verification logs remain under ignored
owner-local storage. Fixtures and the scale benchmark never qualify a real source.

## Verification commands

Use the locked environment and real isolated PostgreSQL TEST setup, then run:

```text
python tools/local_db.py migrate
python -m ruff format --check src tests tools migrations
python -m ruff check src tests tools migrations
python -m mypy
python -m pytest -q
node tools/check-docs.mjs
python tools/secret_scan.py
python tools/verify_recovery.py
python tools/verify_data_recovery.py
python tools/benchmark_research.py
python tools/verify_clean_clone.py
git diff --check
```

Do not run migrations or empirical jobs against an unidentified database. The existing
local helpers inject protected DEV/TEST credentials without printing them. Optional
`python tools/research_local.py provision` creates only a dedicated local research
identity, with no ingestion or foundation-policy write grants. No broker identity exists.

The owner-local receipts record actual command exit codes, counts, source hashes and
limitations. Required checks also include full-history and full-source redacted Gitleaks,
the unchanged lock exported with hashes and audited against current advisories, exact
source-to-Parquet replay of every retained research-used version, restored research
artifact hashes/triggers, a fresh Windows clone/venv at the final committed source SHA,
and hosted CI matching the unmerged PR head. No failure may be suppressed or inferred away.

## Evidence contract

- `.local/phase3-resume-snapshot.json` identifies the verified pre-edit recovery snapshot.
- `.local/phase3-outage-evidence/` retains original source diagnosis, narrow REST response,
  source-bound outage certificates and the pre-freeze gate receipt.
- `.local/phase3-resumed/` retains both acquisition checkpoints and exact final inventory,
  quality dispositions, transport counters and all dataset/manifest identities.
- `.local/phase3-study/` contains preregistration, immutable development selection receipts
  and final empirical reports. The canonical trial artifacts live in `.local/research/`
  with append-only PostgreSQL metadata, and are never committed.
- `.local/research-scale-evidence.json`, `.local/data-recovery-evidence.json`,
  `.local/clean-clone-evidence.json` and final CI receipts report measured verification.
- `.local/PHASE_3_FINAL_HANDOFF.md` is the owner-local final review package with exact
  commits, actual checks, private empirical disposition and remaining acceptance gates.

These are evidence locations, not claims that an unfinished command passed. The final
handoff must identify any unavailable result explicitly. Historical blocked handoffs and
the original V1 plan remain unchanged.

Correctness coverage includes independent Decimal round-trip references/hand fixtures,
adverse intrabar and gap-through stops, positive-lag chronology, truncation, financial
conservation properties, no fills during outages, stale final valuation, 24/72/168-hour
rewarming, parser-version replay, unknown-gap refusal, sealed holdout before development,
validation-grid completeness, duplicate/trial races and globally overlapping holdout races.
All inherited all-mode execution denials and dependency/import boundaries remain required.

Calendar observation and Exness qualification are separate: only genuine scheduled dates
may count, Phase 2 full operational acceptance remains OPEN, and no fixture/retrospective
receipt or Phase 3 result closes those gates. The public exception review is due 2026-10-24.

## Measured synthetic scale check

The corrected Windows run on 2026-10-18 passed with 1,052,640 synthetic 1m rows spanning
2020-01-01 through 2022-01-01, in 43 Parquet files totaling 23,738,590 bytes. Measured
generation/write: 105.80s; pruned row-count scan: 0.29s; one-week filter/canonical load:
1.50s; full batched canonical validation: 130.41s (8,072 rows/s). A separate 10,080-row
event replay took 0.234s (43,130 rows/s). Peak RSS was 437,788,672 bytes, two Polars threads,
217.5 CPU seconds and 238.24 wall seconds. These are local measurements, not capacity guarantees.

The retained exact-string/canonical audit schema meets this bounded study's load/replay
needs with lazy column pruning and batched canonical validation. No second numeric
representation, fixed-point parity risk or dependency was introduced. The first benchmark
attempt failed only at the final Windows disk-space reporting call; its result was not
reported PASS. The corrected complete rerun supplies the measurements above.

## Legacy identity compatibility correction

Independent review of `1f3f9c5ab40b667fd79573d5a99c81580964adb3` found that
legacy `spot.v1` publication omitted the parser suffix from the dataset identity.
Every supported parser now uses SHA-256 of ASCII `key + ":" + source_hash + ":" + parser_version`,
restoring the historical Phase 2 formula while leaving `spot.v2` identities unchanged.
No migration, historical manifest, source archive or Parquet artifact changes.

Independent expected-hash tests cover both parser versions. Storage tests also verify
legacy repeat-publication idempotence, immutable supersession, exact legacy replay and
0004's source/parser uniqueness, including legacy payloads without a parser field.
The expected `spot.v1` identity assertion failed on the reviewed source before correction.
The corrected focused storage/outage suite passed 25 tests. A read-only retained audit
verified all 70 legacy identities and all 78 `spot.v2` identities and artifact hashes.

Final correction evidence belongs in the owner-local handoff and
`.local/phase3-correction/`: full retained replay/isolated restore, all 30 previously
consumed OOS trajectories compared byte-for-byte under corrected clean-clone source,
unchanged trial/holdout metadata, final Windows clone and exact-new-head hosted CI.
This verification must not append empirical trials, reopen a holdout, retune selection
or overwrite prior artifacts. Any trajectory mismatch stops acceptance for reviewer disposition.
