/**
 * One panel's chart.
 *
 * Three forms, picked by what the number is rather than by preference:
 *
 *   line   a level or rate sampled over time — temperature, power draw.
 *   area   a single level where the filled region reads as "how full".
 *   bar    a quantity per interval — consumption, net change. Discrete
 *          buckets deserve discrete marks; a line would imply readings
 *          between them.
 *
 * There is exactly one y-axis. Two measures of different scale get two
 * panels, never a second axis — a dual axis lets the author place the
 * crossing point wherever they like, which is a way of drawing a conclusion
 * rather than showing data.
 */

import { useMemo, useState } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { AxisDomain } from 'recharts/types/util/types'

import {
  formatValue,
  makeTickFormatter,
  toChartRows,
  unitSuffix,
} from '@/lib/chartData'
import { CHART_INK } from '@/lib/palette'
import type { ChartKind, Panel } from '@/lib/types'

import { ChartLegend } from './ChartLegend'
import { ChartTooltip } from './ChartTooltip'

interface PanelChartProps {
  panel: Panel
  /** Series key -> colour, assigned by entity so filtering never repaints. */
  colours: Map<string, string>
  /**
   * Series key -> stroke dash pattern, empty for a plain series. Used when
   * one room reports under two tag spellings: both lines are that room's
   * colour, and the dash is what separates the sensor groups without
   * spending a second colour on a place that already has one.
   */
  dashes: Map<string, string>
  windowMinutes: number
}

/* Room on the right for the last time label, which is centred on its tick
   and would otherwise be clipped by the card edge. Shared by all three chart
   types so they cannot drift apart. */
const PLOT_MARGIN = { top: 8, right: 20, bottom: 0, left: 0 }

const AXIS_TICK = {
  fill: CHART_INK.label,
  fontSize: 10,
  fontFamily: 'var(--font-mono)',
  letterSpacing: '0.04em',
}

/**
 * Where the value axis starts, decided by what the mark encodes.
 *
 *   bar   length encodes magnitude, so it must start at zero — a truncated
 *         bar misstates the ratio between two bars. Signed values (net
 *         change) extend below the baseline, so the floor is the lower of
 *         zero and the data.
 *   area  the filled region reads as "how much is in the tank", which is an
 *         amount measured from zero.
 *   line  position encodes the value, not length. Room temperature lives
 *         between 19 °C and 27 °C; anchoring that axis at zero spends four
 *         fifths of the height on a range the data never visits and flattens
 *         every difference worth seeing.
 */
function valueDomain(chart: ChartKind): AxisDomain {
  if (chart === 'bar') return [(min: number) => Math.min(0, min), 'auto']
  if (chart === 'area') return [0, 'auto']
  return ['auto', 'auto']
}

export function PanelChart({
  panel,
  colours,
  dashes,
  windowMinutes,
}: PanelChartProps) {
  const [isolated, setIsolated] = useState<string | null>(null)

  const rows = useMemo(() => toChartRows(panel.series), [panel.series])
  const tickFormatter = useMemo(
    () => makeTickFormatter(windowMinutes),
    [windowMinutes],
  )

  const labels = useMemo(
    () => new Map(panel.series.map((entry) => [entry.key, entry.label])),
    [panel.series],
  )

  const visible = useMemo(
    () => (isolated ? panel.series.filter((s) => s.key === isolated) : panel.series),
    [isolated, panel.series],
  )

  const suffix = unitSuffix(panel)
  const legend = panel.series.map((entry) => ({
    key: entry.key,
    label: entry.label,
    colour: colours.get(entry.key) ?? 'var(--series-1)',
    dashed: Boolean(dashes.get(entry.key)),
  }))

  const shared = (
    <>
      {/* A plain hairline rather than a dashed one — the dash is now doing
          work on the series themselves, and a dashed grid would compete. */}
      <CartesianGrid stroke={CHART_INK.grid} vertical={false} />
      <XAxis
        dataKey="t"
        type="number"
        scale="time"
        domain={['dataMin', 'dataMax']}
        tickFormatter={tickFormatter}
        tick={AXIS_TICK}
        stroke={CHART_INK.axis}
        tickLine={false}
        minTickGap={48}
      />
      <YAxis
        tick={AXIS_TICK}
        stroke={CHART_INK.axis}
        tickLine={false}
        axisLine={false}
        width={52}
        domain={valueDomain(panel.chart)}
        tickFormatter={(value: number) => formatValue(value)}
      />
      <Tooltip
        content={<ChartTooltip labels={labels} unit={suffix} />}
        cursor={{ stroke: CHART_INK.cursor, strokeWidth: 1 }}
        // Recharts' default animation lags the cursor by a frame, which on a
        // crosshair reads as the readout belonging to the wrong point.
        isAnimationActive={false}
      />
    </>
  )

  return (
    <div className="panel-chart">
      <ChartLegend entries={legend} isolated={isolated} onIsolate={setIsolated} />

      {/* The plot takes whatever height the card has left after the head, the
          legend, and the source row. Cards in a row are the same height, so
          their plots end on the same line — which is what lets the eye read
          one timestamp across three charts. */}
      <div className="panel-chart__plot">
        <ResponsiveContainer width="100%" height="100%">
          {panel.chart === 'bar' ? (
            <BarChart data={rows} margin={PLOT_MARGIN}>
              {shared}
              {visible.map((entry) => (
                <Bar
                  key={entry.key}
                  dataKey={entry.key}
                  fill={colours.get(entry.key) ?? 'var(--series-1)'}
                  isAnimationActive={false}
                />
              ))}
            </BarChart>
          ) : panel.chart === 'area' ? (
            <AreaChart data={rows} margin={PLOT_MARGIN}>
              {shared}
              {visible.map((entry) => {
                const colour = colours.get(entry.key) ?? 'var(--series-1)'
                return (
                  <Area
                    key={entry.key}
                    // Straight segments between samples. A monotone spline
                    // draws values the sensor never reported, which is the
                    // one thing a readout must not do.
                    type="linear"
                    dataKey={entry.key}
                    stroke={colour}
                    strokeWidth={1.75}
                    strokeDasharray={dashes.get(entry.key) || undefined}
                    fill={colour}
                    fillOpacity={0.12}
                    // A gap means the sensor said nothing; do not bridge it.
                    connectNulls={false}
                    dot={false}
                    isAnimationActive={false}
                  />
                )
              })}
            </AreaChart>
          ) : (
            <LineChart data={rows} margin={PLOT_MARGIN}>
              {shared}
              {visible.map((entry) => (
                <Line
                  key={entry.key}
                  type="linear"
                  dataKey={entry.key}
                  stroke={colours.get(entry.key) ?? 'var(--series-1)'}
                  strokeWidth={1.75}
                  strokeDasharray={dashes.get(entry.key) || undefined}
                  connectNulls={false}
                  dot={false}
                  activeDot={{ r: 3, strokeWidth: 0 }}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  )
}
