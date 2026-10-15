/**
 * Shared configuration for the project-board scripts (derive.mjs, sync.mjs).
 * Field/option IDs are intentionally NOT hard-coded here — sync.mjs discovers
 * them from the live project at runtime so option-id changes don't break it.
 */

// The GitHub Project and the repo its issues live in.
export const OWNER = 'bloombar'
export const PROJECT_NUMBER = 4
export const REPO = 'bloombar/git-developer-contribution-analysis'

// Phases are carried by repo Milestones; the project's built-in Milestone
// field can be used to filter by phase. Titles must match the milestones.
// Phase 1 is everything specified in the SPEC's numbered sections; phase 2 is
// the SPEC's Future Work section.
export const PHASES = [1, 2]
export const MILESTONE_TITLE = {
  1: 'Phase 1 — Current release',
  2: 'Phase 2 — Future Work',
}
// Optional due dates per phase (none set).
export const MILESTONE_DUE = {}

// The Status single-select drives the board columns. These names must match
// the existing option names on the project's Status field exactly (these are
// GitHub's defaults for a new project).
export const STATUSES = ['Todo', 'In Progress', 'Done']

// Per-family labels so the different types of task are distinguishable in the
// repo and on the board. Keyed by requirement family (REPO, STAT, …).
export const FAMILY_LABEL = {
  REPO: {
    name: 'area:repositories',
    color: '1d76db',
    description: 'Repository selection, cloning & branches',
  },
  STAT: {
    name: 'area:statistics',
    color: '0e8a16',
    description: 'Contribution statistics & attribution',
  },
  FILT: {
    name: 'area:filtering',
    color: '5319e7',
    description: 'Date range, user & file filters',
  },
  OUT: {
    name: 'area:output',
    color: 'fbca04',
    description: 'Output formats',
  },
  CLI: {
    name: 'area:cli',
    color: 'd93f0b',
    description: 'Command-line interface',
  },
  PKG: {
    name: 'area:packaging',
    color: '555555',
    description: 'Packaging, CI & release',
  },
  FUTURE: {
    name: 'area:future',
    color: 'ededed',
    description: 'Future work',
  },
}
export const familyLabel = family =>
  FAMILY_LABEL[family] || {
    name: `area:${family.toLowerCase()}`,
    color: 'ededed',
    description: '',
  }

// Hidden marker that keys an issue to a requirement id — the idempotency anchor.
export const marker = id => `<!-- gls-req: ${id} -->`
export const MARKER_RE = /<!--\s*gls-req:\s*([A-Za-z0-9.-]+)\s*-->/

/** GitHub heading-anchor slug (matches GitHub's own algorithm closely enough). */
export const anchorSlug = text =>
  text
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .trim()
    .replace(/\s+/g, '-')

/** Deep link to a requirement's section in the SPEC on the given branch. */
export const specLink = (id, title, branch) =>
  `https://github.com/${REPO}/blob/${branch}/docs/SPEC.md#${anchorSlug(`${id} ${title}`)}`
