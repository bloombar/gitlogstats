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
# Requires: Python 3, git, and the GitHub CLI (gh), signed in with
# `gh auth login` (gh is used to list the organization's repositories).
# gitlogstats is installed or upgraded automatically in its own Python
# environment (~/.gitlogstats-venv, or $GITLOGSTATS_VENV).

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

# find a Python 3 interpreter: python3 on macOS and Linux, often python on Git Bash
if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  echo "error: Python 3 is not installed" >&2
  exit 1
fi

for tool in git gh; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "error: '$tool' is not installed" >&2
    exit 1
  fi
done

if ! gh auth status >/dev/null 2>&1; then
  echo "error: the GitHub CLI is not signed in; run 'gh auth login' first" >&2
  exit 1
fi

# install or upgrade gitlogstats in a virtual environment of its own: many
# systems (Homebrew Python, recent Debian and Ubuntu) refuse a system-wide
# pip install. The environment is kept and reused by later runs; set
# GITLOGSTATS_VENV to put it somewhere else.
VENV=${GITLOGSTATS_VENV:-"$HOME/.gitlogstats-venv"}
if [ ! -d "$VENV" ]; then
  echo "Creating a Python environment for gitlogstats in $VENV..." >&2
  if ! "$PYTHON" -m venv "$VENV"; then
    echo "error: could not create a virtual environment (on Debian or Ubuntu, install python3-venv)" >&2
    exit 1
  fi
fi
# the environment's Python is in bin/ on macOS, Linux and WSL, Scripts/ on Windows
if [ -x "$VENV/bin/python" ]; then
  VENV_PYTHON="$VENV/bin/python"
else
  VENV_PYTHON="$VENV/Scripts/python.exe"
fi
echo "Installing the latest gitlogstats..." >&2
"$VENV_PYTHON" -m pip install --quiet --disable-pip-version-check --upgrade gitlogstats >&2

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
"$VENV_PYTHON" -m gitlogstats -rf "$REPOS_FILE" -s "$START_DATE" -e "$END_DATE" \
  --github --clobber "$@"
