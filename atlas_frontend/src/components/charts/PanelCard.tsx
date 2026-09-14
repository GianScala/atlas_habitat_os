/**
 * The frame around one chart: title, caption, unit, and the query behind it.
 *
 * The query disclosure is the same promise the chat makes — a figure on this
 * page is as checkable as one in an answer. A panel that failed says why and
 * leaves the rest of the page alone.
 *
 * Every card is built to the same vertical skeleton — fixed head, plot that
 * takes whatever height is left, source row pinned to the foot — so that the
 * cards in a row line up along their tops AND their bottoms whatever their
 * captions, legends, or failure states happen to be.
 */

import { isAllZero, isEmpty } from '@/lib/chartData'
import type { Panel } from '@/lib/types'

import { ChevronRight, NoSignal, Rooms, Warning } from '@/icons'

import { PanelChart } from './PanelChart'

interface PanelCardProps {
  panel: Panel
  colours: Map<string, string>
  /** Series key -> stroke dash, for a room reported under several tags. */
  dashes: Map<string, string>
  windowMinutes: number
  /**
   * True when this panel draws rooms and the room filter removed all of
   * them. An empty chart then says nothing about the sensors — it is the
   * filter's doing, and the card should say so rather than blaming the data.
   */
  filteredOut?: boolean
  /** The next window out, offered when this one came back empty. */
  wider?: { key: string; label: string } | null
  onWiden?: (key: string) => void
}

export function PanelCard({
  panel,
  colours,
  dashes,
  windowMinutes,
  filteredOut,
  wider,
  onWiden,
}: PanelCardProps) {
  const known = panel.unit_source === 'known' && panel.unit

  /* A short token in the corner, with the long explanation on hover. The full
     sentence used to sit in the header, where it wrapped the title onto a
     second line and knocked that card out of step with its neighbours. */
  const unitLabel = known ? panel.unit : 'no unit'
  const unitTitle = known
    ? `Values are in ${panel.unit}`
    : (panel.unit_note ?? 'The database does not record a unit for this field.')

  /* How often this chart plots a point, in words rather than in the database's
     word for it.

     This used to read "10 MIN BUCKETS". A bucket is what InfluxQL calls the
     interval it groups readings into, and nothing outside a database calls it
     that — next to WATER.LITRES it reads as a pail, and on the power charts it
     reads as a mistake. It is neither: the sensors report far more often than
     any chart can draw, so readings are grouped into equal intervals and each
     interval becomes one point. That is true of every panel here, which is why
     the note appears on all of them. */
  const cadence = panel.bucket_minutes
    ? panel.mode === 'mean'
      ? `Each point is ${panel.bucket_minutes} minutes of readings averaged into one. ` +
        `The sensors report more often than a chart this wide can draw.`
      : `Each point covers ${panel.bucket_minutes} minutes: how far the reading ` +
        `moved over that interval, not its level.`
    : ''

  return (
    <section className="card">
      <header className="card__head">
        <div className="card__heading">
          <h2 className="card__title" title={panel.title}>
            {panel.title}
          </h2>
          <span
            className={known ? 'card__unit' : 'card__unit card__unit--unknown'}
            title={unitTitle}
          >
            {unitLabel}
          </span>
        </div>
        <p className="card__subtitle">{panel.subtitle}</p>
      </header>

      {panel.error ? (
        <div className="card__state card__state--error" role="alert">
          <Warning size={20} />
          <p className="card__state-title">This panel could not be drawn</p>
          <p className="card__state-text">{panel.error}</p>
        </div>
      ) : filteredOut ? (
        <div className="card__state">
          <Rooms size={20} />
          <p className="card__state-title">No rooms selected</p>
          <p className="card__state-text">
            This chart draws one line per room. Pick at least one room in the
            selector above to see it.
          </p>
        </div>
      ) : isEmpty(panel) ? (
        <div className="card__state">
          <NoSignal size={20} />
          <p className="card__state-title">No readings in this window</p>
          <p className="card__state-text">
            Nothing was recorded for {panel.measurement}.{panel.field} here.
            The sensor may be offline, or the window may start before the data
            does.
          </p>
          {wider && onWiden && (
            <button
              type="button"
              className="button card__state-action"
              onClick={() => onWiden(wider.key)}
              title={`Widen every panel on the page to ${wider.label}`}
            >
              <span className="button__label">Try {wider.label}</span>
            </button>
          )}
        </div>
      ) : (
        <>
          <PanelChart
            panel={panel}
            colours={colours}
            dashes={dashes}
            windowMinutes={windowMinutes}
          />

          {/* Drawn, because zero is what the sensor said — and labelled,
              because a flat chart and a dead feed look identical. */}
          {isAllZero(panel) && (
            <p className="card__note">
              Every interval in this window read exactly zero. The sensor
              reported; nothing changed.
            </p>
          )}
        </>
      )}

      {panel.query && (
        <details className="panel panel--flush">
          <summary className="panel__summary">
            <ChevronRight className="panel__chevron" />
            <span className="panel__label">Source</span>
            {/* "60m" next to an all-caps field name read as a prefix rather
                than a duration — mega, or metres. Spelling out "min" costs
                two characters and removes the only ambiguity in the line. */}
            <span
              className="panel__hint"
              title={
                `Measurement ${panel.measurement}, field ${panel.field}.` +
                (cadence ? ` ${cadence}` : '')
              }
            >
              {panel.measurement}.{panel.field}
              {panel.bucket_minutes ? ` · 1 point per ${panel.bucket_minutes} min` : ''}
            </span>
          </summary>
          <div className="panel__body">
            <code className="sources__query">{panel.query}</code>
          </div>
        </details>
      )}
    </section>
  )
}
