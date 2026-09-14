/**
 * Reshaping panel data for the chart library.
 *
 * The API returns one list of points per series, which is the honest shape —
 * series do not share a sampling clock, and a room whose sensor was offline
 * for an hour simply has no points there. Recharts wants the transpose: one
 * row per timestamp with a column per series.
 *
 * The transpose must not invent readings. A series with no point at a given
 * timestamp gets `null`, not zero and not the previous value — a gap in a
 * line is the truthful rendering of a sensor that said nothing.
 */

import type { Panel, PanelSeries } from './types'

export interface ChartRow {
  /** Milliseconds since epoch — recharts sorts and scales numerically. */
  t: number
  [seriesKey: string]: number | null
}

export function toChartRows(series: PanelSeries[]): ChartRow[] {
  const byTime = new Map<number, ChartRow>()

  for (const entry of series) {
    for (const point of entry.points) {
      const at = Date.parse(point.t)
      if (Number.isNaN(at)) continue

      let row = byTime.get(at)
      if (!row) {
        row = { t: at }
        byTime.set(at, row)
      }
      row[entry.key] = point.v
    }
  }

  const rows = [...byTime.values()].sort((a, b) => a.t - b.t)

  // Fill absent series with null so the library draws a gap rather than
  // connecting across a period where a sensor reported nothing.
  for (const row of rows) {
    for (const entry of series) {
      if (!(entry.key in row)) row[entry.key] = null
    }
  }

  return rows
}

/** Tick format that suits the window — clock for hours, date for weeks. */
export function makeTickFormatter(windowMinutes: number): (value: number) => string {
  const showDateOnly = windowMinutes >= 60 * 24 * 3
  const showDate = windowMinutes > 60 * 24

  return (value: number) => {
    const at = new Date(value)
    if (showDateOnly) {
      return at.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    }
    const time = at.toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
    })
    if (!showDate) return time
    return `${at.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })} ${time}`
  }
}

/** Full timestamp for a tooltip header, where there is room for it. */
export function formatInstant(value: number): string {
  return new Date(value).toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * A number for display: enough precision to be useful, not so much that a
 * column of them stops lining up.
 */
export function formatValue(value: number): string {
  const size = Math.abs(value)
  if (size >= 1000) return value.toLocaleString(undefined, { maximumFractionDigits: 0 })
  if (size >= 10) return value.toFixed(1)
  if (size >= 1) return value.toFixed(2)
  if (size === 0) return '0'
  return value.toFixed(3)
}

/** The unit to print after a figure, or an empty string when none is known. */
export function unitSuffix(panel: Panel): string {
  return panel.unit_source === 'known' && panel.unit ? ` ${panel.unit}` : ''
}

/**
 * True when a panel has nothing to draw.
 *
 * Counting points is not enough: a series can arrive carrying points whose
 * values are all null, which plots as an empty pair of axes — indistinguishable
 * from a broken chart, and a worse lie than saying plainly that nothing came
 * back.
 */
export function isEmpty(panel: Panel): boolean {
  return panel.series.every((entry) =>
    entry.points.every((point) => !Number.isFinite(point.v)),
  )
}

/**
 * True when every reading in the window is exactly zero.
 *
 * Zero is a reading, not an absence, and the chart must still be drawn — but a
 * flat row of nothing looks the same as a dead sensor, so the panel says which
 * of the two it is looking at rather than leaving the reader to guess.
 */
export function isAllZero(panel: Panel): boolean {
  let seen = false

  for (const entry of panel.series) {
    for (const point of entry.points) {
      if (!Number.isFinite(point.v)) continue
      if (point.v !== 0) return false
      seen = true
    }
  }

  return seen
}
