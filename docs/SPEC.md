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

Repositories are cloned into a `repos/` directory under the current working directory, in a folder named the way `git clone` names it (the last path segment, minus a trailing `.git`; dots in the name are kept), or a numbered variant of it when another repository has that name (REPO-6). On later runs the existing clone is updated with `git pull` instead of being cloned again. `--clobber` removes the clones after the run (REPO-5).

**Status:** Done

#### REPO-4 Branch selection

`-b/--branch <name>` checks out the given branch before statistics are computed. Without `-b`, the repository's default branch is used — including when an earlier run left the cached clone on another branch. With `--github`, it also limits which pull requests are counted to those whose base branch is that branch (CLI-3).

**Status:** Done

#### REPO-5 Remove clones after the run

`--clobber` deletes the clones this run used from the `repos/` directory (REPO-3) once the results have been printed, and then removes `repos/` itself if nothing else is left in it. Clones in `repos/` that this run did not use are kept. It is off by default, so clones are kept and reused by later runs. If the run fails before the results are printed, nothing is deleted, so the clones can be inspected. Only directories inside `repos/` are deleted; a symbolic link in place of a clone is removed without following it. If `repos/` is itself a symbolic link to another directory, the clones are deleted from that directory and the link is kept. A clone that cannot be fully deleted (e.g. it contains a folder the user cannot open) is reported on standard error and the remaining clones are still deleted; the exit status stays 0, since the results were printed. Read-only files that git writes inside a clone (as on Windows) are deleted too. With `-v`, each deleted path is printed to standard error. The name follows build tools such as Rake, where `clean` removes intermediate files and `clobber` also removes caches; it is unrelated to `-c/--clean` (FILT-4).

**Status:** Done

#### REPO-6 Repositories with the same name

Repositories whose names are the same (e.g. two forks, `alice/project` and `bob/project`, or two local paths ending in `project`) are each cloned and analyzed separately, never one in place of the other, in one run or across runs. A clone in `repos/` is reused only for the repository it was cloned from (its `origin` URL equals the URL given, or, for a local path, leads to the same folder); a folder in `repos/` that is not a clone, or has no `origin`, is left untouched. The first repository with a name uses `repos/<name>` (REPO-3), so existing clones are still reused; a different repository with the same name uses the first free folder among `repos/<name>-2`, `repos/<name>-3`, and so on, checked the same way. The `repository` column tells them apart by owner (OUT-8).

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

#### STAT-12 Self-merged pull requests

With `--github`, for each contributor, the number of pull requests they authored and also merged themselves (the GitHub user who merged the pull request is its author, ignoring case), with a merge time (`merged_at`) in the date range. Reported in a `prs_self_merged` column, appended after `prs_closed_unmerged`. Every self-merged pull request is also counted in `prs_merged` (STAT-9), so `prs_self_merged` is never larger than `prs_merged`. A merged pull request whose merger GitHub does not report (e.g. a deleted account) is not counted as self-merged. `-b` and `-s/-e` apply as for `prs_merged`.

**Status:** Done

#### STAT-13 Contributor email addresses

With `--github`, every row also reports the contributor's email addresses in two columns appended after `prs_self_merged`: `git_email` lists every distinct author email of the git identities combined into the row (STAT-11), sorted alphabetically (ignoring case) and separated by `; `, and is empty for a GitHub-only row; `github_email` is the public email on the matched GitHub user's profile, and is empty when the profile has none (GitHub does not reveal private emails) or the row has no GitHub user. Emails come from the whole history of the analyzed branch, like the contributor list, not only from commits in the date range. When GitHub statistics are unavailable for a repository (CLI-3), `git_email` is still filled in and `github_email` is empty (`null` in JSON). Without `--github`, neither column appears.

**Status:** Done

#### STAT-14 Pushes to the analyzed branch

