/**
 * One resource against one window: today, this cycle, or the whole mission.
 *
 * The card is built to the same skeleton as the chart cards next door — fixed
 * head, body that takes what is left, footnote pinned to the foot — so three
 * of them in a row line up along their tops and their bottoms whatever their
 * notes happen to say.
 *
 * Order of reading, top to bottom: which window this is, the ring and its
 * verdict, the headline sentence, then the four figures the sentence was built
 * from. A reader who stops after the ring has the answer; one who reads to the
 * bottom can check it.
 *
 * "Plan expected" is the figure that makes the rest legible, so it sits in the
 * four rather than in a tooltip. Used against allowance is a fraction; used
 * against what was due by now is a verdict.
 */

import { NoSignal, Warning } from '@/icons'
import { amount, headline, paceReading, STATUS_TONE } from '@/lib/mission'
import type { Budget } from '@/lib/types'

import { BudgetRing } from './BudgetRing'

interface BudgetCardProps {
  budget: Budget
  unit: string
  /** True where the ceiling behind it is one we shipped, not one they set. */
  isDefault: boolean
}

export function BudgetCard({ budget, unit, isDefault }: BudgetCardProps) {
  const pace = paceReading(budget, unit)
  const covers =
    budget.first_code && budget.first_code !== budget.last_code
      ? `${budget.first_code}–${budget.last_code}`
      : budget.first_code

  return (
    <section className="card budget">
      <header className="card__head budget__head">
        <div className="card__heading">
          <h3 className="card__title" title={`${budget.days} day(s)`}>
            {budget.label}
          </h3>
          {covers && <span className="card__unit">{covers}</span>}
        </div>
      </header>

      {budget.status === 'no_data' ? (
        <div className="card__state">
          <NoSignal size={20} />
          <p className="card__state-title">No readings in this window</p>
          <p className="card__state-text">{budget.note}</p>
        </div>
      ) : (
        <div className="budget__body">
          <BudgetRing budget={budget} unit={unit} />

          <p className="budget__headline">{headline(budget, unit)}</p>
          {pace && <p className="budget__pace">{pace}</p>}

          <dl className="budget__figures">
            <Figure label="Used" value={amount(budget.used, unit)} />
            <Figure
              label="Plan expected"
              value={amount(budget.planned_by_now, unit)}
              title={
                'What the plan itself expected to have been drawn by this ' +
                'moment: finished days in full, today at the share of it ' +
                'that has passed, and each extra on its own day rather than ' +
                'smeared across the window.'
              }
            />
            <Figure label="Allowed" value={amount(budget.target, unit)} />
            <Figure
              label="Left"
              value={amount(budget.remaining, unit)}
              overspent={budget.remaining !== null && budget.remaining < 0}
            />
          </dl>
        </div>
      )}

      {(budget.note || isDefault) && (
        <footer className="budget__foot">
          {isDefault && (
            <p className="budget__flag">
              <Warning size={12} />
              Measured against a shipped default, not a ceiling the crew set.
            </p>
          )}
          {budget.note && budget.status !== 'no_data' && (
            <p className="budget__note">{budget.note}</p>
          )}
        </footer>
      )}
    </section>
  )
}

interface FigureProps {
  label: string
  value: string
  /** Draws the figure in the fault colour — only ever used on a negative left. */
  overspent?: boolean
  title?: string
}

function Figure({ label, value, overspent, title }: FigureProps) {
  return (
    <div className="budget__figure-item" title={title}>
      <dt className="readout__key">{label}</dt>
      <dd className={overspent ? 'readout__value readout__value--bad' : 'readout__value'}>
        {value}
      </dd>
    </div>
  )
}

export { STATUS_TONE }
