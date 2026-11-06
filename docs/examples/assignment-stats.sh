#!/usr/bin/env bash
#
# Report every student's contributions to one assignment: all repositories in
# a GitHub organization whose names start with a given prefix, over a date
# range. Works in bash on macOS, Linux, other Unix systems, WSL and Git Bash.
#
# Usage:
#   ./assignment-stats.sh ORGANIZATION_NAME REPO_PREFIX START_DATE END_DATE [gitlogstats options...]
#
# Example:
#   ./assignment-stats.sh software-students-fall2029 web-app-exercise- 09/01/2029 10/16/2029 > stats.csv
#   ./assignment-stats.sh software-students-fall2029 web-app-exercise- 09/01/2029 10/16/2029 -f markdown
#
# Dates are mm/dd/yyyy and both days are included. gitlogstats always runs
# with --github, so the GitHub columns are included. Any options after the four
# arguments are passed to gitlogstats unchanged (e.g. -f json, -c).
# The results go to standard output; progress messages go to standard error.
#
# Requires: Python 3, pipenv, git, and the GitHub CLI (gh), signed in with
# `gh auth login` (gh is used to list the organization's repositories).
# gitlogstats is installed automatically in the pipenv environment defined by
# the Pipfile and Pipfile.lock next to this script.

set -euo pipefail

usage() {
  echo "usage: $(basename "$0") ORGANIZATION_NAME REPO_PREFIX START_DATE END_DATE [gitlogstats options...]" >&2
  echo "example: $(basename "$0") software-students-fall2029 web-app-exercise- 09/01/2029 10/16/2029" >&2
}

if [ "$#" -lt 4 ]; then
  usage
  exit 2
fi

# retrieve command-line arguments
ORGANIZATION_NAME=$1
REPO_PREFIX=$2
START_DATE=$3
END_DATE=$4
shift 4 # anything left is passed to gitlogstats

# check the dates before doing any work
for date in "$START_DATE" "$END_DATE"; do
  if ! [[ "$date" =~ ^[0-9]{2}/[0-9]{2}/[0-9]{4}$ ]]; then
    echo "error: '$date' is not a date in mm/dd/yyyy format" >&2
    usage
    exit 2
  fi
done

for tool in git gh pipenv; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "error: '$tool' is not installed" >&2
    exit 1
  fi
done

if ! gh auth status >/dev/null 2>&1; then
  echo "error: the GitHub CLI is not signed in; run 'gh auth login' first" >&2
  exit 1
fi

# gitlogstats runs in the pipenv environment defined by the Pipfile next to
# this script, whatever directory the script is run from. `pipenv sync`
# creates the environment on the first run and installs exactly the versions
# in Pipfile.lock; later runs only check it. Any virtual environment that is
# already active is ignored, so the Pipfile's environment is always used.
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
export PIPENV_PIPFILE="$SCRIPT_DIR/Pipfile"
export PIPENV_IGNORE_VIRTUALENVS=1
export PIPENV_VERBOSITY=-1
echo "Setting up the Python environment from $PIPENV_PIPFILE..." >&2
if ! pipenv sync >&2; then
  echo "error: could not set up the Python environment with pipenv" >&2
  exit 1
fi

# list the assignment's repositories in a temporary file, so an existing
# repos.txt in this directory is never overwritten
REPOS_FILE=$(mktemp "${TMPDIR:-/tmp}/gitlogstats-repos.XXXXXX")
trap 'rm -f "$REPOS_FILE"' EXIT

# the prefix is read by gh's built-in jq from an environment variable, so it
# needs no quoting and jq does not have to be installed
REPO_PREFIX="$REPO_PREFIX" gh repo list "$ORGANIZATION_NAME" --limit 1000 \
  --json name,url \
  --jq '.[] | select(.name | startswith(env.REPO_PREFIX)) | .url' >"$REPOS_FILE"

count=$(grep -c . "$REPOS_FILE" || true)
if [ "$count" -eq 0 ]; then
  echo "error: no repositories in '$ORGANIZATION_NAME' start with '$REPO_PREFIX'" >&2
  exit 1
fi
echo "Analyzing $count repositories from $START_DATE to $END_DATE..." >&2

# --github adds the GitHub columns (pull requests, pushes, website commits,
# emails) and combines each student's git names into one row; --clobber
# deletes the clones once the results are printed
pipenv run python -m gitlogstats -rf "$REPOS_FILE" -s "$START_DATE" -e "$END_DATE" \
  --github --clobber "$@"