With `--github`, for each contributor, the number of times they pushed directly to the analyzed branch (the default branch, or the `-b` branch) in the date range, reported in a `pushes_to_default` column appended after `github_email`. Pushes come from GitHub's repository activity record (`repos/{owner}/{repo}/activity`), which names the GitHub user who pushed: activity types `push` and `force_push` count; pull-request merges, merge-queue merges and branch creation or deletion do not. One push counts once however many commits it carries. Each push is filtered by its own timestamp, using the same inclusive local-time range as FILT-1, and credited to the row of the GitHub user who pushed (STAT-11); a GitHub user with pushes but no other row gets a GitHub-only row. GitHub's activity record does not go back before September 2023, so older pushes are not counted. Without `-b`, the branch is the default branch; if the clone is on no branch (a tag or commit was checked out), no pushes are counted. GitHub lets anyone who can see a public repository read its activity record; a private repository needs access to it.

**Status:** Done

#### STAT-15 Commits made on the GitHub website

With `--github`, for each contributor, how many of their commits counted in `commits` (STAT-1: same date range, exclusions and branch, merges excluded) were made on GitHub's website rather than in a local clone, reported in a `web_commits` column appended after `pushes_to_default`, so `web_commits` is never larger than `commits`. A commit counts when GitHub created it — its committer is `GitHub <noreply@github.com>` — and it is not the result of merging a pull request: a commit GitHub created when squash- or rebase-merging a pull request is not a website commit. Such a commit is the merge commit GitHub names for a merged pull request, or was committed within 2 seconds of one (the other commits of a rebase merge); GitHub commits the result a few seconds before it marks the pull request merged, so the pull request's merge time is used only when GitHub names no merge commit. A named merge commit committed more than a minute before or after the merge time is the pull request's own head commit, which reached the branch another way, so that pull request excludes nothing. A commit GitHub created when a repository was created on the website (a root commit) counts like any other. Such commits are typically file edits, creations, deletions and uploads made in the browser; commits made through GitHub's API (e.g. `github.dev`) look the same and are counted too. Website commits are credited to the commit's author, like `commits`, and summed when identities are combined (STAT-11). When GitHub statistics are unavailable for a repository (CLI-3), `pushes_to_default` and `web_commits` are empty (`null` in JSON).

**Status:** Done

### 3. Filtering

#### FILT-1 Date range

`-s/--start` and `-e/--end` (format `mm/dd/yyyy`) limit the analysis to commits whose commit date falls between the start of the start date and the end of the end date, inclusive, in local time. Defaults: one year ago until today. The output records the requested start and end dates on every row. With `--github`, each pull request and push count is filtered by its own timestamp in the same range (CLI-3).

**Status:** Done

#### FILT-2 Single contributor

`-u/--user <name>` reports only the contributor whose author name or email address matches exactly. Without `-u`, every contributor in the repository's history is reported. With `--github`, it selects the combined row, and a value may also be the GitHub username (ignoring case); see CLI-3.

**Status:** Done

#### FILT-3 File exclusions

`-x/--exclusions` takes a comma-separated list of file names, glob patterns or directories to leave out of the analysis, matched in any directory. A directory name (`vendor` or `vendor/`) excludes everything inside it, and a path pattern (`docs/*.md`) matches inside directories of that name. Surrounding spaces and empty items are ignored. The list replaces the defaults, and `-x ""` excludes nothing. Exclusions apply to commits, lines and files, but not to merges (STAT-7). By default common generated and binary files are excluded: `package.json`, `package-lock.json`, `Pipfile`, `Pipfile.lock`, `requirements.txt`, `*.jpg`, `*.png`, `*.gif`, `*.svg`, `*.pdf`, `*.zip`, `*.gz`, `*.tar`, `*.csv`, `*.json`.

**Status:** Done

#### FILT-4 Remove inactive contributors

By default, contributors with no activity in the date range are listed with zeros. `-c/--clean` removes them. With `--github`, only rows with neither git, pull-request nor push activity are removed (CLI-3).

**Status:** Done

### 4. Output

#### OUT-1 CSV output

