/**
 * The whole mission, day by day: what was allowed, what was drawn, what is
 * allowed from here.
 *
 * The three ring cards say where the crew stands right now. This says whether
 * that is normal, and — the part no single window can show — what the plan has
 * had to become. Overspend in week one is a lower line for every day after it,
 * and that consequence is the shape this chart exists to draw.
 *
 * Three series, one axis, one unit. Not a dual-axis chart: litres against
 * litres, or kWh against kWh, and nothing here is ever indexed or rescaled.
 *
 *   bars    what the meters recorded. The measurement.
 *   line    the original allowance, laid down when the mission was declared.
 *   dashed  what the forward plan now allows, from today on. Absent behind us,
 *           because a day already lived cannot be re-planned.
 *
 * Bars that cleared their day's allowance are drawn in the fault colour. That
 * is the chart borrowing the status palette rather than the categorical one,
 * and it is deliberate: on this chart "which days went over" IS the data. The
 * legend and the tooltip both say so in words, so the colour never carries it
 * alone.
 *
 * Today's bar is drawn hollow. A day four hours old is not a low day, and a
 * part-day bar next to whole ones is the most natural misreading available.
 */

import { useMemo } from 'react'
import {
  Bar,
  Cell,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { formatValue } from '@/lib/chartData'
import { amount, DAY_LABEL } from '@/lib/mission'
import { CHART_INK } from '@/lib/palette'
import type { PlannedDay } from '@/lib/types'

const PLOT_MARGIN = { top: 8, right: 20, bottom: 0, left: 0 }

const AXIS_TICK = {
  fill: CHART_INK.label,
  fontSize: 10,
  fontFamily: 'var(--font-mono)',
  letterSpacing: '0.04em',
}

interface Row extends PlannedDay {
  over: boolean
}

interface DayPlanChartProps {
  days: PlannedDay[]
  unit: string
}

export function DayPlanChart({ days, unit }: DayPlanChartProps) {
  const rows = useMemo<Row[]>(
    () =>
      days.map((day) => ({
        ...day,
        over: day.actual !== null && day.actual > day.planned,
      })),
    [days],
  )

  const todayAt = rows.find((row) => row.state === 'today')?.code

  return (
    <div className="panel-chart">
      <div className="panel-chart__plot">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={PLOT_MARGIN}>
            <CartesianGrid stroke={CHART_INK.grid} vertical={false} />
            <XAxis
              dataKey="code"
              tick={AXIS_TICK}
              stroke={CHART_INK.axis}
              tickLine={false}
              minTickGap={18}
            />
            {/* Bar length encodes an amount, so the axis starts at zero. */}
            <YAxis
              tick={AXIS_TICK}
              stroke={CHART_INK.axis}
              tickLine={false}
              axisLine={false}
              width={52}
              domain={[0, 'auto']}
              tickFormatter={(value: number) => formatValue(value)}
            />
            <Tooltip
              content={<DayTooltip unit={unit} />}
              cursor={{ fill: CHART_INK.grid }}
              isAnimationActive={false}
            />

            {todayAt && (
              <ReferenceLine
                x={todayAt}
                stroke={CHART_INK.cursor}
                strokeDasharray="3 3"
                label={{
                  value: 'today',
                  position: 'insideTopLeft',
                  fill: CHART_INK.label,
                  fontSize: 10,
                  fontFamily: 'var(--font-mono)',
                }}
              />
            )}

            <Bar dataKey="actual" isAnimationActive={false}>
              {rows.map((row) => (
                <Cell
                  key={row.code}
                  fill={row.over ? 'var(--danger)' : 'var(--series-1)'}
                  fillOpacity={row.state === 'today' ? 0.35 : 1}
                  stroke={row.state === 'today' ? 'var(--series-1)' : undefined}
                  strokeDasharray={row.state === 'today' ? '3 2' : undefined}
                />
              ))}
            </Bar>

            <Line
              type="stepAfter"
              dataKey="planned"
              stroke={CHART_INK.cursor}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="stepAfter"
              dataKey="revised"
              stroke="var(--series-3)"
              strokeWidth={2}
              strokeDasharray="6 3"
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Always present, because there are three series. Two of them are lines
          of the same weight and could not be told apart otherwise. */}
      <ul className="legend day-legend">
        <Key className="day-legend__bar">Drawn</Key>
        <Key className="day-legend__bar day-legend__bar--over">Drawn, over the day</Key>
        <Key className="day-legend__line">Planned at the start</Key>
        <Key className="day-legend__line day-legend__line--revised">
          Allowed from here
        </Key>
      </ul>
    </div>
  )
}

function Key({ className, children }: { className: string; children: React.ReactNode }) {
  return (
    <li className="legend__item legend__item--static">
      <span className={`day-legend__key ${className}`} aria-hidden="true" />
      <span>{children}</span>
    </li>
  )
}

interface TooltipProps {
  active?: boolean
  payload?: { payload: Row }[]
  unit: string
}

function DayTooltip({ active, payload, unit }: TooltipProps) {
  if (!active || !payload?.length) return null
  const row = payload[0]!.payload

  return (
    <div className="tooltip">
      <div className="tooltip__time">
        {row.code} · {row.date}
        {row.state === 'today' ? ' · still running' : ''}
      </div>
      <ul className="tooltip__rows">
        <Line2 label="Drawn" value={amount(row.actual, unit)} />
        <Line2 label="Planned" value={amount(row.planned, unit)} />
        {row.revised !== null && (
          <Line2 label="Allowed from here" value={amount(row.revised, unit)} />
        )}
        {row.extras > 0 && (
          <Line2 label="Of which extras" value={amount(row.extras, unit)} />
        )}
        <Line2 label="Verdict" value={DAY_LABEL[row.status]} />
      </ul>
      {row.extra_labels.length > 0 && (
        <p className="tooltip__note">{row.extra_labels.join(', ')}</p>
      )}
    </div>
  )
}

function Line2({ label, value }: { label: string; value: string }) {
  return (
    <li className="tooltip__row">
      <span className="tooltip__label">{label}</span>
      <span className="tooltip__value">{value}</span>
    </li>
  )
}
