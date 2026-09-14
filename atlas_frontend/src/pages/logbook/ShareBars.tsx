/**
 * Every meter in a window, ranked.
 *
 * The chart for eleven taps. A ring with eleven slices needs eleven hues the
 * palette does not have and separates none of them at the sizes the small ones
 * land at; bars sorted by size answer "which tap is the problem" at a glance
 * and "by how much" without a legend.
 *
 * The bars are drawn against the LARGEST bar rather than against the window
 * total, so the smallest ones are still visible. That would be a lie if the
 * bars were the figure — so they are not: every row carries its litres and its
 * share of the window in text, and the bar is only the ordering made visible.
 *
 * A meter with nothing logged keeps its row, greyed. Dropping it would read as
 * "there is no meter there", which is a different and wrong claim.
 */

import { amount } from '@/lib/mission'
import { share } from '@/lib/logbook'
import type { Share } from '@/lib/types'

interface ShareBarsProps {
  rows: Share[]
  unit: string
  /** Colour per row key, where the category means something. Grey otherwise. */
  colours?: Record<string, string>
}

export function ShareBars({ rows, unit, colours }: ShareBarsProps) {
  const largest = rows.reduce((most, row) => Math.max(most, row.amount), 0)

  return (
    <ul className="log-bars">
      {rows.map((row) => {
        const width = largest > 0 ? (row.amount / largest) * 100 : 0
        return (
          <li
            key={row.key}
            className={row.logged ? 'log-bars__row' : 'log-bars__row log-bars__row--absent'}
          >
            <span className="log-bars__label">
              {row.label}
              {row.code && <span className="log-bars__code">{row.code}</span>}
            </span>

            <span className="log-bars__track">
              <span
                className="log-bars__fill"
                style={{
                  width: `${width}%`,
                  background: colours?.[row.key] ?? 'var(--series-1)',
                }}
              />
            </span>

            <span className="log-bars__amount">{amount(row.amount, unit)}</span>
            <span className="log-bars__share">
              {row.logged ? (
                share(row.share)
              ) : (
                <span
                  className="log-bars__absent-mark"
                  title="Nothing logged for this meter in this window. Not a meter that read zero."
                >
                  not logged
                </span>
              )}
            </span>
          </li>
        )
      })}
    </ul>
  )
}
