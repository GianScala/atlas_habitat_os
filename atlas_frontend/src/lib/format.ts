/** Small presentation helpers shared across components. */

import type { TraceStep } from './types'

/** `get_latest` -> `get latest`, for a label a reader can skim. */
export function humaniseToolName(name: string): string {
  return name.replace(/_/g, ' ')
}

/** Tool arguments as a compact `key=value` line. */
export function formatToolInput(input: Record<string, unknown>): string {
  const parts = Object.entries(input).map(([key, value]) => {
    if (value === null || value === undefined) return `${key}=—`
    if (typeof value === 'object') return `${key}=${JSON.stringify(value)}`
    return `${key}=${String(value)}`
  })
  return parts.join('  ')
}

/** A one-line summary of what a step did, for the collapsed trace header. */
export function summariseTrace(steps: TraceStep[]): string {
  if (steps.length === 0) return 'No queries'

  const failed = steps.filter((s) => s.status === 'failed').length
  const empty = steps.filter((s) => s.status === 'empty').length
  const noun = steps.length === 1 ? 'query' : 'queries'

  if (failed > 0) return `${steps.length} ${noun}, ${failed} failed`
  if (empty > 0) return `${steps.length} ${noun}, ${empty} with no data`
  return `${steps.length} ${noun}`
}

/**
 * What the health check's `measurement_count` actually counts.
 *
 * An InfluxDB "measurement" is a kind of reading, not a sensor and not a
 * datapoint: `Temperature`, `CO2`, `Energy`, `Water`. One of them covers
 * every thermometer in the habitat. A bare "37 measurements" in the chrome
 * read as a quantity of something unspecified, so the number is now only
 * ever shown with the noun that says what it is — and the long form spells
 * out what a reader is being told.
 */
export function describeMeasurements(count: number): string {
  const noun = count === 1 ? 'type' : 'types'
  return (
    `${count} measurement ${noun} available — one per kind of reading ` +
    `(Temperature, CO₂, Energy, Water, …), each covering every sensor that ` +
    `reports it. InfluxDB's own internal metrics are excluded.`
  )
}

/**
 * Bytes as gigabytes, the way a download is talked about.
 *
 * Decimal GB rather than GiB, because that is the figure the Ollama catalogue
 * quotes and the two appearing side by side with a 7% discrepancy would read
 * as a bug.
 */
export function formatGigabytes(bytes: number): string {
  const gb = bytes / 1e9
  if (gb >= 10) return `${Math.round(gb)} GB`
  if (gb >= 1) return `${gb.toFixed(1)} GB`
  return `${Math.max(1, Math.round(bytes / 1e6))} MB`
}

/**
 * How long an answer took, at the precision that reading is worth.
 *
 * A local model answers in tens of seconds, so one decimal on the seconds is
 * enough to tell two runs apart and few enough digits to skim. Milliseconds
 * are only ever shown below a second, where the decimal would read as noise.
 */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`

  const minutes = Math.floor(ms / 60_000)
  const seconds = Math.round((ms % 60_000) / 1000)
  // 59.6 s rounds to 60, which should read as the next minute, not "1m 60s".
  return seconds === 60 ? `${minutes + 1}m 00s` : `${minutes}m ${String(seconds).padStart(2, '0')}s`
}

/** A stable-enough id for locally created messages. */
export function makeId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}
