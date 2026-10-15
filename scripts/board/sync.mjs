/**
 * sync.mjs — idempotently push the board manifest to GitHub.
 *
 * For each manifest entry it upserts a repo issue (keyed by a hidden marker so
 * re-runs never duplicate), files it under the phase's milestone, adds it to the
 * project, and — on first creation — seeds its Status column and closed-state.
 *
 * Ownership split (so re-runs don't fight the live workflow/automation):
 *   - manifest-owned, re-enforced every run: title, body, milestone (phase),
 *     the `spec` label.
 *   - board-owned after creation: Status column and open/closed. Seeded once at
 *     creation from the manifest; thereafter left to the team + Actions
 *     automation — except that a requirement the SPEC marks Done is always
 *     closed and moved to Done. Pass --reconcile to force the manifest's
 *     status/state back on in both directions.
 *
 * Flags:
 *   --dry-run     no writes; print intended actions
 *   --limit N     only process the first N manifest entries
 *   --reconcile   force manifest Status + open/closed onto the board (else the
 *                 board owns Status after an issue's creation)
 *   --prune       DELETE issues that carry our marker but are no longer in the
 *                 manifest (removes their card too). Permanent; opt-in.
 * Requires: gh CLI authenticated with the `project` scope.
 */
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { parse } from 'yaml'
import {
  OWNER,
  PROJECT_NUMBER,
  REPO,
  MILESTONE_TITLE,
  MILESTONE_DUE,
  marker,
  MARKER_RE,
  specLink,
  familyLabel,
} from './config.mjs'

const here = dirname(fileURLToPath(import.meta.url))
const MANIFEST = join(here, 'manifest.yaml')

const args = process.argv.slice(2)
const DRY = args.includes('--dry-run')
const RECONCILE = args.includes('--reconcile')
const PRUNE = args.includes('--prune')
const LIMIT = (() => {
  const i = args.indexOf('--limit')
  return i >= 0 ? Number(args[i + 1]) : Infinity
})()

const counts = {
  created: 0,
  updated: 0,
  closed: 0,
  reopened: 0,
  statusSet: 0,
  added: 0,
  unchanged: 0,
  deleted: 0,
}

/** Run gh. Read-only calls always run; mutations are skipped under --dry-run. */
const gh = (argv, { mutating = false, json = false } = {}) => {
  if (mutating && DRY) return null
  const out = execFileSync('gh', argv, {
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  })
  return json ? JSON.parse(out) : out.trim()
}

const norm = s => (s || '').replace(/\r\n/g, '\n').trim()
const titleOf = e => `${e.id} — ${e.title}`

// Branch the issue bodies deep-link into for SPEC anchors: the repo's GitHub
// default branch (which holds the current SPEC), overridable with SPEC_BRANCH.
const specBranch =
  process.env.SPEC_BRANCH ||
  (() => {
    try {
      return gh([
        'repo',
        'view',
        REPO,
        '--json',
        'defaultBranchRef',
        '-q',
        '.defaultBranchRef.name',
      ])
    } catch {
      return 'master'
    }
  })()

/**
 * Add an issue to the project by its GraphQL node id and return the item id.
 * addProjectV2ItemById is idempotent: for an issue already on the project
 * (e.g. via the Auto-add workflow) it returns the existing item. Used instead
 * of `gh project item-add`, which reports "resource not found" for issues in
 * a repository linked to a user-owned project.
 */
const addItem = nodeId => {
  const data = gh(
    [
      'api',
      'graphql',
      '-f',
      'query=mutation($p:ID!,$c:ID!){addProjectV2ItemById(input:{projectId:$p,contentId:$c}){item{id}}}',
      '-f',
      `p=${projectId}`,
      '-f',
      `c=${nodeId}`,
    ],
    { mutating: true, json: true },
  )
  if (DRY) return null
  const id = data?.data?.addProjectV2ItemById?.item?.id
  if (!id) throw new Error(`could not add ${nodeId} to the project`)
  return id
}

/** The GraphQL node id of an issue, by number. */
const nodeIdOf = number =>
  gh(['api', `repos/${REPO}/issues/${number}`, '-q', '.node_id'])

const bodyOf = e =>
  `${marker(e.id)}\n**${e.id} — ${e.title}**` +
  (e.full ? `\n\n${e.full}` : '') +
  `\n\nSpec: ${e.section} · [SPEC.md](${specLink(e.id, e.title, specBranch)})\n` +
  `Phase ${e.phase} · managed by \`scripts/board\` — do not edit the marker line above.`