`-f csv` (the default) prints a header row followed by one row per contributor per repository, with fields `username, repository, start_date, end_date, commits, insertions, deletions, files, merges`. New fields are added at the end so existing column positions do not change. Values containing commas, quotes or line breaks are quoted. The header is printed even when there are no rows, and the output ends with a single newline. With `--github`, the columns `github_username, prs_opened, prs_merged, prs_closed_unmerged, prs_self_merged, git_email, github_email, pushes_to_default, web_commits` are appended, and are in the header even when there are no rows (CLI-3).

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

#### OUT-6 Aggregated results

`-a/--aggregate developer` prints one row per developer, summed over every repository analyzed, instead of one row per contributor per repository. Its columns are `username, start_date, end_date, commits, insertions, deletions, files, merges, repositories`, where `repositories` is the number of repositories in which the developer has any activity in the date range (a non-zero count, git or GitHub, as for `-c`); there is no `repository` column. With `--github`, the columns `github_username, prs_opened, prs_merged, prs_closed_unmerged, prs_self_merged, git_email, github_email, pushes_to_default, web_commits` follow. Rows are combined when they share a GitHub username (ignoring case), or, for rows without one, the same git `username` exactly; a developer matched to a GitHub user in one repository but not in another is reported as two rows. `username` is the git username of the developer's row with the most commits (ties alphabetical, as in STAT-11), `github_username` the first non-empty one among the developer's rows, and `git_email` and `github_email` list every distinct email of the combined rows, sorted alphabetically (ignoring case) and separated by `; `.

`-a/--aggregate repository` prints one row per repository, summed over its contributors. Its columns are `repository, start_date, end_date, commits, insertions, deletions, files, merges, contributors`, where `contributors` is the number of its contributors with any activity in the date range; with `--github`, `prs_opened, prs_merged, prs_closed_unmerged, prs_self_merged, pushes_to_default, web_commits` follow. There are no `username`, `github_username`, `git_email` or `github_email` columns.

In both modes every count is the sum of the combined rows, so each total equals the sum of the rows printed without `--aggregate`. A GitHub count is empty (`null` in JSON) only when it is empty in every combined row (CLI-3). Aggregation is applied after `-u` and `-c`, so it combines only the rows those options keep. Rows are sorted by `username` (or `github_username`, for a developer with no git username) or by `repository`, ignoring case. The aggregated columns are printed in every output format, and in the CSV header even when there are no rows. Without `-a`, the output is unchanged.

**Status:** Done

#### OUT-7 Results by day

`-a/--aggregate day` prints one row per day on which anything was counted, summed over every contributor and repository analyzed, in date order. Its columns are `date, commits, insertions, deletions, files, merges, repositories, contributors`, where `date` is the day in `mm/dd/yyyy` format, `repositories` is the number of repositories with any activity that day and `contributors` the number of developers with any activity that day (a developer is identified as in OUT-6, so one person active in several repositories counts once, while one matched to a GitHub user in one repository but not in another counts twice). With `--github`, the columns `prs_opened, prs_merged, prs_closed_unmerged, prs_self_merged, pushes_to_default, web_commits` follow. There are no `username`, `repository`, `start_date`, `end_date`, `github_username`, `git_email` or `github_email` columns.

Each event is counted on the day it happened, in local time, the same way FILT-1 limits the date range: a commit, merge or website commit on its commit date; a pull request as opened on the day it was created, as merged (and self-merged) on the day it was merged, and as closed without merging on the day it was closed; a push on the day it was pushed. So the day totals add up to the totals printed without `-a`. Days without any activity are left out. `-u` limits the counts to that contributor (as in CLI-3 with `--github`); `-c` changes nothing, since inactive contributors add nothing to a day. A GitHub count is empty (`null` in JSON) only when no repository with activity that day could be asked about (CLI-3). The columns are printed in the CSV header even when there are no rows.

**Status:** Done

#### OUT-8 Repository owner in the repository column

