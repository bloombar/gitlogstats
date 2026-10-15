# Instructions to Claude

`gitlogstats` is a Python command-line tool (`src/gitlogstats/`) that reports developers' contributions to git repositories. The repository also holds JavaScript project tooling: the project-board scripts (`scripts/board/`) and the Claude Code hook tests (`.claude/hooks/`). Each language has its own conventions below.

## Testing

Before finalizing major changes to code, write thorough unit tests and integration tests, aiming for 100% coverage of `src/gitlogstats/`. Statistics must be checked against **real git repositories** built in the tests (see `tests/test_integration.py`), not only against hand-written `git log` text: a mocked log can only confirm the format the test author expected. All passing tests should be reproducible during regression testing as we develop new code.

The checks, all run by the Stop hook (`.claude/hooks/verify.sh`):

| Area                      | Command                                                     |
| ------------------------- | ----------------------------------------------------------- |
| Python tests              | `python -m pytest -q` (or `npm test`)                       |
| Python coverage           | `python -m pytest --cov`                                    |
| Formatting (Python + JS)  | `npm run format:check` (Black and Prettier)                 |
| Board script tests        | `npm run test:scripts`                                      |
| Hook tests                | `npm run test:hooks`                                        |

### Reading a green result

A passing check is not automatically evidence. Before treating one as proof, ask:

- **What would this value look like if the thing that sets it had never happened?** If the answer is "the same", it is not evidence. A count of zero failures, a field read off an object that does not have it, a measurement that never ran, and a package built before the change all report exactly what success reports.
- **Does this pass mean "nothing broke" or "the thing works"?** They are indistinguishable from outside. A green suite proves nothing about a scenario the data under test never exercises — e.g. a parser tested only on single-line commit messages says nothing about multi-line ones.
- **Which tests did this green actually run?** `pytest` covers the Python tool only; the board scripts and hooks have their own `node --test` suites. A green from one says nothing about the others.
- **Would the new test fail without the change?** Where it is cheap, run it against the old code (e.g. `git show HEAD:<file>` into a scratch directory) and confirm it fails.

The first question you can and should ask about your own work: whether an artifact is what you think it is is checkable from the inside. **A prediction is not** — when you expect a particular answer, the expectation is what is doing the asking, so that check has to come from someone with no stake in the outcome. Where work is split across people or sessions, spend one question there rather than on general review.

Fix the defect, not the instrument. If a check reports something correct as a fault, the rule is measuring the wrong thing — loosening its threshold hides the real fault it was built to catch.

## Python conventions

- Follow **PEP 8**, formatted with **Black** (default settings, 88-character lines). Run `black src tests` (or `npm run format`); the PostToolUse hook formats edited `.py` files automatically, and `black --check src tests` must pass.
- Naming per PEP 8: `snake_case` for functions, methods and variables; `PascalCase` for classes; `UPPER_SNAKE_CASE` for module constants.
- Imports at the top of the module: standard library, then third party, then local, one group each.
- Support the Python versions in `pyproject.toml` (`requires-python`) and CI's matrix; avoid syntax newer than they allow.
- Run git through `subprocess` with an **argument list**, never a shell string, so names, paths and patterns containing spaces or quotes are passed intact.
- Never parse human-oriented `git log` output (commit messages, `Author:` lines) with regular expressions. Ask git for a machine-readable `--format` instead.
- Results go to standard output; diagnostics (`--verbose`) go to standard error.
- Runtime code uses the standard library only; test and build tools belong in the `dev` extra / `[dev-packages]`.

## JavaScript conventions

- JavaScript in this repository is project tooling only (`scripts/`, `.claude/hooks/`), run with Node 20+.
- Format with **Prettier** (`.prettierrc.json`: no semicolons, single quotes, arrow parentheses avoided). Run `npm run format`; the PostToolUse hook formats edited files automatically.
- Use ES Modules (`import`/`export`, `.mjs` files) and the Node standard library (`node:fs`, `node:test`, …). Add dependencies only when the standard library cannot do the job.
- Test with the built-in `node:test` runner in `*.test.mjs` files next to the code they test. Scripts that run on execution must guard that with an "is main module" check so tests can import them.

