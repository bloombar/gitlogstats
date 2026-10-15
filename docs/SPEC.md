# gitlogstats — Specification

`gitlogstats` is a command-line tool, written in Python, that reports each developer's contributions to one or more Git repositories within a date range. It exists because GitHub's Insights charts often omit contributors or give misleading statistics; `gitlogstats` reads the git history directly instead.

This document describes what the tool does today and what is planned. Each requirement carries a **Status** (`Done`, `In Progress` or `Todo`), and the project board is generated from this file (`npm run board:derive`, then `npm run board:sync`).

## 1. Overview

- **Users:** instructors, team leads and developers who run the tool in a terminal against public (or locally accessible) repositories, typically a batch of student or team repositories.
- **Input:** one repository URL, or a text file listing many.
- **Output:** one row per contributor per repository with commits, lines inserted, lines deleted and files changed — as CSV, JSON or a Markdown table, written to standard output.
- **Platform:** Python 3.7+, with `git` installed and on the `PATH`. Distributed on PyPI as `gitlogstats`.

## 2. Requirements

### 1. Repository Selection

#### REPO-1 Single repository

`-r/--repository <url>` analyzes one repository. Any URL or path that `git clone` accepts works, including HTTPS, SSH (`git@host:user/repo.git`) and local paths. Exactly one of `-r` or `-rf` is required.

**Status:** Done

#### REPO-2 Repository list file

`-rf/--repofile <path>` analyzes every repository listed in a plain text file, one URL per line. Surrounding whitespace is ignored, as are blank lines and lines starting with `#`.

**Status:** Done

#### REPO-3 Local clone cache

Repositories are cloned into a `repos/` directory under the current working directory, in a folder named the way `git clone` names it (the last path segment, minus a trailing `.git`; dots in the name are kept). On later runs the existing clone is updated with `git pull` instead of being cloned again.

**Status:** Done

#### REPO-4 Branch selection

`-b/--branch <name>` checks out the given branch before statistics are computed. Without `-b`, the repository's default branch is used — including when an earlier run left the cached clone on another branch. With `--github`, it also limits which pull requests are counted to those whose base branch is that branch (CLI-3).

**Status:** Done

### 2. Contribution Statistics

#### STAT-1 Commit count

For each contributor, the number of non-merge commits they authored in the date range. Merge commits are counted separately (STAT-7), not as commits. Commits that change no files (empty commits) and commits that only touch excluded files (FILT-3) are not counted. The count does not depend on git's history simplification: commits are never hidden because of how the exclusions interact with merges.

**Status:** Done

#### STAT-2 Lines inserted and deleted

For each contributor, the sum of lines inserted and lines deleted across their commits, as reported by `git log --shortstat`. Binary files add no lines. Merge commits add no lines, so work merged from a branch is never counted twice.

**Status:** Done

#### STAT-3 Files changed

For each contributor, the sum over their commits of the number of files each commit changed, as reported by `git log --shortstat` (binary files and renames included).

**Status:** Done

#### STAT-4 Exact author attribution

Each commit is credited to exactly one contributor: the commit's author name. Names that are prefixes of each other (`Al`, `Alice`), or that contain spaces, quotes, brackets or other symbols, are kept apart and counted correctly. The per-contributor totals for a repository add up to the repository's totals.

**Status:** Done

#### STAT-5 Statistics independent of commit messages

Statistics are correct whatever the commit messages contain: single-line, multi-line (with or without a blank line after the subject), empty, non-English, or text that looks like `git log` output (e.g. `commit abc123` or `3 files changed`). Commit messages are never read; each commit's author and change summary come from a machine-readable `git log` format.

**Status:** Done

#### STAT-6 Mailmap identities

Author names are taken after applying the repository's `.mailmap`, so a developer who committed under several names or email addresses can be reported as one contributor when the repository maps them.

**Status:** Done

#### STAT-7 Merge count

For each contributor, the number of merge commits they authored directly on the analyzed branch (its first-parent line) in the date range, reported in a `merges` column. The author of a merge commit is the person who merged, so this covers merges made locally and pushed, and pull requests merged on GitHub, GitLab or Bitbucket with a merge commit, where the hosting service is only the committer. Octopus merges count once. Not counted: fast-forward, squash and rebase merges (no merge commit exists); merges made inside other branches, such as merging the main branch into a feature branch to update it; merges on branches other than the analyzed one; and local merges that were never pushed. File exclusions (FILT-3) do not affect merges. Merges are not counted as commits and add no lines or files.

**Status:** Done

#### STAT-8 Pull requests opened

With `--github` (CLI-3), for each contributor, the number of pull requests they authored on GitHub whose creation time (`created_at`) falls in the date range, whatever their state now (open, merged or closed; drafts included). Reported in a `prs_opened` column.

