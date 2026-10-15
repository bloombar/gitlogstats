---
name: phase-handoff
description: The brief template and definition of done for handing a slice to developer-agent. Use when scoping work on gitlogstats.
---

# Handing off a slice

A slice is work small enough that its **diff can be reviewed in one pass**. If you cannot describe the change in a few sentences, split it.

## The brief template

A brief without a runnable check is not ready to hand over. That check is the whole point: it is what lets the loop close without a human watching it.

````markdown
## Slice: <short name>

**SPEC ids:** <FAMILY-N, …> (must already exist in docs/SPEC.md, or be added by this slice)
**Branch:** feat/<REQ-ID>-<slug>, cut from `master` (the default branch)

### Goal

One paragraph. What exists after this slice that did not before.

### Files and interfaces

- `src/gitlogstats/<file>.py` — what it must contain
- Reuse `existingHelper()` from an existing module rather than writing a new one

### Out of scope

Explicitly. Name the adjacent things you do NOT want touched — this is the line that keeps the diff reviewable, and the reviewer checks it.

### Verification

```bash
<the exact command, and what its output must show>
```

### Notes

Prior art elsewhere in this repo, and any decision already taken that constrains the implementation.
````

## Definition of done

- `python -m pytest -q` and `black --check src tests` pass — plus `npm run format:check`, and `npm run test:scripts` if the slice touched `scripts/` or `npm run test:hooks` if it touched `.claude/hooks/`
- Both reviewers have run and every **must-fix** finding is resolved
- New behaviour has a test that **fails without the change**; statistics changes have an integration test on a real git repository
- `docs/SPEC.md` describes the new behaviour, with the requirement's `**Status:**` updated
- `npm run board:derive` has been run and `scripts/board/manifest.yaml` is committed with the change
- Requirement ids cited in code comments where implemented
- `README.md` updated if a command-line option, default or output changed
- Judgment calls the brief did not settle are recorded in the PR description
- The PR body carries `Closes #N`

## The loop

1. Run `stale-check`. An open PR touching these files means coordinate, not proceed.
2. Spawn `developer-agent` with the brief.
3. Run `/code-review` and `spec-reviewer` in parallel on the diff. Effort scales with blast radius — high for anything that changes how statistics are computed or what is printed to standard output, since users compare and grade on those numbers.
4. Triage. **must-fix** → back to the developer. **cheap-fix** → only within files already touched. **note** → the PR description or a Future Work bullet in the SPEC, and ship.
5. Commit, push, open the PR with `Closes #N` (verify the number — issues are not numbered in family order).
6. After merge, run `npm run board:sync` if the SPEC changed, so the board reflects it.

**Two rounds of rework, maximum.** A third means the slice was mis-scoped rather than merely wrong — re-split it and write a sharper brief.