// ---- Discover live project + repo state ----
console.log(
  `${DRY ? '[dry-run] ' : ''}Syncing ${REPO} → project ${OWNER}/${PROJECT_NUMBER}`,
)

const project = gh(
  [
    'project',
    'view',
    String(PROJECT_NUMBER),
    '--owner',
    OWNER,
    '--format',
    'json',
  ],
  { json: true },
)
const projectId = project.id
const fields = gh(
  [
    'project',
    'field-list',
    String(PROJECT_NUMBER),
    '--owner',
    OWNER,
    '--format',
    'json',
    '--limit',
    '100',
  ],
  { json: true },
).fields
const statusField = fields.find(f => f.name === 'Status')
if (!statusField || !statusField.options)
  throw new Error('Status single-select field not found on the project')
const statusOptionId = name => {
  const o = statusField.options.find(o => o.name === name)
  if (!o)
    throw new Error(
      `Status option "${name}" not found (have: ${statusField.options.map(o => o.name).join(', ')})`,
    )
  return o.id
}

// Milestones: ensure one per phase exists.
const milestones = gh(
  ['api', `repos/${REPO}/milestones?state=all&per_page=100`],
  { json: true },
)
const milestoneByTitle = new Map(milestones.map(m => [m.title, m]))
for (const [phase, title] of Object.entries(MILESTONE_TITLE)) {
  if (milestoneByTitle.has(title)) continue
  console.log(`  + milestone "${title}"`)
  const argv = ['api', `repos/${REPO}/milestones`, '-f', `title=${title}`]
  if (MILESTONE_DUE[phase])
    argv.push('-f', `due_on=${MILESTONE_DUE[phase]}T00:00:00Z`)
  const created = gh(argv, { mutating: true, json: true })
  if (created) milestoneByTitle.set(title, created)
}

// Marker label so humans can filter these issues in the repo.
gh(
  [
    'label',
    'create',
    'spec',
    '-R',
    REPO,
    '--color',
    '0e8a16',
    '--description',
    'Tracked SPEC requirement',
    '--force',
  ],
  { mutating: true },
)

// Existing issues keyed by marker.
const issues = gh(
  [
    'issue',
    'list',
    '-R',
    REPO,
    '--state',
    'all',
    '--limit',
    '1000',
    '--json',
    'id,number,title,body,state,url,milestone,labels',
  ],
  { json: true },
)
const issueByReq = new Map()
for (const it of issues) {
  const m = norm(it.body).match(MARKER_RE)
  if (m) issueByReq.set(m[1], it)
}

// Existing project items keyed by issue number.
const items = gh(
  [
    'project',
    'item-list',
    String(PROJECT_NUMBER),
    '--owner',
    OWNER,
    '--format',
    'json',
    '--limit',
    '1000',
  ],
  { json: true },
).items
const itemByNumber = new Map()
for (const it of items) {
  if (it.content && typeof it.content.number === 'number')
    itemByNumber.set(it.content.number, it)
}

// ---- Load manifest ----
let manifest = parse(readFileSync(MANIFEST, 'utf8')) || []
const manifestIds = new Set(manifest.map(e => e.id))

// Ensure a label per task family (from the FULL manifest, before --limit).
for (const fam of [...new Set(manifest.map(e => e.family))]) {
  const { name, color, description } = familyLabel(fam)
  gh(
    [
      'label',
      'create',
      name,
      '-R',
      REPO,
      '--color',
      color,
      '--description',
      description,
      '--force',
    ],
    { mutating: true },
  )
}

if (LIMIT !== Infinity) manifest = manifest.slice(0, LIMIT)

