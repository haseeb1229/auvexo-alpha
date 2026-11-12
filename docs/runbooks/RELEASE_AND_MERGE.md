# Release and merge

## Commit rules

- Author and committer are the founder's configured Git identity.
- No AI co-author trailer and no generated-by line.
- No history rewrite and no force push.
- Normal merge commits only. No squash, no rebase merge.

## Before pushing a branch

1. Run [local verification](LOCAL_VERIFICATION.md) on the exact tree being committed.
2. Run the staged and full-history secret scans.
3. Read the diff for machine, user or account identifiers. The repository is public.
4. Commit in reviewable chunks with messages that say why.

## Before merging a pull request

1. The pull request's base is the current `main` and the head is the commit you verified.
2. Hosted CI has passed on that exact head. Open the run and confirm that the job has
   real steps and that the pytest summary shows the expected counts. A run with no
   executed steps is not a pass.
3. The change has been reviewed against the canonical documents by someone other than
   its author, or by an independent audit recorded under [reviews](../reviews/).
4. Frozen files are unchanged unless a new ADR supersedes them. The documentation check
   pins several by hash.

Merge with a normal merge commit, then verify:

```text
git fetch origin
git log -1 --format="%H %P" origin/main
git rev-parse "origin/main^{tree}" "<head>^{tree}"
```

The first parent is the previous `main`, the second parent is the verified head, and the
two trees are equal when `main` had not moved.

## After merging

`main` is tested by CI on push. Update [STATUS](../STATUS.md) in the same pull request
that changes a fact, not afterwards.

## Operational releases

Merging does not change what runs. The Operational and OI Runtime checkouts move only by
an explicit owner-approved re-pin, with a superseding preregistration where a campaign is
affected. See [evidence campaigns](EVIDENCE_CAMPAIGNS.md).

## Before Phase 8

Protected `main` or an equivalent reviewed control, a CI-bound release manifest or tag
with exact approved hashes, and no unreviewed release. None of these exists today.
