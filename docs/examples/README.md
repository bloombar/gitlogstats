# Examples

Tools for scoring students' contributions to a team assignment: every repository in a GitHub organization whose name starts with the same prefix (e.g. `web-app-exercise-`), over a date range.

**Start here.** This is the only tool most people need to run:

| Tool                                         | What it does                                                                                |
| -------------------------------------------- | ------------------------------------------------------------------------------------------- |
| [`assignment-score.sh`](#assignment-scoresh) | One 0–100 score per student for the assignment; runs the two supporting tools below for you |

**Supporting tools.** `assignment-score.sh` runs these in order; you can also run either on its own:

| Tool                                               | What it does                                                                             |
| -------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| [`assignment-stats.sh`](#assignment-statssh)       | Each student's raw statistics (commits, lines, pull requests, …) per repository          |
| [`score-developers.ipynb`](#score-developersipynb) | Jupyter notebook that turns those statistics into scores; holds all the scoring settings |

The scripts run in bash on macOS, Linux, WSL and Git Bash on Windows, from any directory.

## Setup

You need:

- Python 3 and [pipenv](https://pipenv.pypa.io) (`pip install --user pipenv`)
- git
- The [GitHub CLI](https://cli.github.com) (`gh`), signed in with `gh auth login`

The Python packages (`gitlogstats`, pandas, Jupyter, …) are listed in this directory's `Pipfile` and `Pipfile.lock`. The scripts install them into a pipenv environment automatically on their first run. To use the environment yourself:

```bash
cd docs/examples
pipenv sync       # install exactly the locked versions
pipenv shell      # or: pipenv run <command>
```

pipenv uses the nearest `Pipfile` at or above the current directory, so in `docs/examples` it uses this environment, and at the repository root it uses the root environment for developing `gitlogstats`. Leave one `pipenv shell` (`exit`) before starting the other, or set `PIPENV_IGNORE_VIRTUALENVS=1`; otherwise pipenv keeps using the environment that is already active.

To move to a newer `gitlogstats` release, run `pipenv update gitlogstats` here and commit the new `Pipfile.lock`.

## `assignment-score.sh`

Scores every student on one assignment and prints the scores as CSV.

```bash
./assignment-score.sh ORGANIZATION_NAME REPO_PREFIX START_DATE END_DATE [gitlogstats options...] > scores.csv
```

| Argument            | Meaning                                                       | Example                      |
| ------------------- | ------------------------------------------------------------- | ---------------------------- |
| `ORGANIZATION_NAME` | The GitHub organization that holds the students' repositories | `software-students-fall2029` |
| `REPO_PREFIX`       | The start of the repository names for this assignment         | `web-app-exercise-`          |
| `START_DATE`        | First day of the period, `mm/dd/yyyy`                         | `09/01/2029`                 |
| `END_DATE`          | Last day of the period, `mm/dd/yyyy` (included)               | `10/16/2029`                 |
| options             | Passed to `gitlogstats` (see [below](#assignment-statssh))    | `-c`                         |

Example:

```bash
./assignment-score.sh software-students-fall2029 web-app-exercise- 09/01/2029 10/16/2029 > web-app-exercise-scores.csv
```

It runs `assignment-stats.sh` with the same arguments into a temporary CSV, runs `score-developers.ipynb` on that CSV, and prints the scores; the temporary files are deleted afterwards and the notebook is left unchanged. `-f` and `-a` are refused, because the notebook needs the default CSV layout. To change how scores are calculated, edit the settings in the notebook ([below](#settings)).

## `assignment-stats.sh`

Prints each student's statistics for one assignment, one row per student per repository. It takes the same arguments as `assignment-score.sh`.

```bash
./assignment-stats.sh software-students-fall2029 web-app-exercise- 09/01/2029 10/16/2029 > web-app-exercise.csv
./assignment-stats.sh software-students-fall2029 web-app-exercise- 09/01/2029 10/16/2029 -f markdown
```

Options after the four arguments are passed to `gitlogstats` unchanged:

| Option                          | Effect                                                                               |
| ------------------------------- | ------------------------------------------------------------------------------------ |
| `-f csv\|json\|markdown`        | Output format (default `csv`)                                                        |
| `-c`, `--clean`                 | Leave out contributors with no contributions in the period                           |
| `-a developer\|repository\|day` | One row per student over all repositories, per repository, or per day with activity  |
| `-u USER`                       | Report only this git username or email address                                       |
| `-x "PATTERNS"`                 | Comma-separated files, patterns or directories to exclude; replaces the default list |
| `-b BRANCH`                     | Analyze this branch instead of each repository's default branch                      |
| `-v`, `--verbose`               | Print debugging information to standard error                                        |

The script always adds `--github` (pull request, push, website-commit and email columns, with each student's git names combined into one row) and `--clobber` (delete the clones afterwards), and sets the repositories and dates itself, so don't pass `-r`, `-rf`, `-s` or `-e`. It lists the matching repositories with `gh` into a temporary file, so an existing `repos.txt` is never touched. See the main [README](../../README.md) for what each column means.

## `score-developers.ipynb`

Turns a CSV from `assignment-stats.sh` into one score per student. Use it directly to try different settings on statistics you have already collected:

1. Save statistics into this directory, e.g. `./assignment-stats.sh ... > project-2-stats.csv`.
2. Open the notebook in Jupyter (`pipenv run jupyter notebook`) or VS Code (choose the `examples` pipenv environment as the kernel).
3. In the first code cell, set `INPUT_CSV` and `OUTPUT_CSV`, adjust the settings, and run all cells.

To run it without opening it: `pipenv run jupyter nbconvert --to notebook --execute score-developers.ipynb --stdout > /dev/null`. The `SCORE_INPUT_CSV` and `SCORE_OUTPUT_CSV` environment variables override `INPUT_CSV` and `OUTPUT_CSV`; `assignment-score.sh` uses them.

### Settings

| Setting                                            | Meaning                                                                                                                                         | Default                                                                                                  |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `INPUT_CSV`                                        | Statistics CSV to score                                                                                                                         | `project-2-stats.csv`                                                                                    |
| `OUTPUT_CSV`                                       | Where to write the scores; `None` to skip                                                                                                       | `project-2-scores.csv`                                                                                   |
| `EXCLUDE_DEVELOPERS`                               | GitHub usernames (or git names) to leave out, e.g. the instructor whose starter commits are in every repository                                 | `["bloombar"]`                                                                                           |
| `COMBINED_METRICS`                                 | New metrics made by adding CSV columns together                                                                                                 | `prs_closed` = `prs_merged` + `prs_closed_unmerged`                                                      |
| `CAPS`                                             | The scored metrics and their caps                                                                                                               | `commits` 15, `insertions` 1000, `deletions` 300, `files` 30, `merges` 8, `prs_opened` 6, `prs_closed` 6 |
| `MAX_LINES_ADDED`                                  | Most lines a student can add before it looks like copied-in libraries or generated code; lines added beyond it are penalized                    | `2500`                                                                                                   |
| `PENALTIES`                                        | Metrics that take points off: `max_penalty` is the most a metric can cost, reached when the amount over `allowed` (default 0) gets to `full_at` | 10 points at a count of 3; for lines added, 10 points at 2500 lines over `MAX_LINES_ADDED`               |
| `METRIC_LABELS`, `PENALTY_LABELS`, `PENALTY_UNITS` | How metrics and penalties are named in the `comment` column                                                                                     | e.g. `insertions` → "lines added"                                                                        |
| `COMMENT_THRESHOLD`                                | How far from the class average, in standard deviations, a metric must be to be called a strength or weakness in the comment                     | `0.5`                                                                                                    |

### How scores are calculated

1. **Combine rows.** A student's rows are added together, matched by GitHub username (ignoring case), or by git name when there is no GitHub username.
2. **Cap.** A value above its metric's cap counts as the cap: with a `prs_opened` cap of 6, 9 pull requests count as 6.
3. **Z-score.** Each capped metric becomes a z-score (standard deviations above or below the class average), so metrics in different units count equally.
4. **Base score.** Each student's z-scores are averaged and rescaled so the lowest student is 0 and the highest is 100. Scores are relative to the class.
5. **Penalties.** `prs_self_merged`, `pushes_to_default` and `web_commits` are not averaged; each takes off `max_penalty × min(count, full_at) ÷ full_at` points (by default 3.3 per occurrence, at most 10 per metric). Lines added beyond `MAX_LINES_ADDED` are penalized the same way (by default 1 point per 250 lines over 2500, at most 10), as a sign of copied-in libraries or generated code.
6. **Final score.** The base score minus the penalties, never below 0, rounded to the nearest whole number.

The scores CSV keeps each student's uncapped totals, `mean_z`, `base_score` and `total_penalty` next to `score`, so any score can be checked by hand.

Its last column, `comment`, explains the score to the student in plain language, ready to paste into feedback:

> Score 57/100: activity 71.3/100 compared with the rest of the class, minus 14.0 penalty points. Above class average in commits, files changed, lines added. Below class average in pull requests opened (1, typical 5); merges (0, typical 4). Points lost for: merging your own pull request without a review (2 times, -6.7); committing through the GitHub website instead of git (1 time, -3.3); adding an unrealistic number of lines (3,500 lines).

## Student data

Statistics and scores hold students' names and email addresses. `.gitignore` keeps every CSV in this directory out of git; save results here, or anywhere outside the repository. A notebook that has been run shows student data in its outputs, so clear them before committing it (in Jupyter, **Edit → Clear Outputs of All Cells**).

## Troubleshooting

| Message                                     | What to do                                                                                        |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `'...' is not a date in mm/dd/yyyy format`  | Write dates with two-digit month and day and a four-digit year, e.g. `09/01/2029`                 |
| `'pipenv' is not installed`                 | `pip install --user pipenv`                                                                       |
| `the GitHub CLI is not signed in`           | Run `gh auth login`                                                                               |
| `no repositories in '...' start with '...'` | Check the organization name and prefix; the prefix is case-sensitive                              |
| `'-f' cannot be used here`                  | `assignment-score.sh` needs the default CSV; use `assignment-stats.sh` for other formats          |
| `Permission denied` running a script        | `chmod +x assignment-score.sh assignment-stats.sh`, or run it with `bash assignment-score.sh ...` |
