/**
 * derive.mjs — build/refresh the board manifest from docs/SPEC.md.
 *
 * Reads the requirement ids, titles, sections, descriptions and statuses from
 * docs/SPEC.md and writes scripts/board/manifest.yaml, which sync.mjs pushes to
 * GitHub. The SPEC is the source of truth: every run regenerates each entry
 * from it. Ids that vanished from the SPEC are kept and reported as stale, so
 * their issues are not orphaned silently.
 *
 * SPEC formats understood (see .claude/CLAUDE.md):
 *   ### <N>. <Section title>          a section
 *   #### <FAMILY-N> <Title>           a requirement; prose beneath is its body
 *   **Status:** Done|In Progress|Todo a line in a requirement's body
 *   - <bullet>                        a Future Work item, under `### <N>. Future Work`
 */
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { parse, stringify } from 'yaml'
import { PHASES, STATUSES } from './config.mjs'

const here = dirname(fileURLToPath(import.meta.url))
const root = join(here, '..', '..')
const SPEC = join(root, 'docs', 'SPEC.md')
const MANIFEST = join(here, 'manifest.yaml')

const DEFAULT_STATUS = 'Todo'
const FUTURE_RE = /^###\s+\d+\.\s+Future Work\s*$/

export const familyOf = id => id.replace(/-\d+.*$/, '')

/** Trim to a word boundary with an ellipsis, for tidy issue titles. */
export const shorten = (s, max) => {
  s = s.replace(/\s+/g, ' ').trim()
  if (s.length <= max) return s
  return (
    s
      .slice(0, max)
      .replace(/\s+\S*$/, '')
      .replace(/[\s—:,;(-]+$/, '') + '…'
  )
}

/** Flatten a chunk of markdown to plain prose for an issue body. */
export const cleanMd = s =>
  s
    .replace(/```[\s\S]*?```/g, ' ') // drop fenced code blocks
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1') // links -> their label text
    .replace(/^\s*[-+*]\s+/gm, ' ') // list bullet markers
    .replace(/^\s*>\s?/gm, '') // block quote markers
    .replace(/[*`#|]/g, '') // emphasis / heading / table pipes
    .replace(/\s+/g, ' ')
    .trim()

/** Read a `**Status:** X` line, checking X is a known board status. */
const statusOf = (lines, id) => {
  for (const line of lines) {
    const m = line.match(/^\s*\*\*Status:?\*\*:?\s*(.+?)\s*$/)
    if (!m) continue
    const status = STATUSES.find(s => s.toLowerCase() === m[1].toLowerCase())
    if (!status)
      throw new Error(
        `${id}: unknown status "${m[1]}" (use one of: ${STATUSES.join(', ')})`,
      )
    return status
  }
  return DEFAULT_STATUS
}

/**
 * Parse the SPEC into requirement items, in document order:
 * { id, title, full?, section, family, phase, status }.
 */
export const parseSpec = text => {
  const items = []
  let section = ''
  let inFuture = false
  let cur = null // requirement currently collecting its body prose

  const flush = () => {
    if (!cur) return
    const prose = cur.body.filter(l => !/^\s*\*\*Status:?\*\*/.test(l))
    const full = shorten(cleanMd(prose.join('\n')), 700)
    const { id, title, ...rest } = cur.item
    items.push({
      id,
      title,
      ...(full && full !== title ? { full } : {}),
      ...rest,
      status: statusOf(cur.body, id),
    })
    cur = null
  }

  for (const line of text.split('\n')) {
    const sec = line.match(/^###\s+(\d+)\.\s+(.+?)\s*$/)
    if (sec) {
      flush()
      section = `§${sec[1]} ${sec[2]}`
      inFuture = FUTURE_RE.test(line)
      continue
    }
    const head = line.match(/^####\s+([A-Z]+-\d+[a-z]?)\s+(.+?)\s*$/)
    if (head) {
      flush()
      cur = {
        item: {
          id: head[1],
          title: head[2].trim(),
          section,
          family: familyOf(head[1]),
          phase: inFuture ? 2 : 1,
        },
        body: [],
      }
      continue
    }
    if (/^#{1,6}\s/.test(line)) {
      flush() // any other heading ends the current item's body
      if (/^#{1,2}\s/.test(line)) inFuture = false
      continue
    }
    if (inFuture && !cur) {
      const item = parseFutureBullet(line, section)
      if (item) items.push(item)
      continue
    }
    if (cur) cur.body.push(line)
  }
  flush()
  return items
}

/** Turn a Future Work bullet into an item keyed by a stable FUTURE-<slug> id. */
const parseFutureBullet = (line, section) => {
  const b = line.match(/^-\s+(.+)$/)
  if (!b) return null
  const lead = b[1].match(/^\*\*(.+?)\*\*/) // bold lead phrase, if any
  const raw = (lead ? lead[1] : b[1])
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/[*`]/g, '')
  const slug = raw
    .split(/\s+/)
    .slice(0, 5)
    .join(' ')
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .trim()
    .replace(/\s+/g, '-')
    .slice(0, 40)
  if (!slug) return null
  const title = shorten(raw.replace(/\s+—.*$/, '').replace(/\.$/, ''), 80)
  const full = shorten(cleanMd(b[1]), 800)
  return {
    id: `FUTURE-${slug}`,
    title,
    ...(full !== title ? { full } : {}),
    section,
    family: 'FUTURE',
    phase: 2,
    status: DEFAULT_STATUS,
  }
}

