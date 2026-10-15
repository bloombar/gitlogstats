#!/usr/bin/env bash
# Formats a file right after it is edited, so formatting never shows up as
# review noise in the diff: Black for Python, Prettier for JavaScript and the
# other web-tooling formats.
#
# Deliberately best-effort: this runs after every edit, and a formatter that is
# missing or unhappy must never block the work. Always exits 0.

set -uo pipefail

payload=$(cat)

file_path=$(printf '%s' "$payload" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
value = (data.get('tool_input') or {}).get('file_path')
if value:
    print(value)
" 2>/dev/null || true)

[ -n "$file_path" ] || exit 0
[ -f "$file_path" ] || exit 0

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

case "$file_path" in
  *.py)
    # Black is the Python formatter (PEP 8 compliant); use it if installed.
    if command -v black >/dev/null 2>&1; then
      black --quiet "$file_path" >/dev/null 2>&1 || true
    fi
    ;;
  *.js | *.mjs | *.cjs | *.json | *.yml | *.yaml)
    # The generated board manifest is written by derive.mjs, not formatted.
    case "$file_path" in */scripts/board/manifest.yaml | scripts/board/manifest.yaml) exit 0 ;; esac
    [ -d node_modules ] || exit 0
    npx --no-install prettier --write "$file_path" >/dev/null 2>&1 || true
    ;;
esac

exit 0
