/**
 * Time windows: the presets, and the one the reader picks the start of.
 *
 * A preset is a distance back from now — "the last 24 hours" — and answers
 * itself again every time it is asked. A custom window is an instant: "since
 * 08:00 this morning", which is a different length of time each time you look
 * at it and always begins in the same place.
 *
 * Both travel as one string, because everything downstream of the picker
 * treats the window as an opaque key: it is what the browser caches the
 * payload under, what is remembered between visits, what goes on the wire, and
 * what the payload echoes back so the page can tell whether the charts on
 * screen are still the window that is selected. A custom window that was a
 * second, parallel piece of state would have needed all of that machinery
 * built again beside itself.
 *
 * So a custom window is the key `since:<ISO instant>`, and the only code that
 * has to know it is not a preset is in this file. The backend reads the same
 * grammar — see `resolve_window` in `telemetry/timeseries.py`.
 */

import type { RangeOption } from './types'

export const CUSTOM_PREFIX = 'since:'

/** The window a fresh visit opens on. */
export const DEFAULT_RANGE = '24h'

/**
 * Used until the server's list arrives, and if that request fails.
 * Mirrors `RANGES` in `atlas_backend/app/telemetry/timeseries.py`.
 */
export const FALLBACK_RANGES: RangeOption[] = [
  { key: '30m', label: '30 min', minutes: 30, bucket_minutes: 1 },
  { key: '1h', label: '1 hour', minutes: 60, bucket_minutes: 1 },
  { key: '3h', label: '3 hours', minutes: 180, bucket_minutes: 2 },
  { key: '5h', label: '5 hours', minutes: 300, bucket_minutes: 3 },
  { key: '12h', label: '12 hours', minutes: 720, bucket_minutes: 5 },
  { key: '24h', label: '24 hours', minutes: 1440, bucket_minutes: 10 },
  { key: '48h', label: '48 hours', minutes: 2880, bucket_minutes: 20 },
  { key: '72h', label: '72 hours', minutes: 4320, bucket_minutes: 30 },
  { key: '5d', label: '5 days', minutes: 7200, bucket_minutes: 60 },
  { key: '7d', label: '7 days', minutes: 10080, bucket_minutes: 60 },
  { key: '14d', label: '14 days', minutes: 20160, bucket_minutes: 180 },
]

/** What the backend will accept, mirroring the same two constants there. */
export const MIN_CUSTOM_MINUTES = 5
export const MAX_CUSTOM_DAYS = 90

export function isCustomRange(key: string): boolean {
  return key.startsWith(CUSTOM_PREFIX)
}

/** The range key for a window opening at this instant and running to now. */
export function customRangeKey(start: Date): string {
  return `${CUSTOM_PREFIX}${start.toISOString()}`
}

/** The instant a custom key opens at, or null if it is not one, or is junk. */
export function customRangeStart(key: string): Date | null {
  if (!isCustomRange(key)) return null
  const parsed = new Date(key.slice(CUSTOM_PREFIX.length))
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

/**
 * Is this a window we can still ask for?
 *
 * The preset list is not fixed forever — this one dropped 15 minutes and
 * gained 5 hours — and the last choice is remembered in localStorage, so a
 * browser that was here before the change comes back asking for a window that
 * no longer exists. Unchecked, that is a dashboard that opens on an error
 * until the reader thinks to click something else.
 */
export function isKnownRange(key: string, options: RangeOption[]): boolean {
  if (isCustomRange(key)) return customRangeStart(key) !== null
  return options.some((option) => option.key === key)
}

/** How long this window is, in minutes, right now. */
export function spanMinutes(key: string, options: RangeOption[]): number {
  const start = customRangeStart(key)
  if (start) return Math.max(0, Math.round((Date.now() - start.getTime()) / 60_000))
  return options.find((option) => option.key === key)?.minutes ?? 0
}

/** The window's name, in the reader's own timezone. */
export function describeRange(key: string, options: RangeOption[]): string {
  const start = customRangeStart(key)
  if (start) return `since ${formatStart(start)}`
  return options.find((option) => option.key === key)?.label ?? key
}

/** "20 Aug, 14:00" — the day and the hour, which is all that was picked. */
export function formatStart(start: Date): string {
  return start.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * A span in words: "3 days 4 hours".
 *
 * Two units at most. A custom window is chosen as a start rather than as a
 * length, so the length is the thing the reader has not been told and wants
 * confirmed — but to the minute it is noise.
 */
export function describeSpan(minutes: number): string {
  if (minutes < 60) return `${minutes} min`

  const days = Math.floor(minutes / 1440)
  const hours = Math.floor((minutes % 1440) / 60)
  if (days > 0) return hours > 0 ? `${days}d ${hours}h` : `${days}d`

  const rest = minutes % 60
  return rest > 0 ? `${hours}h ${rest}m` : `${hours}h`
}

/* --- The datetime-local control -----------------------------------------

   `<input type="datetime-local">` speaks "YYYY-MM-DDTHH:mm" with no timezone
   on it, meaning whatever the clock on the wall says. Everything else here
   works in absolute instants. These two functions are the border between
   them, and they are the only place local time is assumed.
   ---------------------------------------------------------------------- */

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

/** An instant, as the control spells it in the reader's timezone. */
export function toLocalInput(moment: Date): string {
  return (
    `${moment.getFullYear()}-${pad(moment.getMonth() + 1)}-${pad(moment.getDate())}` +
    `T${pad(moment.getHours())}:${pad(moment.getMinutes())}`
  )
}

/** What the control produced, as an absolute instant. Null if unparseable. */
export function fromLocalInput(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(value)
  if (!match) return null

  const [, year, month, day, hour, minute] = match
  // Constructed field by field rather than parsed from the string: this is
  // the reading that is unambiguously local in every browser.
  const moment = new Date(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hour),
    Number(minute),
  )
  return Number.isNaN(moment.getTime()) ? null : moment
}

/** Why this start cannot be charted, or null if it can. */
export function customRangeProblem(start: Date): string | null {
  const minutes = (Date.now() - start.getTime()) / 60_000

  if (minutes < 0) return 'That is in the future.'
  if (minutes < MIN_CUSTOM_MINUTES) {
    return `Too recent to chart — pick at least ${MIN_CUSTOM_MINUTES} minutes back.`
  }
  if (minutes > MAX_CUSTOM_DAYS * 1440) {
    return `Too far back — the longest window is ${MAX_CUSTOM_DAYS} days.`
  }
  return null
}