// ---- Upsert each entry ----
for (const e of manifest) {
  const wantTitle = titleOf(e)
  const wantBody = bodyOf(e)
  const wantMilestone = MILESTONE_TITLE[e.phase]
  const wantClosed = e.status === 'Done'
  const wantLabels = ['spec', familyLabel(e.family).name]
  let issue = issueByReq.get(e.id)
  let justCreated = false

  if (!issue) {
    // Create the issue (open), then file + close as needed.
    console.log(`  + issue  ${wantTitle}`)
    const argv = [
      'issue',
      'create',
      '-R',
      REPO,
      '--title',
      wantTitle,
      '--body',
      wantBody,
      ...wantLabels.flatMap(l => ['--label', l]),
    ]
    if (wantMilestone) argv.push('--milestone', wantMilestone)
    const url = gh(argv, { mutating: true })
    counts.created++
    justCreated = true
    if (DRY) continue // no number to work with in dry-run
    const number = Number(url.split('/').pop())
    issue = { id: nodeIdOf(number), number, url, state: 'OPEN' }
    if (wantClosed) {
      gh(['issue', 'close', '-R', REPO, String(number)], { mutating: true })
      counts.closed++
    }
  } else {
    // Enforce manifest-owned fields (title/body/milestone/label) on drift.
    const edits = []
    if (norm(issue.title) !== norm(wantTitle)) edits.push('--title', wantTitle)
    if (norm(issue.body) !== norm(wantBody)) edits.push('--body', wantBody)
    if (wantMilestone && issue.milestone?.title !== wantMilestone)
      edits.push('--milestone', wantMilestone)
    const have = new Set((issue.labels || []).map(l => l.name))
    const missingLabels = wantLabels.filter(l => !have.has(l))
    if (edits.length || missingLabels.length) {
      console.log(`  ~ issue  #${issue.number} ${wantTitle}`)
      gh(
        [
          'issue',
          'edit',
          '-R',
          REPO,
          String(issue.number),
          ...edits,
          ...missingLabels.flatMap(l => ['--add-label', l]),
        ],
        { mutating: true },
      )
      counts.updated++
    } else {
      counts.unchanged++
    }

    // Status/open-state are board-owned after creation, except that Done in
    // the SPEC always closes the issue; --reconcile also reopens.
    {
      if (wantClosed && issue.state !== 'CLOSED') {
        gh(['issue', 'close', '-R', REPO, String(issue.number)], {
          mutating: true,
        })
        counts.closed++
      } else if (RECONCILE && !wantClosed && issue.state === 'CLOSED') {
        gh(['issue', 'reopen', '-R', REPO, String(issue.number)], {
          mutating: true,
        })
        counts.reopened++
      }
    }
  }

  if (DRY && !issue.number) continue

  // Ensure the issue is a project item.
  let item = itemByNumber.get(issue.number)
  if (!item) {
    const itemId = addItem(issue.id)
    counts.added++
    if (itemId) item = { id: itemId, status: null }
  }

  // Seed Status on first add, move to Done when the SPEC says so, or force it
  // under --reconcile; else leave the live board alone.
  const wantStatus = e.status
  if (
    item &&
    (justCreated || RECONCILE || wantClosed) &&
    item.status !== wantStatus
  ) {
    gh(
      [
        'project',
        'item-edit',
        '--project-id',
        projectId,
        '--id',
        item.id,
        '--field-id',
        statusField.id,
        '--single-select-option-id',
        statusOptionId(wantStatus),
      ],
      { mutating: true },
    )
    counts.statusSet++
  }
}

// ---- Orphans: managed issues whose id left the manifest ----
// Only issues carrying our marker are considered — unmanaged issues are never
// touched. With --prune, delete them (and thus their project card); otherwise
// just report. Deleting an issue is permanent, so it is opt-in.
const orphans = [...issueByReq.entries()].filter(([id]) => !manifestIds.has(id))
if (orphans.length) {
  if (PRUNE) {
    for (const [id, iss] of orphans) {
      console.log(`  - delete #${iss.number} (${id})`)
      gh(['issue', 'delete', String(iss.number), '-R', REPO, '--yes'], {
        mutating: true,
      })
      counts.deleted++
    }
  } else {
    console.log(
      `\n  ! ${orphans.length} managed issue(s) no longer in the manifest: ${orphans.map(([id]) => id).join(', ')}`,
    )
    console.log('    (re-run with --prune to delete them, or remove by hand)')
  }
}

// ---- Report ----
const review = manifest.filter(e => e.review).map(e => e.id)
console.log(`\n${DRY ? '[dry-run] ' : ''}Done.`)
console.log(
  `  created=${counts.created} updated=${counts.updated} unchanged=${counts.unchanged} ` +
    `added=${counts.added} statusSeeded=${counts.statusSet} closed=${counts.closed} reopened=${counts.reopened} deleted=${counts.deleted}`,
)
if (review.length)
  console.log(
    `  note: ${review.length} manifest row(s) still flagged review: ${review.join(', ')}`,
  )
