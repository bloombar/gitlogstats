![build](https://github.com/bloombar/gitlogstats/actions/workflows/build.yaml/badge.svg)

# Git Developer Contributions Analysis

This repository contains a command-line tool, `gitlogstats`, written in `python`, to track developers' contributions to one or more Git repositories within a particular time range. GitHub's Insights tools and charts are not extremely useful, and often omit contributors or give misleading statistics.

This script calculates the following, for each developer in each repository:

- number of **commits**
- number of **lines added**
- number of **lines deleted**
- number of **files changed**
- number of **merges** into the analyzed branch

With `--github`, it also reports each developer's GitHub **pull requests** opened, merged, closed without merging and merged by themselves, their **pushes** to the analyzed branch, their commits made on GitHub's **website**, and their **git and GitHub email addresses**. It matches each GitHub account to the developer's git names and combines a developer who committed under several names into one row (see [GitHub statistics](#github-statistics)).

The results can be formatted as `csv`, `json`, or `markdown`.

## Install

`gitlogstats` can be installed with a package manager such as `pip`

e.g. `pip install gitlogstats`, `pip3 install gitlogstats`, depending on your environment.

## Usage

The command `gitlogstats --help` shows the usage instructions:

```
usage: gitlogstats [-h] (-r REPOSITORY | -rf REPOFILE) [-u USER] [-s START]
                   [-e END] [-x EXCLUSIONS] [-f {csv,json,markdown}]
                   [-b BRANCH] [-v] [-c] [-a {developer,repository}]
                   [--github] [--clobber]

options:
  -h, --help            show this help message and exit
  -r REPOSITORY, --repository REPOSITORY
                        the public URL of the repository whose logs to parse
  -rf REPOFILE, --repofile REPOFILE
                        the path to simple text file with a list of repository
                        URLs to parse
  -u USER, --user USER  The git username (or email address) to report. Default
                        is all contributing users
  -s START, --start START
                        Start date in mm/dd/yyyy format
  -e END, --end END     End date in mm/dd/yyyy format
  -x EXCLUSIONS, --exclusions EXCLUSIONS
                        A comma-separated list of files, patterns or
                        directories to exclude, e.g. --exclusions "foo.zip,
                        *.jpg, vendor". Replaces the default list; use "" to
                        exclude nothing
  -f {csv,json,markdown}, --format {csv,json,markdown}
                        The format in which to output the results
  -b BRANCH, --branch BRANCH
                        The branch to parse, if not the default branch
  -v, --verbose         Whether to output debugging info
  -c, --clean           Remove contributors without any contribuition
  -a {developer,repository}, --aggregate {developer,repository}
                        Combine the results into one row per developer, summed
                        over all repositories, or one row per repository,
                        summed over its contributors
  --github              Also report GitHub pull requests opened, merged,
                        closed and self-merged per contributor, with their git
                        and GitHub emails, their pushes to the analyzed branch
                        and their commits made on the GitHub website, and
                        match GitHub users to git authors. Needs the GitHub
                        CLI (gh), signed in
  --clobber             Delete the repository clones this run used from the
                        repos/ directory after printing the results (default:
                        keep them for faster later runs)
```

In case `gitlogstats` is not found as a command, even after installing, try `python -m gitlogstats` or `python3 -m gitlogstats` instead.

## Example usage

### Single versus multiple repository analytics

The `-r` and `-rf` flags control whether the script looks at a single repository, or a batch of repositories stored in a simple text file.

Output the contributions of all developers to a single repository:

```bash
gitlogstats -r https://github.com/bloombar/gitlogstats.git
```

Output the contributions of all developers to a set of repositories stored in a file named `repos.txt`, one URL per line (see [example file](./repos.txt)). Blank lines and lines starting with `#` are ignored. The results for all repositories are combined into a single table:

```bash
gitlogstats -rf repos.txt
```

### Individual contributor versus all contributors

By default, the statistics of all contributors are calculated. The `-u` flag can be used to limit the analysis to just a single contributor by referencing their git username or email address. The match is exact, so `-u Al` does not include commits by `Alice`.

Output the contributions of only the contributor named `bloombar` to a single repository:

```bash
gitlogstats -u bloombar -r https://github.com/bloombar/gitlogstats.git
```

The same, but to a batch of repositories listed in the `repos.txt` file:

```
gitlogstats -u bloombar -rf repos.txt
```

### Custom date range

By default, contributions from a year ago until today are analyzed. Use the `-s` and `-e` flags to specify a different start and end date, respectively. Both dates are inclusive: all commits made from the start of the start date to the end of the end date (by commit date, in local time) are counted.

Output the contributions to a single repository for a specific date range, inclusive.

```bash
gitlogstats -s 11/15/2021 -e 12/15/2021 -r https://github.com/bloombar/gitlogstats.git
```

The same, but to a batch of repositories listed in the `repos.txt` file:

```
gitlogstats -s 11/15/2021 -e 12/15/2021 -rf repos.txt
```

### Excluding files

By default, common generated and binary files are left out of the analysis: `package.json`, `package-lock.json`, `Pipfile`, `Pipfile.lock`, `requirements.txt`, `*.jpg`, `*.png`, `*.gif`, `*.svg`, `*.pdf`, `*.zip`, `*.gz`, `*.tar`, `*.csv` and `*.json`. Use `-x` to give your own comma-separated list instead. It replaces the default list rather than adding to it.

Each item can be a file name, a glob pattern or a directory, and is matched in any directory of the repository. A directory name, such as `vendor` or `vendor/`, excludes everything inside it. A path such as `docs/*.md` matches only inside directories with that name.

```
gitlogstats -rf repos.txt -x "*.json, *.lock, vendor, docs/*.md"
```

Exclude nothing:

```
gitlogstats -rf repos.txt -x ""
```

Excluded files are left out of the commit, line and file counts. A commit that only touches excluded files is not counted at all. Exclusions do not affect the merge count.

### Filter Contributors

By default, every contributor in a repository's history is listed, with zeros for those who were inactive in the date range. Use `-c` to show only contributors with activity.

```
gitlogstats -rf repos.txt -c
```

### Totals per developer or per repository

By default there is one row per contributor per repository. Add `-a developer` to get one row per developer with their statistics summed over every repository, or `-a repository` to get one row per repository summed over its contributors.

```
gitlogstats -rf repos.txt -a developer
gitlogstats -rf repos.txt -a repository
```

Developer rows have no `repository` column; instead a `repositories` column counts the repositories the developer has a row in. Repository rows have no username or email columns; a `contributors` column counts the contributor rows combined. `-u` and `-c` are applied first, so `-u alice -a repository` shows Alice's share of each repository. With `--github`, a developer's rows are combined by GitHub username, so different git names linked to one GitHub account become one row, and their email addresses are listed together. A developer matched to a GitHub account in one repository but not in another (for example a repository not on GitHub) keeps a separate row for each.

### Cloned repositories

Each repository is cloned into a `repos/` directory under the directory you run the command from, and later runs update (`git pull`) the existing clone instead of cloning again, which makes them much faster. Add `--clobber` to delete the clones the run used, once the results have been printed; `repos/` itself is removed too if nothing else is left in it. Clones from other runs are kept, and nothing is deleted if the run fails before printing, so you can inspect it. With `-v`, each deleted path is listed on standard error.

```
gitlogstats -rf repos.txt --clobber
```

`--clobber` is unrelated to `-c/--clean`, which only hides contributors without activity.

### GitHub statistics

Add `--github` to also report each contributor's pull requests, pushes, website commits and email addresses. Nine columns are appended to every output format:

| Column                | Meaning                                                                                                 |
| --------------------- | ------------------------------------------------------------------------------------------------------- |
| `github_username`     | the GitHub account matched to the contributor (never the display name), so you can check the matching   |
| `prs_opened`          | pull requests they opened in the date range, whatever their state now (drafts included)                 |
| `prs_merged`          | pull requests they authored that were merged in the date range, by anyone and in any way (squash too)   |
| `prs_closed_unmerged` | pull requests they authored that were closed without merging in the date range                          |
| `prs_self_merged`     | pull requests they authored and also merged themselves, merged in the date range (also in `prs_merged`) |
| `git_email`           | every distinct author email of the git names combined into the row, sorted alphabetically (ignoring case) and separated by `; `; empty for a GitHub-only row |
| `github_email`        | the public email on the matched GitHub profile; empty when the profile has none (GitHub does not reveal private emails) or no account matched |
| `pushes_to_default`   | times they pushed directly to the analyzed branch (the default branch, or the `-b` branch) in the date range; each push counts once however many commits it carries. Pull request merges, merge-queue merges and creating or deleting branches are not pushes |
| `web_commits`         | their commits counted in `commits` that were made on GitHub's website (committer `GitHub <noreply@github.com>`), such as editing, creating, deleting or uploading a file in the browser; never more than `commits`. The commit GitHub makes when it squash- or rebase-merges a pull request is not counted |

```
gitlogstats -r https://github.com/bloombar/gitlogstats.git --github
```

**Requirements.** Only `--github` needs the [GitHub CLI](https://cli.github.com) (`gh`); without the flag nothing changes and GitHub is never contacted. Install `gh`, then run `gh auth login`. The tool checks this before cloning anything. If it fails, nothing is printed to standard output, the exit status is 1 and one of these messages is printed to standard error:

```
gitlogstats: --github needs the GitHub CLI (gh), which is not installed. Install it from https://cli.github.com and run 'gh auth login', or run without --github.
gitlogstats: --github needs the GitHub CLI (gh) to be signed in. Run 'gh auth login', or run without --github.
```

**Empty versus zero.** A zero means GitHub was asked and the person has none. An empty value (`null` in JSON) means GitHub could not be asked for that repository: it is not on github.com, or the request failed (no network, rate limit, a private repository you cannot see). The git statistics are still reported, the reason is printed to standard error, and the other repositories carry on. A contributor with no GitHub account matched has an empty `github_username` and zero pull requests. A GitHub user who opened pull requests or pushed but has no commits is listed in a row of their own with an empty `username` and zero git statistics. When GitHub could not be asked, `git_email` is still filled in and `github_email` is empty. The emails come from the whole history of the branch, not only from commits in the date range.

**Limits of pushes and website commits.** Pushes come from GitHub's repository activity record, which starts in September 2023: earlier pushes are not counted, however old the date range. A file edited on the website directly on the analyzed branch is recorded by GitHub as a push too, so it counts in both `pushes_to_default` and `web_commits`. Reading it works for any public repository you can see; for a private one you need access to it, and if GitHub refuses, the repository's GitHub columns are empty with the reason on standard error, as above. A push is credited to the GitHub user who pushed it, so a person who only pushes (and has no commits or pull requests in the range) still gets a row of their own. Pushes made while a tag or commit (not a branch) is checked out with `-b` are not counted. Website commits are recognised by GitHub being the committer, so commits made through GitHub's API, for example in the `github.dev` editor, are counted as website commits too, and so is the first commit GitHub creates when a repository is created on the website. Website commits follow `commits`: the same date range, exclusions (`-x`) and branch, credited to the commit's author and added up when names are combined into one row.

**Matching GitHub users to git authors.** Each git author name is compared with the GitHub users active in the repository, trying these in order and stopping at the first that finds exactly one user:

1. **Email.** The email is a GitHub `noreply` address containing the username, GitHub itself links one of the author's commits to an account, or the email is the public email of a GitHub profile.
2. **Username.** The author name, or the part of the email before the `@`, is the GitHub username (ignoring case, and treating spaces, hyphens, underscores and dots as alike). The part before the `@` is skipped when it names a role rather than a person (such as `noreply`, `admin` or `info`), or when several author names in the repository share it (`alex@gmail…` and `alex@school…`), since it could belong to either.
3. **Display name.** The author name is the GitHub profile name (ignoring case, accents, punctuation and word order, so `Grace Hopper` matches `Hopper, Grace`).

If a step finds several users it is skipped as ambiguous and the next is tried. All git names matched to one GitHub user become one row: the `username` is the name with the most commits and the git statistics are added up. Use `-v` to see which step matched each name, the ambiguous and unmatched names, and how many `gh` calls were made. A wrong match can be fixed with a `.mailmap` file.

**How the other options apply.**

- `-s` / `-e`: each pull request count uses its own timestamp (opened, merged or closed), and each push its push time, against the same inclusive local-time range as commits.
- `-b`: only pull requests whose base branch is that branch are counted (without `-b`, all pull requests count), and pushes and website commits are counted on that branch instead of the default branch.
- `-u`: selects the combined row whose author names or emails equal the value exactly, or whose GitHub username equals it ignoring case. The whole combined row is reported, so `-u` with one email address also includes the person's commits under their other names and emails, and a value that matches nobody prints no row.
- `-c`: removes only rows with no git activity, no pull requests and no pushes. Email addresses do not count as activity.
- `-x`: has no effect on pull requests or pushes; it does apply to `web_commits`, which only counts commits that `commits` counts.

### Formatting the results

The results can be formatted as `csv`, `json`, or a `markdown` table. The default is `csv`. Use the `-f` flag to control the output format.

```
gitlogstats -s 11/15/2021 -e 12/15/2021 -rf repos.txt -f markdown
```

### Combinations

Flags can be combined to provide more targeted analysis, e.g. a specific contributor over a specific date range

```
gitlogstats -u bloombar -s 11/15/2021 -e 12/15/2021 -r https://github.com/bloombar/gitlogstats.git -f json
```

The same, but to a batch of repositories listed in the `repos.txt` file:

```
gitlogstats -u bloombar -s 11/15/2021 -e 12/15/2021 -rf repos.txt -f json
```

### Debugging

Use `-v` to print debugging information. It is written to standard error, so the results on standard output can still be redirected to a file or piped to another program.

## How statistics are counted

- **commits** — non-merge commits authored by the contributor in the date range. Commits that change no files, or only excluded files (`-x`), are not counted. Merge commits are counted under **merges** instead.
- **insertions** / **deletions** — lines added and removed, as reported by `git log --shortstat`. Binary files add no lines, and merges add none either, so merged work is never counted twice.
- **files** — the number of files each commit changed, summed over the contributor's commits.
- **merges** — merge commits the contributor made directly on the analyzed branch in the date range. The author of a merge commit is the person who merged, so this covers merges made locally and pushed, and pull requests merged on GitHub, GitLab or Bitbucket with a merge commit.

Some merges are not counted:

- Merges that leave no merge commit: fast-forward merges, and pull requests merged with "Squash and merge" or "Rebase and merge". A squash commit counts as an ordinary commit by whoever made it.
- Merges made inside another branch, such as merging `main` into a feature branch with `git pull` or GitHub's "Update branch" button. These keep a branch up to date rather than merge work into it.
- Merges on other branches, unless that branch is analyzed with `-b`.
- Local merges that were never pushed.

A merge made on GitHub uses the person's GitHub profile name and email, which may differ from their local git settings. They can then appear under two names; `--github` combines them into one row (see [Redundant usernames](#redundant-usernames)).

Each commit is credited to its author's name, after applying the repository's `.mailmap` if it has one. Merges are credited the same way. Commit messages are never read, so statistics are the same whether messages are one line, many lines, or empty.

## Development

The package source is in `src/gitlogstats/` and the tests are in `tests/`. Install the development dependencies and run the tests:

```bash
pip install -e ".[dev]"
pytest
```

Python code follows PEP 8 and is formatted with [Black](https://black.readthedocs.io/). The specification is in [docs/SPEC.md](./docs/SPEC.md), and the [project board](https://github.com/users/bloombar/projects/4) is generated from it with `npm run board:derive` and `npm run board:sync` (requires Node and the `gh` CLI).

## Words of caution

### Large numbers of additions or deletions

If a particular contricutor shows a very large number of additions or deletions, typically on the order of many hundreds or thousands, this could be a sign of poor usage of version control.

Most likely, the contributor has failed to update their version control settings to ignore platform or 3rd party code to (i.e. has not updated their `.gitignore` file prior to adding such code), and is therefore tracking additions/deletions of code that is not theirs. The entire contribution for that user during this date range should be ignored in this case until the developer fixes this problem.

### Redundant usernames

The output of the script sometimes lists the same individual contributor under more than one git username. This is most likely due to different username settings for various git and GitHub clients: for example, a merge made on GitHub's website uses the person's GitHub display name, while their own commits use their local `user.name`.

With `--github`, names that belong to the same GitHub account are combined into one row automatically, with their statistics added up (see [GitHub statistics](#github-statistics)). Check the `github_username` and `git_email` columns to see which names were combined. A name GitHub cannot link to any account, for example one whose email is a laptop's default address, keeps a row of its own; add the two names to a `.mailmap` file to combine them.

Without `--github`, or for a repository not on GitHub, add up the rows of a developer who appears under several names yourself, or map the names together in a `.mailmap` file.
