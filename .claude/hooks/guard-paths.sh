#!/usr/bin/env bash
# Blocks writes to files that must never be modified by an agent:
#
#   .pypirc          the PyPI API token used to publish the package
#   .env, .env.*     any local credentials (e.g. a GitHub token)
#
# `.env.example` files are the tracked templates and carry no secrets, so they
# are explicitly allowed — the rule above would otherwise block editing them.
#
# CLAUDE.md rules are advisory; this is not. Exit code 2 blocks the tool call and
# shows stderr to the model, so a blocked write is a signal to stop, not an
# obstacle to route around.
#
# Reads the PreToolUse hook payload as JSON on stdin.

set -euo pipefail

payload=$(cat)

# Pull the fields we need without assuming jq is present.
extract() {
  printf '%s' "$payload" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
value = data
for key in sys.argv[1].split('.'):
    if not isinstance(value, dict):
        sys.exit(0)
    value = value.get(key)
    if value is None:
        sys.exit(0)
print(value)
" "$1" 2>/dev/null || true
}

tool=$(extract tool_name)
file_path=$(extract tool_input.file_path)
command=$(extract tool_input.command)

# Paths are matched on the tail of the path, so an absolute path, a relative one
# and a path reached via a symlink all trip the same rule.
is_protected() {
  case "$1" in
    # The tracked templates come first: they are the one .env.* that is public.
    */.env.example | .env.example) return 1 ;;
    */.env | .env | */.env.* | .env.*) return 0 ;;
    */.pypirc | .pypirc) return 0 ;;
    *) return 1 ;;
  esac
}

deny() {
  echo "BLOCKED: $1" >&2
  echo "This path is protected because it holds live credentials." >&2
  echo "Do not work around this. Stop and report the block." >&2
  exit 2
}

case "$tool" in
  Write | Edit | MultiEdit | NotebookEdit)
    if [ -n "$file_path" ] && is_protected "$file_path"; then
      deny "write to $file_path"
    fi
    ;;
  Bash)
    # Only guard commands that plainly mutate a protected path. A read (cat,
    # grep, a `grep -E '^KEY=' .env` to list key names) is allowed: the risk
    # here is loss and leakage through modification, not inspection.
    #
    # Matching is restricted to the FIRST LINE of the command. Everything after
    # a newline is a heredoc body, a commit message, or a multi-line script
    # argument — text that merely mentions `.env` rather than acting on it.
    # Without this, writing a commit message about the guard trips the guard,
    # which is how an over-broad rule teaches people to disable it.
    if [ -n "$command" ]; then
      first_line=${command%%$'\n'*}

      # Force-add: the one operation that puts a gitignored secret into history.
      case "$first_line" in
        *"git add "*" -f"* | *"git add "*" --force"* | *"git add -f"* | *"git add --force"*)
          deny "git add --force can commit an ignored secret: $first_line"
          ;;
      esac

      # Destructive operations naming a protected path.
      case "$first_line" in
        rm\ * | *\;\ rm\ * | *"&& rm "* | *"| rm "* | *truncate\ * | *shred\ *)
          case "$first_line" in
            *.env.example*) ;;
            *.env | *.env\ * | *.env.* | *.pypirc*)
              deny "command would delete a protected path: $first_line"
              ;;
          esac
          ;;
      esac

      # Redirection into a protected path (`> .env`, `>> server/.env.production`).
      case "$first_line" in
        *">"*.env.example*) ;;
        *">"*/.env* | *">"\ .env* | *">"*.pypirc*)
          deny "command would overwrite a protected path: $first_line"
          ;;
      esac
    fi
    ;;
esac

exit 0
