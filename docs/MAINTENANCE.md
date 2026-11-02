# Maintaining this profile

The public README at the root of `kuxiaowo/kuxiaowo` is displayed on the
[GitHub profile](https://github.com/kuxiaowo). The default branch is `main`.

## Editing

Develop and commit on `developing`, push that branch, then open and merge a
pull request into `main`. Do not commit directly to `main`. Keep both branches.
No branch uses a `codex/` prefix.

For local Python work, use Conda:

```sh
conda env create -f environment.yml
conda activate github-profile
python scripts/update_stats.py
python scripts/validate_stats.py
```

The refresh script needs the GitHub CLI authenticated for reading public data.
It does not push or create pull requests when run locally.

## Automatic refresh

`Refresh profile statistics` runs daily at **09:17 Asia/Shanghai (01:17 UTC)**,
can be started manually from Actions, and runs when its code changes on `main`.
GitHub can delay scheduled runs; public-repository schedules can also be disabled
after extended repository inactivity. The date printed in the card is the last
successful snapshot, not a promise of live data.

The workflow uses a Conda environment and GitHub's short-lived `GITHUB_TOKEN`;
no personal access token or extra secret is required. Repository settings permit
Actions to create pull requests; the job requests `contents: write` and
`pull-requests: write` for its publication step.

Each run fetches `main` and `developing`, refuses to publish if `developing` has
unmerged commits, fast-forwards `developing`, refreshes and validates the four
generated files, then commits to `developing`, opens a PR, and merges it into
`main` with an expected-head check. Normal pushes are used throughout. A conflict,
concurrent branch change, unexpected file, or failed validation stops publication.

If publication stops after opening a PR, review that PR rather than bypassing
the branch check. No unrelated developing changes are automatically merged.

## Statistical scope

- Stars and language shares cover owned **public non-fork** repositories.
  Each selected project's Star count refers to its main repository link.
- Language percentages use GitHub's code-byte classification, including
  documentation and generated code; they are not proficiency or time estimates.
- The contribution calendar comes from the anonymous public profile page,
  including anonymized contributions already visible there. Private repository
  names and contents are not queried or published.
- Contributions include commits, issues, PRs, and reviews. Streaks cover only
  the displayed date range; the current streak ends on its final date.
- The full public snapshot is recorded in `stats-data.json`.

All SVGs are generated locally without a third-party statistics image service.
The portrait-free header and badge assets are original to this profile draft.
