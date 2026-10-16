# Examples

## `assignment-stats.sh`: statistics for one assignment

Reports every student's contributions to one assignment: all the repositories in a GitHub organization whose names start with the same prefix (e.g. `web-app-exercise-`), over a date range. It works in bash on macOS, Linux, WSL and Git Bash on Windows.

### Requirements

- Python 3
- git
- The [GitHub CLI](https://cli.github.com) (`gh`), signed in with `gh auth login`

You don't need to install `gitlogstats` yourself: the script installs or upgrades it each time it runs (see [What the script does](#what-the-script-does)).

### Usage

```bash
./assignment-stats.sh ORGANIZATION_NAME REPO_PREFIX START_DATE END_DATE [gitlogstats options...]
```

| Argument            | Meaning                                                                | Example                      |
| ------------------- | ---------------------------------------------------------------------- | ---------------------------- |
| `ORGANIZATION_NAME` | The GitHub organization that holds the students' repositories          | `software-students-fall2029` |
| `REPO_PREFIX`       | The start of the repository names for this assignment                  | `web-app-exercise-`          |
| `START_DATE`        | First day of the period, `mm/dd/yyyy`                                  | `09/01/2029`                 |
| `END_DATE`          | Last day of the period, `mm/dd/yyyy` (included)                        | `10/16/2029`                 |
| options             | Anything after the four arguments is passed to `gitlogstats` unchanged | `-f markdown`                |

Run it from any directory. The results are printed to standard output, so redirect them to save them; progress messages go to standard error and stay on screen.

### Examples

Save a CSV of one assignment's statistics:

```bash
./assignment-stats.sh software-students-fall2029 web-app-exercise- 09/01/2029 10/16/2029 > web-app-exercise.csv
```

Print a Markdown table instead:

```bash
./assignment-stats.sh software-students-fall2029 web-app-exercise- 09/01/2029 10/16/2029 -f markdown
```

Leave out students with no activity in the period, as JSON:

```bash
./assignment-stats.sh software-students-fall2029 web-app-exercise- 09/01/2029 10/16/2029 -c -f json > web-app-exercise.json
```

To run it from elsewhere, give its path, e.g. `bash docs/examples/assignment-stats.sh ...`. On Windows, run it from Git Bash or WSL, not from Command Prompt or PowerShell.

See the main [README](../../README.md) for every `gitlogstats` option and what each column means.

### What the script does

1. Checks the arguments and that Python, git and `gh` are installed and `gh` is signed in. If anything is missing it stops with a message saying what.
2. Installs or upgrades `gitlogstats` in a Python environment of its own, `~/.gitlogstats-venv`, reused by later runs. Set `GITLOGSTATS_VENV` to keep it elsewhere. A separate environment is needed because Homebrew Python and recent Debian and Ubuntu releases refuse a system-wide `pip install`.
3. Lists the organization's repositories whose names start with `REPO_PREFIX`, into a temporary file that is deleted when the script ends, even after an error. An existing `repos.txt` in your directory is never touched. If no repository matches, it stops with an error.
4. Runs `gitlogstats` on those repositories with `--github` and `--clobber`. `--github` adds the GitHub columns (pull requests, pushes, website commits and emails) and combines each student's git names into one row; `--clobber` deletes the clones it makes in `./repos/` once the results are printed.

### Troubleshooting

| Message                                                  | What to do                                                                                            |
| -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `'...' is not a date in mm/dd/yyyy format`               | Write dates with two-digit month and day and a four-digit year, e.g. `09/01/2029`                     |
| `the GitHub CLI is not signed in`                        | Run `gh auth login`                                                                                   |
| `no repositories in '...' start with '...'`              | Check the organization name and prefix; the prefix is case-sensitive                                  |
| `could not create a virtual environment`                 | On Debian or Ubuntu, install the venv module: `sudo apt install python3-venv`                         |
| `Permission denied` when running `./assignment-stats.sh` | Make it executable with `chmod +x assignment-stats.sh`, or run it with `bash assignment-stats.sh ...` |
