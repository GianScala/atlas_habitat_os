/**
 * One window of the analysis: a total, and where it went.
 *
 * Three of these sit in a row — the latest logged day, the last three, the
 * whole mission — and they are the same question asked at three ranges,
 * because that is the only way to tell a bad day from a trend. A room that is
 * 40% of today and 12% of the mission had an unusual afternoon; one that is
 * 40% of both is how this habitat works.
 *
 * The total is the hero and it sits in the middle of the ring, because every
 * slice is a share of it. Under it, always, is what the figure is worth: a
 * window with a block still open can only go up, and says so before it is
 * read rather than in a footnote after.
 */

import { Warning } from '@/icons'
import { amount } from '@/lib/mission'
import { topDraw, windowCaveat } from '@/lib/logbook'
import type { LogResource, LogWindow } from '@/lib/types'

import { ShareDonut } from './ShareDonut'

interface WindowCardProps {
  window: LogWindow
  resource: LogResource
  /** Fixed colours where the slices mean something rather than merely differ. */
  colours?: Record<string, string>
  /** Which split the ring draws: the meters themselves, or what they serve. */
  slices: 'meters' | 'groups'
}

export function WindowCard({ window, resource, colours, slices }: WindowCardProps) {
  const caveat = windowCaveat(window, resource)
  const leader = topDraw(window)
  const span =
    window.first_code === null
      ? 'nothing logged'
      : window.first_code === window.last_code
        ? window.first_code
        : `${window.first_code}–${window.last_code}`

  return (
    <section className="card log-window">
      <header className="card__head">
        <div className="card__heading">
          <h3 className="card__title">{window.label}</h3>
          <span className="card__unit">{span}</span>
        </div>
        <p className="card__subtitle">
          {window.days_covered > 0 ? (
            <>
              {window.days_covered} day{window.days_covered === 1 ? '' : 's'}{' '}
              measured
              {window.per_day_mean !== null && (
                <> · {amount(window.per_day_mean, resource.unit)} a day on average</>
              )}
            </>
          ) : (
            'No day in this window has both of its readings yet.'
          )}
        </p>
      </header>

      <ShareDonut
        slices={slices === 'groups' ? window.groups : window.meters}
        unit={resource.unit}
        total={window.total}
        colours={colours}
      />

      {leader && <p className="log-window__lead">{leader}</p>}

      {caveat && (
        <p className="log-window__caveat">
          <Warning size={12} />
          {caveat}
        </p>
      )}
    </section>
  )
}
