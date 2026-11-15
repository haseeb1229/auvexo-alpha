# Future study preregistration template

Every new study fills in every section below and freezes it, by hash, before any trial is
registered. The database gates in [ADR-033](../adr/033-data-and-research-integrity.md)
enforce parts of it; the rest is enforced by review. Leaving a section blank stops the
study. The two Phase 3 holdouts are consumed and may never be named here.

## 1. Identity

- Study name, version, owner, date.
- Code hash and `uv.lock` hash. Both are checked at every read. Any change means a new
  study.

## 2. Inputs

- Input manifests by `dataset_version` and manifest hash.
- The rights snapshot for each source and the data-use classification.
- A statement that no input version has a recorded cross-source conflict, because a
  conflict blocks the read.

## 3. Splits

- Training, validation and holdout as exact half-open UTC instants.
- A statement that the holdout has never been registered, read or consumed by any study.
- Embargo or purge length, at least the longest holding horizon.

## 4. Walk-forward

- Role: either **informational only** (the default in code), or the exact rule by which
  fold results drive selection: the statistic, how folds are aggregated, how ties break,
  and whether folds combine with or replace validation.
- Fold rule by name (`expanding.train-span.365-day-segments.v1`), the fold count and
  every fit and evaluation range. Folds stay inside the training span and never repeat
  validation.
- Whether folds use the embargo.

## 5. Grid and selection

- Every config in grid order with its content hash, its family, and the parameter and
  trial budgets, including walk-forward trials.
- The selection rule (statistic and tie-break). Exactly one config per family is frozen in
  the database before the holdout opens.

## 6. Simulation

- Cost model, stress multipliers starting at 1 and ascending, availability policy and
  lag, seed, bootstrap settings and comparisons.

## 7. Holdout procedure

- Opened only through the database function. An interrupted run resumes only the missing
  trials of the frozen selection, never reopens, and any mismatch stops it.
- Every read, including after completion, is logged.
- [ ] No rights review of any input source falls due before the holdout can complete.
  Check the review dates before opening.
- [ ] While the holdout is OPEN, no change to a research-hashed module is released. This
  includes a rights renewal in `domain/source_reviews.py` and any collector or store
  edit. Such a change alters the code hash, every later read refuses, and the consumed
  holdout is left with no result.

## 8. Decision rule

- Screens and the decision rule. INCONCLUSIVE and NO EDGE are valid outcomes.
- No promotion eligibility follows from a research outcome.
