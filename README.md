![build](https://github.com/bloombar/git-developer-contribution-analysis/actions/workflows/build.yaml/badge.svg)

# Git Developer Contributions Analysis

This repository contains a command-line tool, `gitlogstats`, written in `python`, to track developers' contributions to one or more Git repositories within a particular time range. GitHub's Insights tools and charts are not extremely useful, and often omit contributors or give misleading statistics.

This script calculates the following, for each developer in each repository:

- number of **commits**
- number of **lines added**
- number of **lines deleted**
- number of **files changed**

The results can be formatted as `csv`, `json`, or `markdown`.

## Install

`gitlogstats` can be installed with a package manager such as `pip`

e.g. `pip install gitlogstats`, `pip3 install gitlogstats`, depending on your environment.

## Usage

The command `gitlogstats --help` shows the usage instructions:

```
usage: gitlogstats [-h] (-r REPOSITORY | -rf REPOFILE) [-u USER] [-s START] [-e END] [-x EXCLUSIONS] [-f {csv,json,markdown}] [-b BRANCH] [-v] [-c]

optional arguments:
  -h, --help            show this help message and exit
  -r REPOSITORY, --repository REPOSITORY
                        the public URL of the repository whose logs to parse
  -rf REPOFILE, --repofile REPOFILE
                        the path to simple text file with a list of repository URLs to parse
  -u USER, --user USER  The git username (or email address) to report. Default is all contributing users
  -s START, --start START
                        Start date in mm/dd/yyyy format
  -e END, --end END     End date in mm/dd/yyyy format
  -x EXCLUSIONS, --exclusions EXCLUSIONS
                        A comma-separated string of files to exclude, e.g. --excusions "foo.zip, *.jpg, *.json"
  -f {csv,json,markdown}, --format {csv,json,markdown}
                        The format in which to output the results
  -b BRANCH, --branch BRANCH
                        The branch to checkout before compiling statistics. Defaults to the repository's default branch.
  -v, --verbose         Whether to output debugging info
  -c, --clean           Remove contributors without any contribuition
```

In case `gitlogstats` is not found as a command, even after installing, try `python -m gitlogstats` or `python3 -m gitlogstats` instead.

## Example usage

### Single versus multiple repository analytics

The `-r` and `-rf` flags control whether the script looks at a single repository, or a batch of repositories stored in a simple text file.

Output the contributions of all developers to a single repository:

```bash
gitlogstats -r https://github.com/bloombar/git-developer-contribution-analysis.git
```

Output the contributions of all developers to a set of repositories stored in a file named `repos.txt`, one URL per line (see [example file](./repos.txt)). Blank lines and lines starting with `#` are ignored. The results for all repositories are combined into a single table:

```bash
gitlogstats -rf repos.txt
```

### Individual contributor versus all contributors

By default, the statistics of all contributors are calculated. The `-u` flag can be used to limit the analysis to just a single contributor by referencing their git username or email address. The match is exact, so `-u Al` does not include commits by `Alice`.

Output the contributions of only the contributor named `bloombar` to a single repository:

```bash
gitlogstats -u bloombar -r https://github.com/bloombar/git-developer-contribution-analysis.git
```

The same, but to a batch of repositories listed in the `repos.txt` file:

```
gitlogstats -u bloombar -rf repos.txt
```

### Custom date range

By default, contributions from a year ago until today are analyzed. Use the `-s` and `-e` flags to specify a different start and end date, respectively. Both dates are inclusive: all commits made from the start of the start date to the end of the end date (by commit date, in local time) are counted.

Output the contributions to a single repository for a specific date range, inclusive.

```bash
gitlogstats -s 11/15/2021 -e 12/15/2021 -r https://github.com/bloombar/git-developer-contribution-analysis.git
```

The same, but to a batch of repositories listed in the `repos.txt` file:

```
gitlogstats -s 11/15/2021 -e 12/15/2021 -rf repos.txt
```

### Filter Contributors

By default, every contributor in a repository's history is listed, with zeros for those who were inactive in the date range. Use `-c` to show only contributors with activity.

```
gitlogstats -rf repos.txt -c
```

### Formatting the results

The results can be formatted as `csv`, `json`, or a `markdown` table. The default is `csv`. Use the `-f` flag to control the output format.

```
gitlogstats -s 11/15/2021 -e 12/15/2021 -rf repos.txt -f markdown
```

### Combinations

Flags can be combined to provide more targeted analysis, e.g. a specific contributor over a specific date range

```
gitlogstats -u bloombar -s 11/15/2021 -e 12/15/2021 -r https://github.com/bloombar/git-developer-contribution-analysis.git -f json
```

The same, but to a batch of repositories listed in the `repos.txt` file:

```
gitlogstats -u bloombar -s 11/15/2021 -e 12/15/2021 -rf repos.txt -f json
```

### Debugging

Use `-v` to print debugging information. It is written to standard error, so the results on standard output can still be redirected to a file or piped to another program.

## How statistics are counted

- **commits** — commits authored by the contributor in the date range, including merge commits. Commits that change no files, or only excluded files (`-x`), are not counted.
- **insertions** / **deletions** — lines added and removed, as reported by `git log --shortstat`. Binary files and merge commits add no lines, so merged work is never counted twice.
- **files** — the number of files each commit changed, summed over the contributor's commits.

Each commit is credited to its author's name, after applying the repository's `.mailmap` if it has one. Commit messages are never read, so statistics are the same whether messages are one line, many lines, or empty.

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

The output of the script sometimes lists the same individual contributor under more than one git username... This is most likely due to different username settings for various git and GitHub clients.

If a single developer has multiple usernames that all show the same statistics, then only count those stats once. Otherwise, if a single developer has multiple usernames that show different statistics, then add them together to come up with the total for that developer.