**Status:** Done

#### STAT-9 Pull requests merged

With `--github`, for each contributor, the number of pull requests they authored that were merged (`merged_at` set) in the date range, whoever merged them. Reported in a `prs_merged` column. Unlike merges (STAT-7), this counts squash and rebase merges too, since GitHub records them as merged pull requests.

**Status:** Done

#### STAT-10 Pull requests closed without merging

With `--github`, for each contributor, the number of pull requests they authored that were closed without being merged (`state` closed and `merged_at` not set), with a closing time (`closed_at`) in the date range. Reported in a `prs_closed_unmerged` column.

**Status:** Done

#### STAT-11 Matching GitHub users to git authors

With `--github`, each pull-request author (a GitHub username) is matched to the git identities (author name and email) in the repository's history. Each git identity is tried against the GitHub users active in that repository (pull-request authors and the accounts GitHub links to its commits), tier by tier, stopping at the first tier that finds exactly one GitHub user:

1. **Email.** The email is a GitHub `noreply` address (`12345+login@users.noreply.github.com` or `login@users.noreply.github.com`); or GitHub links one of the identity's commits to an account (the commit's `author.login`, which covers private emails GitHub knows but does not publish); or the email equals a candidate's public profile email (case-insensitive).
2. **Username.** The author name, or the email's local part (before `@`), equals a candidate's GitHub username, ignoring case and treating spaces, hyphens, underscores and dots as the same (`Ada Lovelace` matches `Ada-Lovelace`). An email local part is not used when it names a role rather than a person (such as `noreply`, `admin` or `info`), or when it is shared by several author names in the repository (`alex@gmail…` and `alex@school…`), since it could belong to either.
3. **Display name.** The author name equals a candidate's GitHub display name, ignoring case, accents, repeated spaces and punctuation, and word order (`Grace Hopper` matches `Hopper, Grace`).
4. **No match.** A GitHub user matched by no git identity is reported in a row of its own, with an empty `username`, its pull-request statistics and zero git statistics.

If a tier finds several GitHub users for one identity, that tier is skipped as ambiguous and the next is tried; ambiguous and unmatched identities are listed with `-v`. All git identities matched to the same GitHub user are combined into one row: the `username` is the matched author name with the most commits (ties broken alphabetically), and the git statistics are summed. A git identity matched to no GitHub user keeps its own row with an empty `github_username` and zero pull-request statistics. Every row carries the matched GitHub username (never the display name) in a `github_username` column, so matches can be checked and corrected by hand, e.g. with a `.mailmap` (STAT-6).

**Status:** Done

### 3. Filtering

#### FILT-1 Date range

`-s/--start` and `-e/--end` (format `mm/dd/yyyy`) limit the analysis to commits whose commit date falls between the start of the start date and the end of the end date, inclusive, in local time. Defaults: one year ago until today. The output records the requested start and end dates on every row. With `--github`, each pull request count is filtered by its own timestamp in the same range (CLI-3).

**Status:** Done

#### FILT-2 Single contributor

`-u/--user <name>` reports only the contributor whose author name or email address matches exactly. Without `-u`, every contributor in the repository's history is reported. With `--github`, it selects the combined row, and a value may also be the GitHub username (ignoring case); see CLI-3.

**Status:** Done

#### FILT-3 File exclusions

`-x/--exclusions` takes a comma-separated list of file names, glob patterns or directories to leave out of the analysis, matched in any directory. A directory name (`vendor` or `vendor/`) excludes everything inside it, and a path pattern (`docs/*.md`) matches inside directories of that name. Surrounding spaces and empty items are ignored. The list replaces the defaults, and `-x ""` excludes nothing. Exclusions apply to commits, lines and files, but not to merges (STAT-7). By default common generated and binary files are excluded: `package.json`, `package-lock.json`, `Pipfile`, `Pipfile.lock`, `requirements.txt`, `*.jpg`, `*.png`, `*.gif`, `*.svg`, `*.pdf`, `*.zip`, `*.gz`, `*.tar`, `*.csv`, `*.json`.

**Status:** Done

#### FILT-4 Remove inactive contributors

By default, contributors with no activity in the date range are listed with zeros. `-c/--clean` removes them. With `--github`, only rows with neither git nor pull-request activity are removed (CLI-3).

**Status:** Done

### 4. Output

#### OUT-1 CSV output

`-f csv` (the default) prints a header row followed by one row per contributor per repository, with fields `username, repository, start_date, end_date, commits, insertions, deletions, files, merges`. New fields are added at the end so existing column positions do not change. Values containing commas, quotes or line breaks are quoted. The header is printed even when there are no rows, and the output ends with a single newline. With `--github`, the columns `github_username, prs_opened, prs_merged, prs_closed_unmerged` are appended, and are in the header even when there are no rows (CLI-3).