## Code comments

Leave standard docstring comments for all modules, functions, and for large blocks of complicated code — Python docstrings, JSDoc blocks in JavaScript. Avoid jargon and keep comments concise.

## Specification

The specification is in `docs/SPEC.md`. It describes what the tool does today and what is planned, and it is the source of the GitHub project board. Update it in the same change whenever behaviour changes or a requirement is completed.

The project-board scripts (`scripts/board`) parse `docs/SPEC.md`, so keep these formats when editing it:

- **Sections are `### <N>. <Title>` headings** (e.g. `### 2. Contribution Statistics`); they label a requirement's section.
- **Requirements are `#### <ID> <Title>` subheadings** — `<ID>` is `FAMILY-N` (uppercase family letters, hyphen, number; e.g. `STAT-5`, `REPO-2`). The prose beneath the heading, up to the next heading, becomes the issue body. Families: `REPO`, `STAT`, `FILT`, `OUT`, `CLI`, `PKG` (labels in `scripts/board/config.mjs`).
- **Each requirement has a `**Status:** <status>` line**, one of `Todo`, `In Progress`, `Done`. An unknown status fails `board:derive`.
- **Future Work items are `-` bullets** under `### <N>. Future Work`; they become phase-2 issues keyed by a slug of their first words, so rewording a bullet's start re-keys it.
- **Never change an existing ID** — it keys the issue; renaming or renumbering orphans the old issue and creates a new one.

## Git & project-board workflow

Changes are tracked on the GitHub project board (https://github.com/users/bloombar/projects/4, linked to this repository) and follow a branch → PR flow. Follow this **by default**:

- **Do not commit code changes directly to the default branch (`master`).** Create a feature branch named `feat/<REQ-ID>-<slug>` (e.g. `feat/STAT-6-mailmap`; use a short descriptive slug when no requirement id applies). **Exception:** documentation (Markdown and anything under `docs/`) and project tooling under `scripts/` and `.claude/` may be committed directly to the default branch without a PR.
- **Open a pull request** whose description includes `Closes #N` — `N` is the board issue's number — so the issue closes on merge. Commit and push only when asked, and run the checks above first.
- **Do not hand-create board issues.** The board is generated from the SPEC: `npm run board:derive` regenerates `scripts/board/manifest.yaml`, then `npm run board:sync` creates or updates the issues (`-- --dry-run` previews; `-- --reconcile` forces SPEC statuses back onto the board). A requirement marked `Done` in the SPEC is always closed and moved to Done; other status moves are left to the board unless `--reconcile` is passed.
- **Claude runs both board commands itself** (they are pre-approved in `.claude/settings.json`): `board:derive` whenever `docs/SPEC.md` changes, committing the manifest with the change; `board:sync` **before** opening a PR when the SPEC adds requirements (so `Closes #N` has an issue to point at), and again **after** the PR merges. Sync reads the working tree, so before the merge run it from a tree where the new requirements are still `Todo`/`In Progress` — syncing a branch that already marks them `Done` closes their issues before the code lands.
- Merging a pull request into `master` publishes a release to PyPI once the tests pass on the merged code (see `.github/workflows/build.yaml`); pushes to other branches, and direct pushes to `master`, publish nothing. Bump `version` in `pyproject.toml` in the PR when a change to the package should be released; a merge without a bump skips the upload.

If asked to use a different workflow (e.g. commit code straight to the default branch), **remind the user that it diverges from this flow and confirm before proceeding** — then honor the confirmed request.

## Protected paths

**IMPORTANT:** `.pypirc` holds the PyPI publishing token and `.env*` files hold any other local credentials. A `PreToolUse` hook (`.claude/hooks/guard-paths.sh`, tested by `npm run test:hooks`) blocks writes to them. A block is a signal to stop and report — never route around it.

## Agent workflow

Larger work can run as a supervisor/developer split: `.claude/agents/developer-agent.md` implements a scoped slice against a brief, `.claude/agents/spec-reviewer.md` reviews the diff in fresh context, and the agent doing the work is never the one grading it. The brief template and definition of done are in the `phase-handoff` skill; run the `stale-check` skill before starting or reviewing a slice.
