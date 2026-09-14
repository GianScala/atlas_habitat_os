/**
 * One window's consumption against its allowance, drawn as a ring.
 *
 * The form is a part-to-whole with ONE part and a hero number in the middle,
 * which is what a ring is actually good for — "23% of the plan is gone" read
 * without touching an axis. It is not a pie: there are no slices to compare,
 * and nothing here is ever split into categories.
 *
 * TWO MARKS ON ONE TRACK, and everything this card exists to say is the
 * relationship between them:
 *
 *   the arc   how much of the allowance is gone.
 *   the tick  what the PLAN expected to be gone by now.
 *
 * The tick is not the elapsed share of the window. It is the day plan summed
 * to this moment — finished days in full, today at the share of it that has
 * passed, extras on their own days. A 200-litre experiment booked for the last
 * day of a cycle is not two-thirds spent on the second day, and a tick that
 * said it was would report a crew comfortably ahead right up until it wasn't.
 *
 * Colour is the status palette, never the categorical one, and it never
 * carries the meaning alone — the verdict is written on a chip beside it and
 * the arc is labelled. On this card "are we over" IS the data, which is the one
 * case where a chart is allowed to borrow the instrument colours.
 *
 * An arc past 100% is clamped and the ring gains a second, offset stroke, so
 * "spent twice over" cannot look identical to "spent exactly once".
 */

import { amount, meterGeometry, percent, STATUS_LABEL, STATUS_TONE } from '@/lib/mission'
import type { Budget } from '@/lib/types'

const SIZE = 148
const STROKE = 14
const RADIUS = (SIZE - STROKE) / 2 - 6
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

interface BudgetRingProps {
  budget: Budget
  unit: string
}

export function BudgetRing({ budget, unit }: BudgetRingProps) {
  const tone = STATUS_TONE[budget.status]
  const { fill, pace } = meterGeometry(budget)
  const spent = budget.used_fraction
  const overspent = spent !== null && spent > 1

  // Degrees, from 12 o'clock, clockwise — the direction a gauge is read in.
  const tickAngle = pace * 360 - 90

  const readout =
    spent === null
      ? amount(budget.used, unit)
      : `${Math.round(spent * 100)}%`

  return (
    <div className="ring">
      <svg
        className="ring__svg"
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        role="img"
        aria-label={
          spent === null
            ? `${budget.label}: ${amount(budget.used, unit)} used, no ceiling set`
            : `${budget.label}: ${percent(spent)} of the allowance used, ` +
              `against the ${percent(pace)} the plan expected by now`
        }
      >
        <g transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}>
          {/* The track: the whole allowance, recessive. */}
          <circle
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            fill="none"
            stroke="var(--chart-grid)"
            strokeWidth={STROKE}
          />

          {spent !== null && (
            <circle
              className={`ring__arc ring__arc--${tone}`}
              cx={SIZE / 2}
              cy={SIZE / 2}
              r={RADIUS}
              fill="none"
              strokeWidth={STROKE}
              strokeLinecap="round"
              strokeDasharray={`${fill * CIRCUMFERENCE} ${CIRCUMFERENCE}`}
            />
          )}

          {/* A second lap, inset, for an allowance spent more than once. Drawn
              rather than left to the clamp, so 180% cannot read as 100%. */}
          {overspent && (
            <circle
              className={`ring__arc ring__arc--${tone}`}
              cx={SIZE / 2}
              cy={SIZE / 2}
              r={RADIUS - STROKE}
              fill="none"
              strokeWidth={3}
              strokeDasharray={`${Math.min(1, spent - 1) * 2 * Math.PI * (RADIUS - STROKE)} ${
                2 * Math.PI * (RADIUS - STROKE)
              }`}
            />
          )}
        </g>

        {/* Where the plan expected to be by now. Drawn over the arc, because
            the question is which side of it the arc ends on. */}
        {budget.target !== null && (
          <line
            className="ring__tick"
            x1={SIZE / 2 + Math.cos((tickAngle * Math.PI) / 180) * (RADIUS - STROKE / 2 - 2)}
            y1={SIZE / 2 + Math.sin((tickAngle * Math.PI) / 180) * (RADIUS - STROKE / 2 - 2)}
            x2={SIZE / 2 + Math.cos((tickAngle * Math.PI) / 180) * (RADIUS + STROKE / 2 + 2)}
            y2={SIZE / 2 + Math.sin((tickAngle * Math.PI) / 180) * (RADIUS + STROKE / 2 + 2)}
          >
            <title>
              The plan expected {amount(budget.planned_by_now, unit)} by now
            </title>
          </line>
        )}
      </svg>

      <div className="ring__centre">
        <span className={`ring__figure ring__figure--${tone}`}>{readout}</span>
        <span className="ring__caption">
          {spent === null ? 'used' : 'of plan'}
        </span>
      </div>

      {/* Identity is never colour alone: the verdict is written out. */}
      <span className={`chip chip--${tone} ring__chip`}>
        {STATUS_LABEL[budget.status]}
      </span>
    </div>
  )
}
