import { describeMeasurements } from '@/lib/format'
import type { HealthStatus } from '@/lib/types'

interface DashboardReadoutProps {
  /** Minutes per plotted point, or 0 when nothing came back. */
  bucketMinutes: number
  health: HealthStatus | null
  /** When the payload on screen was read, in epoch ms. */
  readAt: number | null
}

/**
 * What the picker beside it does not already say.
 *
 * The selected preset states the window in ink; repeating it here as
 * "Showing 24 hours" was the same fact twice. What is left is the three
 * things the reader cannot see anywhere else on the page: how coarse the
 * points are, how many kinds of feed exist, and when this was true.
 */
export function DashboardReadout({ bucketMinutes, health, readAt }: DashboardReadoutProps) {
  return (
    <dl className="readout filter-row__readout">
      {bucketMinutes > 0 && (
        <div
          className="readout__item"
          title={
            `Every chart on this page plots one point per ` +
            `${bucketMinutes} minutes. Readings arrive faster than ` +
            `that; a wider window groups more of them into each point.`
          }
        >
          <dt className="readout__key">Resolution</dt>
          <dd className="readout__value">{bucketMinutes} min</dd>
        </div>
      )}

      {health?.measurement_count != null && (
        <div
          className="readout__item"
          title={describeMeasurements(health.measurement_count)}
        >
          <dt className="readout__key">Feeds</dt>
          <dd className="readout__value">{health.measurement_count} measurement types</dd>
        </div>
      )}

      {/* When what is on screen was actually measured. A cached payload is
          drawn the instant a window is re-selected, which is what makes the
          page quick — and would make it quietly dishonest without this, since
          a chart from four minutes ago looks exactly like one from now. */}
      {readAt !== null && (
        <div
          className="readout__item"
          title="When the figures on this page were read from the habitat."
        >
          <dt className="readout__key">Read at</dt>
          <dd className="readout__value">
            {new Date(readAt).toLocaleTimeString(undefined, {
              hour: '2-digit',
              minute: '2-digit',
              second: '2-digit',
            })}
          </dd>
        </div>
      )}
    </dl>
  )
}
