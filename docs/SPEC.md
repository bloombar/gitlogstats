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

`-b/--branch <name>` checks out the given branch before statistics are computed. Without `-b`, the repository's default branch is used — including when an earlier run left the cached clone on another branch.

**Status:** Done

### 2. Contribution Statistics

#### STAT-1 Commit count

For each contributor, the number of commits they authored in the date range. Merge commits count as commits. Commits that change no files (empty commits) and commits that only touch excluded files (FILT-3) are not counted.

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

### 3. Filtering

#### FILT-1 Date range

`-s/--start` and `-e/--end` (format `mm/dd/yyyy`) limit the analysis to commits whose commit date falls between the start of the start date and the end of the end date, inclusive, in local time. Defaults: one year ago until today. The output records the requested start and end dates on every row.

**Status:** Done

#### FILT-2 Single contributor

`-u/--user <name>` reports only the contributor whose author name or email address matches exactly. Without `-u`, every contributor in the repository's history is reported.

**Status:** Done

#### FILT-3 File exclusions

`-x/--exclusions` takes a comma-separated list of file names or glob patterns to leave out of the analysis, matched in any directory. By default common generated and binary files are excluded: `package.json`, `package-lock.json`, `Pipfile`, `Pipfile.lock`, `requirements.txt`, `*.jpg`, `*.png`, `*.gif`, `*.svg`, `*.pdf`, `*.zip`, `*.gz`, `*.tar`, `*.csv`, `*.json`.

**Status:** Done

#### FILT-4 Remove inactive contributors

By default, contributors with no activity in the date range are listed with zeros. `-c/--clean` removes them.

**Status:** Done

### 4. Output

#### OUT-1 CSV output

`-f csv` (the default) prints a header row followed by one row per contributor per repository, with fields `username, repository, start_date, end_date, commits, insertions, deletions, files`. Values containing commas, quotes or line breaks are quoted. The header is printed even when there are no rows, and the output ends with a single newline.

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

`-v/--verbose` prints debugging information (directories, the git commands run, contributors found) to standard error, so standard output stays machine-readable.

**Status:** Done

### 5. Command-Line Interface

#### CLI-1 Help and usage

`gitlogstats --help` lists every option with a short description.

**Status:** Done

#### CLI-2 Input validation

Invalid dates, and a start date after the end date, are rejected with a usage error and exit status 2 instead of a stack trace.

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