The `repository` column names each repository as `<owner>/<name>`: `<name>` as `git clone` names its folder (REPO-3), and `<owner>` the path segment before it in the URL, never its host or user name (`bloombar/gitlogstats` for `https://github.com/bloombar/gitlogstats.git` or `git@github.com:bloombar/gitlogstats.git`; `projects/myrepo` for the local path `/home/user/projects/myrepo`). A URL or path with no segment before the name (other than `.` or `..`) is labelled `<name>` alone. Two different repositories analyzed in one run never share a label: if they would (e.g. `https://github.com/alice/proj` and `https://gitlab.com/alice/proj`, or the same repository given as two different URLs), each of them is labelled with its URL as given instead, leaving out any user name and password (`https://user:token@host/...` is shown as `https://host/...`). Clashes are found among all the repositories analyzed, whichever rows `-u` and `-c` keep. Because every repository has its own label, `-a repository` gives each its own row, and the `repositories` counts of `-a developer` and `-a day` count each separately (OUT-6, OUT-7). The label is the same in every output format and with or without `--github`.

**Status:** Done

### 5. Command-Line Interface

#### CLI-1 Help and usage

`gitlogstats --help` lists every option with a short description.

**Status:** Done

#### CLI-2 Input validation

Invalid dates, and a start date after the end date, are rejected with a usage error and exit status 2 instead of a stack trace.

**Status:** Done

#### CLI-3 GitHub pull-request statistics

`--github` adds GitHub pull-request statistics (STAT-8 to STAT-12), contributor emails (STAT-13), pushes to the analyzed branch (STAT-14) and website commits (STAT-15) for repositories hosted on github.com, appending the columns `github_username, prs_opened, prs_merged, prs_closed_unmerged, prs_self_merged, git_email, github_email, pushes_to_default, web_commits` to every output format. Without `--github`, the output and behaviour are unchanged, GitHub is never contacted and the GitHub CLI (`gh`) is not needed. With `--github`, the GitHub API is called through `gh api`, so `gh` must be installed and signed in. This is checked before any repository is cloned; if it fails, nothing is printed to standard output, the tool exits with status 1, and one plain message on standard error says why and what to do — no stack trace:

- `gh` not found: `gitlogstats: --github needs the GitHub CLI (gh), which is not installed. Install it from https://cli.github.com and run 'gh auth login', or run without --github.`
- `gh` not signed in (`gh auth status` fails): `gitlogstats: --github needs the GitHub CLI (gh) to be signed in. Run 'gh auth login', or run without --github.`

The other options apply to pull requests as follows: `-s/-e` filter each count by its own timestamp, using the same inclusive local-time range as FILT-1; `-u` selects the combined row whose author names, emails or GitHub username match exactly (the username ignoring case); `-b` counts only pull requests whose base branch is that branch, and without `-b` every pull request counts; `-c` removes only rows with neither git, pull-request nor push activity; `-x` does not apply to pull requests or pushes (it limits which commits count as website commits, as it does for `commits`); `-b` also selects the branch whose pushes are counted. For a repository not on github.com, or when GitHub cannot be reached for one repository (no network, rate limit, private repository without access), the git statistics are still reported, the GitHub columns (including `github_email`, `pushes_to_default` and `web_commits`) are empty (`null` in JSON) rather than zero while `git_email` is still filled in (STAT-13), and the reason is printed to standard error.

**Status:** Done

### 6. Packaging & Quality

#### PKG-1 Installable package

The tool installs with `pip install gitlogstats`, which provides a `gitlogstats` command. It can also be run as `python -m gitlogstats`.

**Status:** Done

#### PKG-2 Continuous integration and release

GitHub Actions builds the package on Python 3.9 and 3.11 for every pull request into `master` and every push to `master`. It publishes to PyPI only when a pull request is merged into `master` and the build of the merged code passes; pushes to other branches publish nothing. A merge whose version is already on PyPI (no version bump) skips the upload instead of failing.

**Status:** Done

#### PKG-3 Automated tests

Unit tests cover parsing and formatting, and integration tests build real git repositories to check the statistics across commit-message shapes, kinds of change, author names, date boundaries, exclusions and the command-line options. Run with `pytest`.

**Status:** Done

#### PKG-4 Run tests in CI

The CI workflow runs the Python test suite (`pytest`) on every pull request into `master` and every push to `master`, and on the merged code before a release; a failing test stops the release.

**Status:** Done

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
