/**
 * Tests for the PreToolUse path guard.
 *
 * This hook is the only mechanism standing between an agent and the files
 * holding this project's live credentials — `.pypirc` (the PyPI publishing
 * token) and any `.env` files. A regression here is silent — the hook simply
 * stops blocking — so it is tested like production code.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const HOOK = join(dirname(fileURLToPath(import.meta.url)), 'guard-paths.sh')

/** Runs the hook with a payload; returns its exit code. */
const runHook = payload => {
  try {
    execFileSync(HOOK, {
      input: JSON.stringify(payload),
      stdio: ['pipe', 'pipe', 'pipe'],
    })
    return 0
  } catch (error) {
    return error.status
  }
}

const BLOCKED = 2
const ALLOWED = 0

const write = file_path => ({ tool_name: 'Write', tool_input: { file_path } })
const bash = command => ({ tool_name: 'Bash', tool_input: { command } })

test('blocks writes to files holding live credentials', () => {
  for (const path of [
    '.pypirc',
    '/abs/path/gitlogstats/.pypirc',
    '.env',
    '.env.local',
    'scripts/.env',
    '/abs/path/gitlogstats/.env.production',
  ])
    assert.equal(runHook(write(path)), BLOCKED, path)
})

test('blocks a force-add, which is how a gitignored secret reaches the repo', () => {
  assert.equal(runHook(bash('git add -f .pypirc')), BLOCKED)
  assert.equal(runHook(bash('git add --force .env')), BLOCKED)
})

test('blocks commands that delete or overwrite a protected path', () => {
  assert.equal(runHook(bash('rm -f .pypirc')), BLOCKED)
  assert.equal(runHook(bash('rm .env')), BLOCKED)
  assert.equal(runHook(bash('echo token > .pypirc')), BLOCKED)
  assert.equal(runHook(bash('echo X=1 > scripts/.env')), BLOCKED)
})

test('allows the tracked env templates', () => {
  // `.env.example` is committed and carries no secrets; the `.env.*` rule
  // would block it without an explicit exception.
  for (const path of ['.env.example', 'scripts/.env.example'])
    assert.equal(runHook(write(path)), ALLOWED, path)
  assert.equal(runHook(bash('rm -f .env.example')), ALLOWED)
})

test('allows ordinary source files', () => {
  assert.equal(runHook(write('src/gitlogstats/git_logs_parser.py')), ALLOWED)
  assert.equal(runHook(write('scripts/board/sync.mjs')), ALLOWED)
  assert.equal(runHook(write('docs/SPEC.md')), ALLOWED)
  assert.equal(runHook(bash('python -m pytest -q')), ALLOWED)
})

test('allows reads of protected paths — the risk is modification, not inspection', () => {
  assert.equal(runHook(bash('grep -c password .pypirc')), ALLOWED)
})

test('only the first line is inspected, so prose about a protected path is not a command', () => {
  // Regression: the guard originally matched the whole command string, so a
  // commit message describing the guard tripped the guard. An over-broad rule
  // that blocks honest work is how people learn to disable the rule.
  const message = [
    "git commit -F - <<'EOF'",
    'Add guardrails',
    '',
    'Blocks writes to .pypirc and .env files, and refuses git add -f.',
    'EOF',
  ].join('\n')
  assert.equal(runHook(bash(message)), ALLOWED)
  assert.equal(runHook(bash('git add -A')), ALLOWED)
  assert.equal(runHook(bash('grep -r "pypirc" .gitignore')), ALLOWED)
  assert.equal(runHook(bash('echo "never commit .pypirc"')), ALLOWED)
})

test('a malformed payload does not block work', () => {
  // A hook that fails open on garbage is right: it runs before every tool call,
  // and an unparseable payload is a bug in the harness, not an attack.
  assert.equal(runHook({}), ALLOWED)
})
