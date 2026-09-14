/**
 * Reading the crew's meter log out loud.
 *
 * The backend does every sum; nothing here re-derives a figure. What this file
 * does is decide how the figures are SAID, and the decisions are all versions
 * of the same one: never let a hand-taken reading and a derived consumption
 * look like the same kind of number.
 *
 * Hence four ways of having no figure, kept apart everywhere they are shown:
 *
 *   a box nobody filled in           an empty input
 *   a block still waiting to close   "open" — provisional, not low
 *   a round that was missed          "gap" — somebody has to go and read a dial
 *   a meter that counted down        "check" — the reading is wrong, not the meter
 *
 * Collapsing those into one dash is the single most misleading thing this page
 * could do, because three of the four are actionable and they ask for three
 * different actions.
 */

import type { BlockStatus, LogResource, LogWindow, ResourceTracking, Share } from './types'

/** What a block's state means, in the fewest words that still say it. */
export const BLOCK_LABEL: Record<BlockStatus, string> = {
  ok: 'Measured',
  open: 'Still open',
  gap: 'Round missed',
  backwards: 'Check the reading',
}

export const BLOCK_HINT: Record<BlockStatus, string> = {
  ok: 'Derived from this reading and the one that closes it.',
  open:
    'Waiting on the reading that closes it. This is not a quiet block — it ' +
    'is a block nobody has finished measuring yet.',
  gap:
    'Both rounds have been walked and one of the two readings was never ' +
    'written down. Somebody has to go and read the dial.',
  backwards:
    'The closing reading is lower than the opening one. A meter face counts ' +
    'up, so one of the two figures is mistyped — and until it is fixed, both ' +
    'are left out of every total on this page.',
}

/**
 * The eight categorical slots, in the order they are handed out.
 *
 * Same list, same order, and the same rule as `lib/palette.ts`: a ninth hue is
 * never generated, because the eight were validated as a set and a ninth
 * invented at runtime has been checked against nothing. Nothing this page
 * colours ever needs more than eight — seven rooms, five kinds of tap use, two
 * temperatures, two rounds — and the eleven taps are deliberately ranked as
 * bars rather than coloured as slices for exactly that reason.
 */
const SLOTS = [
  'var(--series-1)',
  'var(--series-2)',
  'var(--series-3)',
  'var(--series-4)',
  'var(--series-5)',
  'var(--series-6)',
  'var(--series-7)',
  'var(--series-8)',
] as const

/** A stable colour per slice, by position in a list that never grows past 8. */
export function sliceColour(index: number): string {
  return SLOTS[index % SLOTS.length] as string
}

/**
 * Warm and cold, coloured as what they are rather than categorically.
 *
 * The one place on this page colour carries a meaning rather than an identity.
 * Warm water is water AND the power that heated it, which is the actionable
 * half of the water story, and drawing it in the palette's arbitrary next hue
 * would throw away a reading the eye gets for free.
 */
export const STREAM_COLOUR: Record<string, string> = {
  warm: 'var(--series-2)',
  cold: 'var(--series-1)',
  none: 'var(--text-faint)',
}

/** The two rounds, kept apart from the eight categorical slots for the same reason. */
export const SLOT_COLOUR: Record<string, string> = {
  morning: 'var(--series-4)',
  evening: 'var(--series-7)',
  daily: 'var(--series-1)',
}

/** `0.42` -> `42%`, and nothing at all where the share is undefined. */
export function share(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '—'
  // A slice under half a percent still gets a mark rather than rounding to a
  // "0%" that reads as "none".
  if (value > 0 && value < 0.005) return '<1%'
  return `${Math.round(value * 100)}%`
}

/** How much of the sheet has been filled in, as the page says it. */
export function coverageReading(resource: LogResource): string {
  const { expected, expected_filled: filled } = resource.coverage
  if (expected === 0) {
    return 'No rounds have come due yet — the sheet fills in as the mission runs.'
  }
  if (filled >= expected) {
    return `Every round walked so far is written down: ${filled} of ${expected}.`
  }
  const missing = expected - filled
  return (
    `${filled} of ${expected} rounds written down. ${missing} ` +
    `${missing === 1 ? 'reading is' : 'readings are'} missing, and every block ` +
    'either side of one of those is left out of the figures below.'
  )
}

/**
 * What a window's total is worth trusting as, said before the number is read.
 *
 * A window whose last day is still open is not wrong, it is provisional, and
 * the difference matters most on the "latest day" card — which is always
 * provisional until the next morning's round closes it.
 */
