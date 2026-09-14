/**
 * Where a window's consumption went, as a part-to-whole.
 *
 * A ring rather than a pie, because the middle is where the total goes and the
 * total is the thing the slices are shares OF — a reader who takes only the
 * centre figure has lost nothing.
 *
 * Every slice is also written out beside it, with its amount and its share. A
 * ring is good at "one of these is much bigger than the others" and bad at
 * "how much bigger", and the list is what answers the second question — and
 * what a reader who cannot separate two hues reads instead.
 *
 * NEVER MORE THAN EIGHT SLICES. The palette is eight validated hues and no
 * ninth is ever generated; see `lib/logbook.ts`. The eleven taps are ranked as
 * bars instead, which is also simply the better chart for eleven of anything.
 */

import { Cell, Pie, PieChart, ResponsiveContainer } from 'recharts'

import { amount } from '@/lib/mission'
import { share, sliceColour } from '@/lib/logbook'
import type { Share } from '@/lib/types'

interface ShareDonutProps {
  slices: Share[]
  unit: string
  /** The figure in the middle: what every slice is a share of. */
  total: number | null
  /** Fixed colours where the categories mean something — warm, cold. */
  colours?: Record<string, string>
}

/*
 * THE HOLE HOLDS THE TOTAL AND ITS UNIT, AND NOTHING ELSE. It used to carry a
 * third line naming the window — "MD-07–MD-09" — which is a string of unknown
 * length placed in a circle of fixed width, and it spilled over the ring on
 * every window whose label was longer than a day code. The card's own heading
 * already says which days it covers, and says it in a box that can hold it.
 */
export function ShareDonut({ slices, unit, total, colours }: ShareDonutProps) {
  const drawn = slices.filter((slice) => slice.amount > 0)

  if (drawn.length === 0 || total === null || total <= 0) {
    return (
      <p className="log-donut__empty">
        Nothing measured in this window yet.
      </p>
    )
  }

  const colourOf = (slice: Share, index: number) =>
    colours?.[slice.key] ?? sliceColour(index)

  return (
    <div className="log-donut">
      <div className="log-donut__plot">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={drawn}
              dataKey="amount"
              nameKey="label"
              // A narrow band. The ring is a shape, not a surface to be read
              // off — the figures are all in the list beside it — and a thin
              // one leaves the total room to be the largest thing in the card.
              innerRadius="70%"
              outerRadius="92%"
              startAngle={90}
              endAngle={-270}
              paddingAngle={1}
              // The plot is decoration for the list beside it, which carries
              // every figure in text. Animating it would only delay that.
              isAnimationActive={false}
              stroke="var(--bg-panel)"
              strokeWidth={2}
            >
              {drawn.map((slice, index) => (
                <Cell key={slice.key} fill={colourOf(slice, index)} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>

        <div className="log-donut__centre">
          <span className="log-donut__total">{amount(total, '')}</span>
          <span className="log-donut__unit">{unit}</span>
        </div>
      </div>

      <ul className="log-shares">
        {drawn.map((slice, index) => (
          <li
            key={slice.key}
            className="log-shares__item"
            // Set on the day/night split: the span of hours the slice covers,
            // which is the whole answer to "when is this one calculated".
            title={slice.covers || undefined}
          >
            <span
              className="log-shares__swatch"
              style={{ background: colourOf(slice, index) }}
              aria-hidden
            />
            <span className="log-shares__label">
              {slice.label}
              {slice.code && <span className="log-shares__code">{slice.code}</span>}
            </span>
            <span className="log-shares__share">{share(slice.share)}</span>
            <span className="log-shares__amount">{amount(slice.amount, unit)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