**Status:** Done

#### OUT-2 JSON output

`-f json` prints a single JSON array of objects with the same fields, valid JSON even when several repositories are analyzed.

**Status:** Done

#### OUT-3 Markdown output

`-f markdown` prints a Markdown table with the same columns. Pipe characters in values are escaped so they do not split cells.

**Status:** Done

#### OUT-4 One combined result across repositories

When several repositories are analyzed, the results are printed once, after all repositories are processed, as a single CSV table, JSON array or Markdown table.

**Status:** Done

#### OUT-5 Verbose diagnostics

`-v/--verbose` prints debugging information (directories, the git commands run, contributors found) to standard error, so standard output stays machine-readable. With `--github`, it also prints how each author name was matched to a GitHub user, the ambiguous and unmatched names, and the number of `gh` API calls made for each repository (CLI-3).

**Status:** Done

### 5. Command-Line Interface

#### CLI-1 Help and usage

`gitlogstats --help` lists every option with a short description.

**Status:** Done

#### CLI-2 Input validation

Invalid dates, and a start date after the end date, are rejected with a usage error and exit status 2 instead of a stack trace.

**Status:** Done

#### CLI-3 GitHub pull-request statistics

`--github` adds GitHub pull-request statistics (STAT-8 to STAT-11) for repositories hosted on github.com, appending the columns `github_username, prs_opened, prs_merged, prs_closed_unmerged` to every output format. Without `--github`, the output and behaviour are unchanged, GitHub is never contacted and the GitHub CLI (`gh`) is not needed. With `--github`, the GitHub API is called through `gh api`, so `gh` must be installed and signed in. This is checked before any repository is cloned; if it fails, nothing is printed to standard output, the tool exits with status 1, and one plain message on standard error says why and what to do — no stack trace:

- `gh` not found: `gitlogstats: --github needs the GitHub CLI (gh), which is not installed. Install it from https://cli.github.com and run 'gh auth login', or run without --github.`
- `gh` not signed in (`gh auth status` fails): `gitlogstats: --github needs the GitHub CLI (gh) to be signed in. Run 'gh auth login', or run without --github.`

The other options apply to pull requests as follows: `-s/-e` filter each count by its own timestamp, using the same inclusive local-time range as FILT-1; `-u` selects the combined row whose author names, emails or GitHub username match exactly (the username ignoring case); `-b` counts only pull requests whose base branch is that branch, and without `-b` every pull request counts; `-c` removes only rows with neither git nor pull-request activity; `-x` does not apply. For a repository not on github.com, or when GitHub cannot be reached for one repository (no network, rate limit, private repository without access), the git statistics are still reported, the four GitHub columns are empty (`null` in JSON) rather than zero, and the reason is printed to standard error.

**Status:** Done

### 6. Packaging & Quality

#### PKG-1 Installable package

The tool installs with `pip install gitlogstats`, which provides a `gitlogstats` command. It can also be run as `python -m gitlogstats`.

**Status:** Done

#### PKG-2 Continuous integration and release

GitHub Actions builds the package on every push, on Python 3.9 and 3.11, and publishes it to PyPI.

**Status:** Done

#### PKG-3 Automated tests

Unit tests cover parsing and formatting, and integration tests build real git repositories to check the statistics across commit-message shapes, kinds of change, author names, date boundaries, exclusions and the command-line options. Run with `pytest`.

**Status:** Done

#### PKG-4 Run tests in CI

The CI workflow runs the test suite on every push and stops the release if any test fails. (Today it builds and publishes without running tests.)

**Status:** Todo

### 7. Future Work

- **Author-date filtering** — offer filtering by author date, so rebased or cherry-picked work is credited to when it was written rather than when it was last committed.
- **Contributor aliases** — let users merge several names or emails into one contributor from the command line, for repositories without a `.mailmap`.
- **Private repositories** — document and support authenticated cloning of private repositories (e.g. via a token or SSH agent).
- **Parallel processing** — clone and analyze many repositories concurrently to speed up large batches.
- **Per-file breakdown** — optionally report each contributor's changes per file or directory.
- **Output to file** — write results to a file (e.g. `-o report.csv`) instead of only standard output.
- **GitHub without the gh CLI** — let `--github` call the GitHub API directly with a `GITHUB_TOKEN`, for users who cannot install `gh`.
- **GitHub Enterprise hosts** — extend `--github` to repositories on GitHub Enterprise Server, via `gh api --hostname` or a configurable API URL.
- **Pull-request reviews and mergers** — report who reviewed and who merged each pull request, in addition to who opened it.
- **GitHub-only mode** — report pull-request statistics without computing git statistics, for faster runs over large batches.
