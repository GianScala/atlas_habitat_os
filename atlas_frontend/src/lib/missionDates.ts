/**
 * Calendar arithmetic on `YYYY-MM-DD`, done without leaving that form.
 *
 * The obvious way — `new Date(text)`, add days, `toISOString().slice(0, 10)` —
 * is wrong, and wrong quietly. `new Date('2026-08-23T00:00:00')` is local
 * midnight, and `toISOString` reads it back in UTC, so on any machine ahead of
 * UTC the answer lands on the day before. A mission declared as 30 days from
 * the 23rd reported the 20th of September instead of the 21st: a whole day of
 * plan, gone, on a page whose entire job is to be exact about days.
 *
 * So the arithmetic is done in UTC from end to end. `Date.UTC` builds the
 * instant, the shift happens in UTC, and the digits come back out in UTC —
 * three operations in one frame, which is the only way this stays true on
 * every machine a crew might open it on.
 *
 * These are for LABELS ONLY. The backend derives the real end date, the real
 * mission days, and the real allowances from the start and the length it
 * stored; nothing here is ever sent back or computed against.
 */

/** `2026-08-23` plus `days`, as `2026-09-21`. Null if the input is not a date. */
export function shiftDate(text: string, days: number): string | null {
  const parts = parseDate(text)
  if (parts === null || !Number.isFinite(days)) return null

  const shifted = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2] + days))
  return format(shifted)
}

/** The last day of a mission: its start, plus its length, less the first day. */
export function endOfMission(start: string, days: number): string | null {
  if (!Number.isInteger(days) || days < 1) return null
  return shiftDate(start, days - 1)
}

/** The calendar date of mission day `index`, counting MD-01 as 1. */
export function dateOfMissionDay(
  start: string | null,
  index: number,
  days: number | null,
): string | null {
  if (!start || !Number.isInteger(index) || index < 1) return null
  if (days !== null && index > days) return null
  return shiftDate(start, index - 1)
}

function parseDate(text: string): [number, number, number] | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text.trim())
  if (!match) return null
  const parts: [number, number, number] = [
    Number(match[1]),
    Number(match[2]),
    Number(match[3]),
  ]
  // Rejects 2026-02-31: the constructor rolls it forward rather than failing,
  // and a silently corrected date is worse than a blank label.
  const built = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]))
  return format(built) === text.trim() ? parts : null
}

function format(when: Date): string | null {
  if (Number.isNaN(when.getTime())) return null
  return when.toISOString().slice(0, 10)
}
