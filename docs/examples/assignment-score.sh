#!/usr/bin/env bash
#
# Score every student on one assignment: collect the assignment's statistics
# with assignment-stats.sh into a temporary CSV, then run the
# score-developers.ipynb notebook on it and print the scores as CSV.
#
# Usage:
#   ./assignment-score.sh ORGANIZATION_NAME REPO_PREFIX START_DATE END_DATE [gitlogstats options...]
#
# Example:
#   ./assignment-score.sh software-students-fall2029 web-app-exercise- 09/01/2029 10/16/2029 > scores.csv
#
# The arguments are the same as assignment-stats.sh's and are passed to it
# unchanged, except that -f/--format and -a/--aggregate are not allowed: the
# notebook needs the default CSV with one row per developer and repository.
# The scores go to standard output; progress messages go to standard error.
# Scoring settings (caps, penalties, excluded developers) are in the
# notebook's first code cell.
#
# Requires what assignment-stats.sh requires. The notebook runs in the same
# pipenv environment as gitlogstats, defined by the Pipfile next to this
# script, which also lists the notebook's packages.

set -euo pipefail

usage() {
  echo "usage: $(basename "$0") ORGANIZATION_NAME REPO_PREFIX START_DATE END_DATE [gitlogstats options...]" >&2
  echo "example: $(basename "$0") software-students-fall2029 web-app-exercise- 09/01/2029 10/16/2029 > scores.csv" >&2
}

if [ "$#" -lt 4 ]; then
  usage
  exit 2
fi

# the options after the four arguments must leave the CSV in the shape the
# notebook reads, so refuse the ones that change it
for arg in "${@:5}"; do
  case "$arg" in
  -f* | --format* | -a* | --aggregate*)
    echo "error: '$arg' cannot be used here; scoring needs the default CSV output" >&2
    exit 2
    ;;
  esac
done

# the companion files live next to this script, wherever it is run from
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
STATS_SCRIPT="$SCRIPT_DIR/assignment-stats.sh"
NOTEBOOK="$SCRIPT_DIR/score-developers.ipynb"
for file in "$STATS_SCRIPT" "$NOTEBOOK"; do
  if [ ! -f "$file" ]; then
    echo "error: '$file' not found; keep it next to $(basename "$0")" >&2
    exit 1
  fi
done

# everything intermediate goes in a temporary directory, deleted when the
# script ends, even after an error
WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/assignment-score.XXXXXX")
trap 'rm -rf "$WORK_DIR"' EXIT
STATS_CSV="$WORK_DIR/stats.csv"
SCORES_CSV="$WORK_DIR/scores.csv"

# 1. statistics: assignment-stats.sh checks the arguments and tools, installs
# gitlogstats and prints the CSV, which is saved to the temporary file
bash "$STATS_SCRIPT" "$@" >"$STATS_CSV"

# 2. scores: run the notebook on the statistics, in the pipenv environment
# assignment-stats.sh just set up from the Pipfile next to this script. The
# notebook reads its input and output paths from the SCORE_* environment
# variables; the executed copy of the notebook is written to the temporary
# directory, so the original is left unchanged.
export PIPENV_PIPFILE="$SCRIPT_DIR/Pipfile"
export PIPENV_IGNORE_VIRTUALENVS=1
export PIPENV_VERBOSITY=-1
echo "Scoring..." >&2
SCORE_INPUT_CSV="$STATS_CSV" SCORE_OUTPUT_CSV="$SCORES_CSV" \
  pipenv run python -m nbconvert --to notebook --execute "$NOTEBOOK" \
  --output-dir "$WORK_DIR" --output executed.ipynb --log-level WARN >&2

cat "$SCORES_CSV"
