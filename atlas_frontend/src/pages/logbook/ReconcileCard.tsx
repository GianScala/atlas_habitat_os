/**
 * The crew's account against the habitat's, day by day.
 *
 * This is what the log is FOR. Everything above it says where the habitat's
 * consumption went; this says whether the account it says it from can be
 * believed at all — by holding it against a completely independent measurement
 * of the same days, taken by instruments that report to the habitat database
 * without a human in the loop.
 *
 * MATCHED ON THE MISSION DAY, never total against total. A crew log covering
 * MD-01 to MD-04 compared with a habitat meter covering the whole mission so
 * far would show an enormous shortfall that is nothing whatever but the
 * difference between the two windows — the most convincing wrong number this
 * page could produce. Only days both accounts closed are compared, and the
 * card says how many that was.
 *
 * The expected result is that the sub-meters come in slightly UNDER the
 * whole-habitat meter: there are loads on the mains that no room owns. Over is
 * the interesting direction, because the parts cannot exceed the whole.
 */

import { Warning } from '@/icons'
import { amount } from '@/lib/mission'
import { reconciliationReading, share, type Reconciliation } from '@/lib/logbook'
import type { LogResource } from '@/lib/types'

interface ReconcileCardProps {
  check: Reconciliation
  resource: LogResource
  /** What the habitat's own meter is called on the mission page. */
  meterLabel: string
}

export function ReconcileCard({ check, resource, meterLabel }: ReconcileCardProps) {
  if (check.mismatch) {
    return (
      <section className="card log-check">
        <header className="card__head">
          <div className="card__heading">
            <h3 className="card__title">Against the habitat meter</h3>
          </div>
        </header>
        <p className="log-check__warn">
          <Warning size={13} />
          {check.mismatch}
        </p>
      </section>
    )
  }

  const under = check.difference < 0
  const tone = Math.abs(check.fraction ?? 0) < 0.05 ? 'ok' : under ? 'warn' : 'bad'

  return (
    <section className="card log-check">
      <header className="card__head">
        <div className="card__heading">
          <h3 className="card__title">Against the habitat meter</h3>
          <span className="card__unit">
            {check.days.length} day{check.days.length === 1 ? '' : 's'} both measured
          </span>
        </div>
        <p className="card__subtitle">
          The crew's sub-meters against {meterLabel.toLowerCase()} in the
          database, over the mission days both accounts closed. Two independent
          measurements of the same habitat — which is the only reason putting
          them side by side proves anything.
        </p>
      </header>

      <div className="log-check__figures">
        <Figure label="Crew log" value={amount(check.logged, resource.unit)} />
        <Figure label="Habitat meter" value={amount(check.measured, resource.unit)} />
        <Figure
          label="Difference"
          value={`${check.difference >= 0 ? '+' : '−'}${amount(
            Math.abs(check.difference),
            resource.unit,
          )}`}
          tone={tone}
        />
        <Figure
          label="Of the meter"
          value={
            check.fraction === null
              ? ''
              : `${check.difference >= 0 ? '+' : '−'}${share(Math.abs(check.fraction))}`
          }
          tone={tone}
        />
      </div>

      <p className={`log-check__reading log-check__reading--${tone}`}>
        {reconciliationReading(check, resource.unit, resource.key)}
      </p>

      <details className="panel">
        <summary className="panel__summary">
          <span className="panel__label">Day by day</span>
          <span className="panel__hint">
            the two accounts for each day they both cover.
          </span>
        </summary>
        <div className="panel__body">
          <div className="dayplan__scroll">
            <table className="dayplan__table">
              <thead>
                <tr>
                  <th scope="col">Day</th>
                  <th scope="col" className="dayplan__num">
                    Crew log
                  </th>
                  <th scope="col" className="dayplan__num">
                    Habitat meter
                  </th>
                  <th scope="col" className="dayplan__num">
                    Difference
                  </th>
                </tr>
              </thead>
              <tbody>
                {check.days.map((day) => {
                  const gap = day.logged - day.measured
                  return (
                    <tr key={day.code} className="dayplan__row">
                      <th scope="row" className="dayplan__code">
                        {day.code}
                      </th>
                      <td className="dayplan__num">
                        {amount(day.logged, resource.unit)}
                      </td>
                      <td className="dayplan__num">
                        {amount(day.measured, resource.unit)}
                      </td>
                      <td className="dayplan__num">
                        {gap >= 0 ? '+' : '−'}
                        {amount(Math.abs(gap), resource.unit)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </details>
    </section>
  )
}

function Figure({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone?: string
}) {
  return (
    <div className="log-check__figure">
      <span className="log-check__figure-label">{label}</span>
      <span
        className={
          tone ? `log-check__figure-value log-check__figure-value--${tone}` : 'log-check__figure-value'
        }
      >
        {value}
      </span>
    </div>
  )
}