export function windowCaveat(window: LogWindow, resource: LogResource): string | null {
  if (window.total === null) {
    // With nothing logged at all, the ring in this same card has already said
    // so at length. Repeating it under the ring is two sentences where the
    // reader needed none.
    return resource.coverage.filled === 0
      ? null
      : 'No block in this window has both of its readings yet. Every one of ' +
        'them is still waiting on a round, or missing one.'
  }
  if (!window.complete) {
    return (
      'Provisional. At least one block here is still waiting on the reading ' +
      'that closes it, so this total can only go up.'
    )
  }
  return null
}

/**
 * One line naming the biggest single meter in a window.
 *
 * Always the METER, even on the water card whose ring is grouped — "the
 * showers are half our water" is where to look, and "the warm feed on shower
 * one is a quarter of it" is what to do about it. The wording says "single
 * meter" so the figure is never read as disagreeing with the ring above it,
 * which is drawn at a coarser grain.
 */
export function topDraw(window: LogWindow): string | null {
  const [first] = window.meters
  if (!first || window.total === null || first.amount <= 0) return null
  return (
    `${first.label} is the largest single meter at ${share(first.share)} of ` +
    'the window.'
  )
}

/** Slices worth drawing: the ones that actually drew something. */
export function drawable(shares: Share[]): Share[] {
  return shares.filter((slice) => slice.amount > 0)
}

/**
 * The habitat meter's figure for the same mission days the crew logged.
 *
 * The whole point of the log is to be an INDEPENDENT account, so the two are
 * only ever compared over days both of them measured — day by day, matched on
 * the mission day, never total against total. A crew log covering MD-01 to
 * MD-04 held up against a habitat meter covering the whole mission to now
 * would show a shortfall that is nothing but the difference in the windows.
 */
export interface Reconciliation {
  /** Mission days where both accounts have a figure. */
  days: { code: string; logged: number; measured: number }[]
  logged: number
  measured: number
  difference: number
  /** The gap as a share of the habitat meter's figure, or null at zero. */
  fraction: number | null
  /** Set when the two are not in the same unit and must not be subtracted. */
  mismatch: string | null
}

export function reconcile(
  resource: LogResource,
  tracked: ResourceTracking | null,
  trackedUnit: string,
): Reconciliation | null {
  if (!tracked) return null

  if (trackedUnit && trackedUnit !== resource.unit) {
    return {
      days: [],
      logged: 0,
      measured: 0,
      difference: 0,
      fraction: null,
      mismatch:
        `The habitat meter reports ${trackedUnit} and the crew log reports ` +
        `${resource.unit}. Until those are the same unit the two figures are ` +
        'shown side by side and never subtracted.',
    }
  }

  const measured = new Map(tracked.days.map((day) => [day.index, day.actual]))
  const days: Reconciliation['days'] = []

  for (const day of resource.days) {
    const theirs = measured.get(day.index)
    // Only a day BOTH accounts closed. An incomplete crew day would report a
    // shortfall that is just a round not yet walked.
    if (day.total === null || !day.complete) continue
    if (theirs === undefined || theirs === null) continue
    days.push({ code: day.code, logged: day.total, measured: theirs })
  }

  if (days.length === 0) return null

  const logged = days.reduce((sum, day) => sum + day.logged, 0)
  const total = days.reduce((sum, day) => sum + day.measured, 0)

  return {
    days,
    logged,
    measured: total,
    difference: logged - total,
    fraction: total === 0 ? null : (logged - total) / total,
    mismatch: null,
  }
}

/**
 * What the difference between the two accounts means, said as a finding.
 *
 * Sub-meters summing to slightly under a whole-habitat meter is the expected
 * result — there are loads on the mains that no room owns. A large gap either
 * way is the thing this whole page exists to surface, so it is stated rather
 * than left as a percentage for the reader to judge.
 */
export function reconciliationReading(
  check: Reconciliation,
  unit: string,
  resource: string,
): string {
  const gap = Math.abs(check.difference)
  const pct = check.fraction === null ? null : Math.abs(check.fraction)

  if (pct !== null && pct < 0.05) {
    return (
      'The two accounts agree to within 5%. The crew log and the habitat ' +
      'database are measuring the same habitat.'
    )
  }

  if (check.difference < 0) {
    return (
      `The sub-meters account for ${format(gap)} ${unit} less than the ` +
      `habitat meter over the same ${check.days.length} days. Some of that is ` +
      `expected — there are ${resource} loads on the mains that no room owns — ` +
      'but a gap this size is worth walking down.'
    )
  }

  return (
    `The sub-meters account for ${format(gap)} ${unit} MORE than the habitat ` +
    `meter over the same ${check.days.length} days. That cannot be right: the ` +
    'parts cannot exceed the whole. Check for a mistyped reading, or for a ' +
    'meter being read into the wrong row.'
  )
}

function format(value: number): string {
  return Math.abs(value) >= 100
    ? Math.round(value).toLocaleString()
    : value.toFixed(1)
}
