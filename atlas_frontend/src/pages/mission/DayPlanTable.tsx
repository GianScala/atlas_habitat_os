/**
 * The mission day by day, as a table.
 *
 * The chart above shows the shape; this is where a number is read off. Both
 * are drawn from the same array, so a bar and a row can never disagree — and
 * the table is also the accessible view of the chart, which is why it is
 * always present rather than hidden behind a toggle.
 *
 * Four columns and a verdict. `Planned` is what the day was allowed when the
 * mission was declared; `Allowed now` is what the forward plan gives it after
 * re-spreading whatever is left; `Drawn` is the meter. A day already behind us
 * has no `Allowed now`, because a day already lived cannot be re-planned, and
 * the cell says so with an em dash rather than repeating `Planned`.
 *
 * Long missions are cut down to the days worth reading — a window around today,
 * plus every day carrying an extra, since those are the ones that explain why
 * their neighbours are lower. The full run is one press away.
 */

import { useMemo, useState } from 'react'

import { amount, DAY_LABEL, DAY_TONE } from '@/lib/mission'
import type { PlannedDay } from '@/lib/types'

/** Days either side of today shown before the table asks to be expanded. */
const AROUND = 7

interface DayPlanTableProps {
  days: PlannedDay[]
  unit: string
}

export function DayPlanTable({ days, unit }: DayPlanTableProps) {
  const [all, setAll] = useState(false)

  const shown = useMemo(() => {
    if (all || days.length <= AROUND * 2 + 1) return days

    const todayAt = days.findIndex((day) => day.state === 'today')
    const centre = todayAt === -1 ? 0 : todayAt
    const keep = new Set<number>()
    for (let i = centre - AROUND; i <= centre + AROUND; i += 1) {
      if (i >= 0 && i < days.length) keep.add(i)
    }
    days.forEach((day, index) => {
      if (day.extras > 0) keep.add(index)
    })
    return [...keep].sort((a, b) => a - b).map((index) => days[index]!)
  }, [all, days])

  const hidden = days.length - shown.length

  return (
    <div className="dayplan">
      <div className="dayplan__scroll">
        <table className="dayplan__table">
          <caption className="dayplan__caption">
            Every mission day: what it was allowed, what it took, and what it is
            allowed now.
          </caption>
          <thead>
            <tr>
              <th scope="col">Day</th>
              <th scope="col">Date</th>
              <th scope="col" className="dayplan__num">
                Planned
              </th>
              <th scope="col" className="dayplan__num">
                Allowed now
              </th>
              <th scope="col" className="dayplan__num">
                Drawn
              </th>
              <th scope="col">Extras</th>
              <th scope="col">Verdict</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((day) => (
              <tr
                key={day.code}
                className={`dayplan__row dayplan__row--${day.state}`}
                aria-current={day.state === 'today' ? 'date' : undefined}
              >
                <th scope="row" className="dayplan__code">
                  {day.code}
                </th>
                <td className="dayplan__date">{day.date}</td>
                <td className="dayplan__num">{amount(day.planned, unit)}</td>
                <td className="dayplan__num dayplan__num--revised">
                  {day.revised === null ? '' : amount(day.revised, unit)}
                </td>
                <td
                  className="dayplan__num"
                  title={
                    day.actual !== null
                      ? undefined
                      : day.queried
                        ? 'The sensors did not cover this day. It is not a day of none.'
                        : 'Older than the window the meters were asked about.'
                  }
                >
                  {day.actual === null ? (
                    <span className="dayplan__absent" />
                  ) : (
                    amount(day.actual, unit)
                  )}
                </td>
                <td className="dayplan__extras">
                  {day.extras > 0 ? (
                    <span title={day.extra_labels.join(', ')}>
                      {amount(day.extras, unit)}
                    </span>
                  ) : (
                    ''
                  )}
                </td>
                <td>
                  <span className={`chip chip--${DAY_TONE[day.status]}`}>
                    {DAY_LABEL[day.status]}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {hidden > 0 && !all && (
        <button type="button" className="link-button" onClick={() => setAll(true)}>
          Show the other {hidden} days
        </button>
      )}
      {all && days.length > AROUND * 2 + 1 && (
        <button type="button" className="link-button" onClick={() => setAll(false)}>
          Show only the days around today
        </button>
      )}
    </div>
  )
}
