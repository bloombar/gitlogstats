/**
 * Tests for the SPEC parser that feeds the project board.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { parseSpec, shorten, sortEntries } from './derive.mjs'

const SPEC = `# Title

## Requirements

### 1. Statistics

Intro prose that belongs to no requirement.

#### STAT-1 Commit count

Counts commits.
Even with **multi-line** messages.

**Status:** Done

#### STAT-2 Lines changed

**Status:** in progress

Insertions and deletions.

#### STAT-3 Not started

### 2. Future Work

- **Author-date filtering** — filter by author date instead.
- Parallel cloning of [many](https://example.com) repositories.

## Appendix

- not a future item
`

test('parses requirement ids, titles, sections and families', () => {
  const items = parseSpec(SPEC)
  const stat1 = items.find(i => i.id === 'STAT-1')
  assert.equal(stat1.title, 'Commit count')
  assert.equal(stat1.section, '§1 Statistics')
  assert.equal(stat1.family, 'STAT')
  assert.equal(stat1.phase, 1)
})

test('the prose beneath a heading becomes the body, without the status line', () => {
  const stat1 = parseSpec(SPEC).find(i => i.id === 'STAT-1')
  assert.equal(stat1.full, 'Counts commits. Even with multi-line messages.')
})

test('status comes from the Status line, case-insensitively, defaulting to Todo', () => {
  const byId = Object.fromEntries(parseSpec(SPEC).map(i => [i.id, i]))
  assert.equal(byId['STAT-1'].status, 'Done')
  assert.equal(byId['STAT-2'].status, 'In Progress')
  assert.equal(byId['STAT-3'].status, 'Todo')
  assert.equal(byId['STAT-3'].full, undefined)
})

test('an unknown status is an error, not a silent default', () => {
  assert.throws(
    () => parseSpec('### 1. S\n\n#### STAT-1 X\n\n**Status:** Finished\n'),
    /unknown status "Finished"/,
  )
})

test('Future Work bullets become phase-2 items with stable slug ids', () => {
  const future = parseSpec(SPEC).filter(i => i.family === 'FUTURE')
  assert.deepEqual(
    future.map(i => [i.id, i.title, i.phase, i.section]),
    [
      [
        'FUTURE-author-date-filtering',
        'Author-date filtering',
        2,
        '§2 Future Work',
      ],
      [
        'FUTURE-parallel-cloning-of-many-repositories',
        'Parallel cloning of many repositories',
        2,
        '§2 Future Work',
      ],
    ],
  )
})

test('bullets outside Future Work are ignored', () => {
  assert.ok(!parseSpec(SPEC).some(i => /not-a-future/.test(i.id)))
})

test('shorten trims at a word boundary', () => {
  assert.equal(shorten('one two three', 9), 'one two…')
  assert.equal(shorten('short', 9), 'short')
})

test('entries sort by phase, family, then number', () => {
  const e = (id, phase) => ({ id, phase, family: id.split('-')[0] })
  assert.deepEqual(
    sortEntries([
      e('STAT-10', 1),
      e('FUTURE-x', 2),
      e('STAT-2', 1),
      e('OUT-1', 1),
    ]).map(x => x.id),
    ['OUT-1', 'STAT-2', 'STAT-10', 'FUTURE-x'],
  )
})
