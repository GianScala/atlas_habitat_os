/**
 * The whole mission, day by day, from the crew's own readings.
 *
 * The window cards say where the habitat's consumption goes. This says whether
 * that is normal for it — a Sunday laundry day, a dormitory left warm, the
 * afternoon the biology run drew half the day's power all at once.
 *
 * Stacked, because a bar that is only a total answers half the question. Both
 * resources are read on two rounds, so both stack DAYTIME against OVERNIGHT by
 * default: the stack IS the day, and a habitat that draws after dark looks
 * different from one that draws at noon without anybody reading a figure.
 *
 * The bands are named for the CONSUMPTION, not for the round that opened it —
 * "Daytime", not "Morning round". The two were one string once, and a bar
 * labelled with the round read as the reading taken at that moment rather than
 * as everything drawn between that round and the next one.
 *
 * Water can also be stacked warm against cold, and gets a control to switch —
 * warm water is water AND the power that heated it, so a day where the warm
 * half grows is a finding about two resources at once. Power has no second
 * split to offer, so it gets no control: a switch with one position is a
 * switch that should not be there.
 *
 * The bars are re-grouped from the blocks the backend already derived — every
 * figure here is one of its numbers, added up a different way. Nothing on this
 * page recomputes a consumption from a reading; there is exactly one place
 * that subtraction happens, and it is not the browser.
 *
 * A day still waiting on its closing reading is drawn hollow. A day four hours
 * from being measurable is not a quiet day, and a short bar beside whole ones
 * is the most natural misreading available.
 */

import { useMemo, useState } from 'react'
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { formatValue } from '@/lib/chartData'
import { SLOT_COLOUR, STREAM_COLOUR } from '@/lib/logbook'
import { amount } from '@/lib/mission'
import { CHART_INK } from '@/lib/palette'
import type { LogResource } from '@/lib/types'

const PLOT_MARGIN = { top: 8, right: 20, bottom: 0, left: 0 }

const AXIS_TICK = {
  fill: CHART_INK.label,
  fontSize: 10,
  fontFamily: 'var(--font-mono)',
  letterSpacing: '0.04em',
}

interface Band {
  key: string
  label: string
  colour: string
  /** The span this band covers, for the legend's tooltip. */
  covers?: string
}

interface Row {
  code: string
  state: string
  complete: boolean
  total: number | null
  /** One entry per band, by band key. */
  [band: string]: unknown
}

interface DailyChartProps {
  resource: LogResource
}

/** How a day's bar is cut up. Water offers both; power only the first. */
type Split = 'round' | 'temperature'

