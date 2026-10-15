#!/usr/bin/env bash
# Stop hook: the turn does not end until the project's checks pass.
#
# Runs the gate CLAUDE.md defines for a PR:
#   Python      black --check, pytest (unit + integration)
#   JavaScript  prettier --check, the board-script tests and the hook tests
#
# Only runs checks whose tools are installed: a missing tool must read as
# "nothing to check", never as a failure, or the hook blocks every turn for the
# wrong reason.
#
# Exit 2 blocks the turn and shows stderr to the model.

set -uo pipefail

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

failures=""

run_check() {
  local name="$1"
  shift
  local output
  if ! output=$("$@" 2>&1); then
    failures="${failures}
--- ${name} ---
${output}
"
  fi
}

# Python: the tool itself.
if command -v black >/dev/null 2>&1; then
  run_check "black --check" black --check --quiet src tests
fi
if python -c "import pytest" >/dev/null 2>&1; then
  run_check "pytest" python -m pytest -q
fi

# JavaScript: project tooling (scripts/, .claude/hooks/).
if [ -f package.json ] && [ -d node_modules ]; then
  run_check "prettier --check" npx --no-install prettier --check "scripts/**/*.mjs" ".claude/**/*.mjs"
  run_check "npm run test:scripts" npm run --silent test:scripts
  run_check "npm run test:hooks" npm run --silent test:hooks
fi

if [ -n "$failures" ]; then
  {
    echo "Checks failed. Fix these before ending the turn:"
    echo "$failures"
  } >&2
  exit 2
fi

exit 0