/** Order manifest entries: by phase, then family, then numeric id. */
export const sortEntries = entries => {
  const numOf = id => Number((id.match(/-(\d+)/) || [])[1] || 0)
  return entries.sort(
    (a, b) =>
      (a.phase ?? 9) - (b.phase ?? 9) ||
      a.family.localeCompare(b.family) ||
      numOf(a.id) - numOf(b.id) ||
      a.id.localeCompare(b.id),
  )
}

/** Build the manifest from the SPEC, merging with any previous manifest. */
const run = () => {
  const items = parseSpec(readFileSync(SPEC, 'utf8'))

  const seen = new Set()
  for (const i of items) {
    if (seen.has(i.id)) throw new Error(`duplicate requirement id ${i.id}`)
    seen.add(i.id)
  }

  // Keep (but warn about) manifest entries no longer in the SPEC.
  const prev = existsSync(MANIFEST) ? parse(readFileSync(MANIFEST, 'utf8')) : []
  const prevIds = new Set((prev || []).map(e => e.id))
  const stale = (prev || []).filter(e => !seen.has(e.id))
  const entries = sortEntries([...items, ...stale])

  const header =
    '# Board manifest — generated from docs/SPEC.md by `npm run board:derive`.\n' +
    '# Do not edit by hand: change docs/SPEC.md and re-derive, then run\n' +
    '# `npm run board:sync`. Ids key the GitHub issues, so never change them.\n\n'
  writeFileSync(MANIFEST, header + stringify(entries))

  // Report.
  const count = key =>
    entries.reduce((m, e) => ({ ...m, [e[key]]: (m[e[key]] || 0) + 1 }), {})
  const byPhase = count('phase')
  const byStatus = count('status')
  console.log(`Wrote ${entries.length} entries to ${MANIFEST}`)
  console.log(
    `  by phase: ${PHASES.map(p => `P${p}=${byPhase[p] || 0}`).join('  ')}`,
  )
  console.log(
    `  by status: ${STATUSES.map(s => `${s}=${byStatus[s] || 0}`).join('  ')}`,
  )
  if (prevIds.size) {
    const news = items.filter(e => !prevIds.has(e.id)).map(e => e.id)
    console.log(
      `  new since last run: ${news.length ? news.join(', ') : 'none'}`,
    )
  }
  if (stale.length)
    console.log(
      `  STALE (in manifest, not in SPEC): ${stale.map(e => e.id).join(', ')}`,
    )
}

// Run only when executed directly, so tests can import the parsers.
if (process.argv[1] === fileURLToPath(import.meta.url)) run()
