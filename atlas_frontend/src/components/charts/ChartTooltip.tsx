/**
 * The hover readout.
 *
 * Rows are sorted by value, largest first, so the series under the cursor is
 * near the top rather than wherever the legend happened to put it. Each row
 * carries its own colour swatch AND its name — identity is never colour
 * alone, which is also what lets the light-mode palette ship as validated.
 */

import type { TooltipContentProps } from 'recharts'

import { formatInstant, formatValue } from '@/lib/chartData'

/**
 * Recharts supplies `active`, `payload` and `label` by cloning this element,
 * so they are optional from our side — only `labels` and `unit` are ours to
 * pass.
 */
type ChartTooltipProps = Partial<TooltipContentProps<number, string>> & {
  /** Series key -> readable name. */
  labels: Map<string, string>
  unit: string
}

export function ChartTooltip({ active, payload, label, labels, unit }: ChartTooltipProps) {
  if (!active || !payload || payload.length === 0) return null

  const rows = payload
    .filter((entry) => entry.value !== null && entry.value !== undefined)
    .sort((a, b) => Number(b.value ?? 0) - Number(a.value ?? 0))

  if (rows.length === 0) return null

  return (
    <div className="tooltip">
      <div className="tooltip__time">
        {typeof label === 'number' ? formatInstant(label) : String(label ?? '')}
      </div>
      <ul className="tooltip__rows">
        {rows.map((entry) => (
          <li key={String(entry.dataKey)} className="tooltip__row">
            <span
              className="tooltip__swatch"
              style={{ background: entry.color }}
              aria-hidden
            />
            <span className="tooltip__label">
              {labels.get(String(entry.dataKey)) ?? String(entry.dataKey)}
            </span>
            <span className="tooltip__value">
              {formatValue(Number(entry.value))}
              {unit}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