export function DailyChart({ resource }: DailyChartProps) {
  const [split, setSplit] = useState<Split>('round')
  const offersTemperature = resource.key === 'water'
  const active: Split = offersTemperature ? split : 'round'

  const bands = useMemo<Band[]>(() => {
    if (active === 'temperature') {
      return [
        { key: 'warm', label: 'Warm', colour: STREAM_COLOUR.warm! },
        { key: 'cold', label: 'Cold', colour: STREAM_COLOUR.cold! },
      ]
    }
    // The BLOCK name, not the round name. A band labelled "Morning round"
    // reads as the reading taken in the morning; what it actually plots is
    // everything drawn between that round and the next one.
    return resource.slots.map((slot) => ({
      key: slot.key,
      label: slot.block_label,
      covers: slot.covers,
      colour: SLOT_COLOUR[slot.key] ?? 'var(--series-1)',
    }))
  }, [resource, active])

  const rows = useMemo<Row[]>(() => {
    // Which band a block belongs to: the round it was read on, or the
    // temperature of the tap that drew it. One lookup, built once, rather
    // than a find per cell.
    const bandOf = new Map<string, string>()
    for (const meter of resource.meters) bandOf.set(meter.key, meter.stream)

    const totals = new Map<number, Record<string, number>>()
    for (const cell of resource.usage) {
      if (cell.amount === null) continue
      const band =
        active === 'temperature' ? (bandOf.get(cell.meter) ?? 'cold') : cell.slot
      const day = totals.get(cell.day_index) ?? {}
      day[band] = (day[band] ?? 0) + cell.amount
      totals.set(cell.day_index, day)
    }

    return resource.days.map((day) => ({
      code: day.code,
      state: day.state,
      complete: day.complete,
      total: day.total,
      ...(totals.get(day.index) ?? {}),
    }))
  }, [resource, active])

  const measured = rows.some((row) => row.total !== null)

  if (!measured) {
    return (
      <p className="log-empty">
        No day has both of its readings yet, so there is nothing to plot. The
        first bar appears when a block has been closed, for power that is the
        evening round of the first day logged.
      </p>
    )
  }

  return (
    <div className="panel-chart">
      {offersTemperature && (
        <div className="log-daily__split">
          <div className="views views--small" role="group" aria-label="How to split each day">
            <button
              type="button"
              className={active === 'round' ? 'view view--on' : 'view'}
              onClick={() => setSplit('round')}
              aria-pressed={active === 'round'}
            >
              Day / night
            </button>
            <button
              type="button"
              className={active === 'temperature' ? 'view view--on' : 'view'}
              onClick={() => setSplit('temperature')}
              aria-pressed={active === 'temperature'}
            >
              Warm / cold
            </button>
          </div>
        </div>
      )}

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
              width={56}
              domain={[0, 'auto']}
              tickFormatter={(value: number) => formatValue(value)}
            />
            <Tooltip
              content={<DayTooltip bands={bands} unit={resource.unit} />}
              cursor={{ fill: CHART_INK.grid }}
              isAnimationActive={false}
            />

            {bands.map((band) => (
              <Bar
                key={band.key}
                dataKey={band.key}
                stackId="day"
                isAnimationActive={false}
              >
                {rows.map((row) => (
                  <Cell
                    key={row.code}
                    fill={band.colour}
                    // Hollow while the day is still open: provisional, not low.
                    fillOpacity={row.complete ? 1 : 0.3}
                    stroke={row.complete ? undefined : band.colour}
                    strokeDasharray={row.complete ? undefined : '3 2'}
                  />
                ))}
              </Bar>
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <ul className="legend day-legend">
        {bands.map((band) => (
          <li key={band.key}>
            {/* The span in the title, so "when is this calculated" is one
                hover away rather than something to work out from the shape. */}
            <span
              className="legend__item legend__item--static"
              title={band.covers}
            >
              <span
                className="legend__swatch"
                style={{ color: band.colour, background: band.colour }}
                aria-hidden
              />
              {band.label}
              {band.covers && (
                <span className="day-legend__covers">{band.covers}</span>
              )}
            </span>
          </li>
        ))}
        <li>
          <span className="legend__item legend__item--static">
            <span className="day-legend__key day-legend__bar day-legend__bar--open" />
            Still open, waiting on a closing reading
          </span>
        </li>
      </ul>
    </div>
  )
}

interface TooltipProps {
  active?: boolean
  payload?: { payload: Row }[]
  bands: Band[]
  unit: string
}

function DayTooltip({ active, payload, bands, unit }: TooltipProps) {
  const row = payload?.[0]?.payload
  if (!active || !row) return null

  // The dashboard's own tooltip, borrowed wholesale — a readout that looked
  // different here would read as a different kind of number.
  return (
    <div className="tooltip">
      <div className="tooltip__time">
        {row.code}
        {!row.complete && ' · still open'}
      </div>
      <ul className="tooltip__rows">
        {bands.map((band) => {
          const value = row[band.key]
          if (typeof value !== 'number') return null
          return (
            <li key={band.key} className="tooltip__row">
              <span
                className="tooltip__swatch"
                style={{ background: band.colour }}
                aria-hidden
              />
              <span className="tooltip__label">{band.label}</span>
              <span className="tooltip__value">{amount(value, unit)}</span>
            </li>
          )
        })}
        {/* "Whole day", not "Day" — sitting directly under "Daytime", the
            short form reads as a repeat of the band above it rather than as
            the two of them added together. */}
        <li className="tooltip__row log-tip__total">
          <span className="tooltip__label">Whole day</span>
          <span className="tooltip__value">{amount(row.total, unit)}</span>
        </li>
      </ul>
    </div>
  )
}
