/**
 * The crew's meter log — a back-analysis of where the habitat's consumption
 * actually goes, room by room and tap by tap.
 *
 * WHY IT IS A PAGE OF ITS OWN, opened from the habitat charts rather than
 * living among them. Everything on the dashboard is telemetry: numbers that
 * arrived on their own, over a window the reader picks. Nothing here is. Every
 * figure on this page begins as somebody walking the habitat with a clipboard,
 * and its window is not a time range but the mission's own days. Those two
 * kinds of number under one set of controls would imply the controls applied
 * to both, which they never could — the same reasoning that split Habitat
 * consumption from Room analysis in the first place. See `lib/views.ts`.
 *
 * THE ORDER IS THE ARGUMENT. The answer first: three windows, each with its
 * distribution — today, the last three days, the whole mission — because "the
 * dormitory is a third of our power" is the sentence somebody came here for.
 * Then the detail behind it, then the day-by-day shape, then the check against
 * the habitat's own meters, and only then the sheet the whole thing was typed
 * into. Data entry is last on purpose: it is the most of the page and the
 * least of the point.
 *
 * WHAT IT REFUSES TO DO. It never fills in a missing round, never treats an
 * unclosed block as a quiet one, and never adds the crew's figures to the
 * database's. The entire value of a second, independent account is that it was
 * kept separately — the moment the two are blended there is nothing left to
 * check anything against.
 */

import { useMemo, useState } from 'react'

import { ChevronLeft, ChevronRight, Refresh, Warning } from '@/icons'
import { useLogbook } from '@/hooks/useLogbook'
import { useMission } from '@/hooks/useMission'
import { coverageReading, reconcile, STREAM_COLOUR, SLOT_COLOUR } from '@/lib/logbook'
import { amount, unitOf } from '@/lib/mission'
import type { LogResource } from '@/lib/types'

import { DailyChart } from './DailyChart'
import { LogSheet } from './LogSheet'
import { ReconcileCard } from './ReconcileCard'
import { ShareBars } from './ShareBars'
import { ShareDonut } from './ShareDonut'
import { WindowCard } from './WindowCard'

interface CrewLogPageProps {
  /** Back to the charts this page was opened from. */
  onClose: () => void
}

export function CrewLogPage({ onClose }: CrewLogPageProps) {
  const {
    logbook,
    loading,
    refreshing,
    error,
    saveError,
    saving,
    refresh,
    write,
    clear,
  } = useLogbook()

  // The habitat's own account of the same days, for the check at the bottom.
  // Its own hook, its own cache, its own failure: an unreachable habitat
  // database costs this page one card and nothing else, which matters because
  // reading dials by hand is exactly what a crew does when telemetry is down.
  const { tracking } = useMission()

  const [resourceKey, setResourceKey] = useState<'power' | 'water'>('power')
  const [detailWindow, setDetailWindow] = useState('mission')
  const [confirmingClear, setConfirmingClear] = useState(false)

  const resource = useMemo<LogResource | null>(
    () => logbook?.resources.find((item) => item.key === resourceKey) ?? null,
    [logbook, resourceKey],
  )

  const detail = useMemo(
    () => resource?.windows.find((item) => item.key === detailWindow) ?? null,
    [resource, detailWindow],
  )

  const tracked = useMemo(
    () => tracking?.resources.find((item) => item.key === resourceKey) ?? null,
    [tracking, resourceKey],
  )

  const check = useMemo(
    () => (resource ? reconcile(resource, tracked, tracked ? unitOf(tracked) : '') : null),
    [resource, tracked],
  )

  if (loading) {
    return <p className="dashboard__status">Loading the crew's meter log…</p>
  }

  if (error && !logbook) {
    return (
      <div className="log">
        <Bar onClose={onClose} onRefresh={refresh} refreshing={refreshing} />
        <div className="error" role="alert">
          <div className="error__body">
            <div className="error__title">Could not load the meter log</div>
            <div>{error}</div>
          </div>
        </div>
      </div>
    )
  }

  if (!logbook || !resource) return null

  const mission = logbook.mission

  // No mission, no mission days, and the sheet is a grid of days. The page
  // says so and sends the reader to the one place that can fix it, rather
  // than drawing an empty table with no rows in it.
  if (!mission.is_declared) {
    return (
      <div className="log">
        <Bar onClose={onClose} onRefresh={refresh} refreshing={refreshing} />
        <div className="mission__banner">
          <Warning size={15} />
          <div>
            <p className="mission__banner-title">
              There is no mission to log against yet
            </p>
            <p className="mission__banner-text">
              One row per mission day, MD-01 to the last.
              so it needs a mission's start date and length before it has any
              rows to offer. Declare one on the Mission plan view, and the sheet
              appears with a row for every planned day.
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="log" aria-busy={refreshing}>
      <Bar
        onClose={onClose}
        onRefresh={refresh}
        refreshing={refreshing}
        mission={mission.name || 'Unnamed mission'}
        position={
          mission.day_code
            ? `${mission.day_code} of ${mission.days}`
            : `${mission.days} days`
        }
        readAt={logbook.generated_at}
      />

      <p className="log__lede">
        Where the habitat's consumption actually goes, from the readings the
        crew takes by hand.
      </p>

      {/* Which sheet is on screen. Power and water are metered by different
          dials on different rounds and share nothing but the mission's days,
          so they are one at a time, as the dashboard's own views are. */}
      <div className="log__switch">
        <div className="views" role="group" aria-label="Which meters">
          {logbook.resources.map((item) => (
            <button
              key={item.key}
              type="button"
              className={item.key === resourceKey ? 'view view--on' : 'view'}
              onClick={() => setResourceKey(item.key)}
              aria-pressed={item.key === resourceKey}
            >
              {item.label}
            </button>
          ))}
        </div>
        <p className="log__coverage">{coverageReading(resource)}</p>
      </div>

      {saveError && (
        <p className="plan__error" role="alert">
          <Warning size={13} />
          {saveError}
        </p>
      )}

      {/* A meter that appears to have counted down. Said at the top, because
          every total below it is missing the two days either side of it. */}
      {resource.issues.map((issue) => (
        <div key={issue} className="mission__warning">
          <Warning size={13} />
          <span>{issue}</span>
        </div>
      ))}

      {error && (
        <div className="error" role="alert">
          <div className="error__body">
            <div className="error__title">Could not re-read the log</div>
            <div>{error}</div>
            <div className="error__aside">
              The figures below are the last ones that did arrive.
            </div>
          </div>
        </div>
      )}

      <section className="dashboard__group">
        <h2 className="dashboard__group-title">
          Where it went
          <span className="card__unit">{resource.unit}</span>
        </h2>

        <div className="log__windows">
          {resource.windows.map((window) => (
            <WindowCard
              key={window.key}
              window={window}
              resource={resource}
              // Power is seven rooms — inside the palette, and each one is its
              // own place. Water is eleven taps, which is more slices than
              // there are validated hues, so the ring draws what they serve
              // and the taps themselves are ranked as bars below.
              slices={resource.key === 'power' ? 'meters' : 'groups'}
            />
          ))}
        </div>
      </section>

      {detail && (
        <section className="dashboard__group">
          <div className="log__detail-head">
            <h2 className="dashboard__group-title">
              {resource.key === 'power' ? 'Every room' : 'Every tap'}
              <span className="card__unit">{resource.unit}</span>
            </h2>

            <div className="views views--small" role="group" aria-label="Which window">
              {resource.windows.map((window) => (
                <button
                  key={window.key}
                  type="button"
                  className={window.key === detailWindow ? 'view view--on' : 'view'}
                  onClick={() => setDetailWindow(window.key)}
                  aria-pressed={window.key === detailWindow}
                >
                  {window.label}
                </button>
              ))}
            </div>
          </div>

          <div className="log__detail">
            <section className="card log__detail-wide">
              <header className="card__head">
                <div className="card__heading">
                  <h3 className="card__title">
                    {resource.key === 'power' ? 'By room' : 'By tap'}
                  </h3>
                  <span className="card__unit">{detail.label.toLowerCase()}</span>
                </div>
              </header>

              <ShareBars
                rows={detail.meters}
                unit={resource.unit}
                colours={
                  resource.key === 'water'
                    ? Object.fromEntries(
                        resource.meters.map((meter) => [
                          meter.key,
                          STREAM_COLOUR[meter.stream] ?? 'var(--series-1)',
                        ]),
                      )
                    : undefined
                }
              />
            </section>

            {/* Warm against cold is a water question and has no power
                equivalent; day against night is asked of both, now that the
                taps are read on the same two rounds as the rooms. So water
                gets three cards here and power two, rather than one card
                changing its meaning depending on which sheet is open. */}
            {resource.key === 'water' && (
              <section className="card">
                <header className="card__head">
                  <div className="card__heading">
                    <h3 className="card__title">Warm against cold</h3>
                    <span className="card__unit">{detail.label.toLowerCase()}</span>
                  </div>
                </header>

                <ShareDonut
                  slices={detail.streams}
                  unit={resource.unit}
                  total={detail.total}
                  colours={STREAM_COLOUR}
                />
              </section>
            )}

            <section className="card">
              <header className="card__head">
                <div className="card__heading">
                  {/* Named for the two blocks exactly as the chart legend and
                      the sheet name them, so the same split does not go by
                      three names on one page. */}
                  <h3 className="card__title">Daytime against overnight</h3>
                  <span className="card__unit">{detail.label.toLowerCase()}</span>
                </div>
              </header>

              <ShareDonut
                slices={detail.slots}
                unit={resource.unit}
                total={detail.total}
                colours={SLOT_COLOUR}
              />
            </section>
          </div>
        </section>
      )}

      <section className="dashboard__group">
        <h2 className="dashboard__group-title">
          Day by day
          <span className="card__unit">
            MD-01 to MD-{String(mission.days ?? 0).padStart(2, '0')}
          </span>
        </h2>

        <section className="card log-daily">
          <header className="card__head">
            <div className="card__heading">
              <h3 className="card__title">
                {resource.label}, one bar per mission day
              </h3>
            </div>
            <p className="card__subtitle">
              Every day of the mission, whether or not it has been logged.
              {resource.windows.find((w) => w.key === 'mission')?.total !== null && (
                <>
                  {' '}
                  {amount(
                    resource.windows.find((w) => w.key === 'mission')?.total ?? null,
                    resource.unit,
                  )}{' '}
                  measured across the mission so far.
                </>
              )}{' '}
              A day with no bar is a day nobody has closed.
            </p>
          </header>

          <DailyChart resource={resource} />
        </section>
      </section>

      {check && (
        <section className="dashboard__group">
          <h2 className="dashboard__group-title">The check</h2>
          <ReconcileCard
            check={check}
            resource={resource}
            meterLabel={tracked?.label ?? 'the habitat meter'}
          />
        </section>
      )}

      <details className="panel log__sheet">
        <summary className="panel__summary">
          <ChevronRight className="panel__chevron" />
          <span className="panel__label">The sheet</span>
          <span className="panel__hint">
            where the rounds are written down. Every figure above is derived
            from these boxes and nothing else
          </span>
        </summary>
        <div className="panel__body">
          <LogSheet resource={resource} saving={saving} onWrite={write} />

          <p className="log__clear">
            {confirmingClear ? (
              <>
                <span className="log__clear-ask">
                  Delete every {resource.key} reading in this log? The rounds
                  behind them cannot be walked again.
                </span>
                <button
                  type="button"
                  className="button button--danger"
                  onClick={() => {
                    void clear(resource.key)
                    setConfirmingClear(false)
                  }}
                >
                  <span className="button__label">Delete them</span>
                </button>
                <button
                  type="button"
                  className="button"
                  onClick={() => setConfirmingClear(false)}
                >
                  <span className="button__label">Keep them</span>
                </button>
              </>
            ) : (
              <button
                type="button"
                className="link-button"
                onClick={() => setConfirmingClear(true)}
              >
                Clear this log
              </button>
            )}
          </p>
        </div>
      </details>
    </div>
  )
}

interface BarProps {
  onClose: () => void
  onRefresh: () => void
  refreshing: boolean
  mission?: string
  position?: string
  readAt?: string
}

function Bar({
  onClose,
  onRefresh,
  refreshing,
  mission,
  position,
  readAt,
}: BarProps) {
  return (
    <div className="mission__bar">
      <dl className="readout">
        <div className="readout__item">
          <dt className="readout__key">Log</dt>
          <dd className="readout__value">Crew meter rounds</dd>
        </div>
        {mission && (
          <div className="readout__item">
            <dt className="readout__key">Mission</dt>
            <dd className="readout__value">{mission}</dd>
          </div>
        )}
        {position && (
          <div className="readout__item">
            <dt className="readout__key">Where we are</dt>
            <dd className="readout__value">{position}</dd>
          </div>
        )}
        {readAt && (
          <div
            className="readout__item"
            title="When these figures were worked out from the readings on disk."
          >
            <dt className="readout__key">Read at</dt>
            <dd className="readout__value">
              {new Date(readAt).toLocaleTimeString(undefined, {
                hour: '2-digit',
                minute: '2-digit',
              })}
            </dd>
          </div>
        )}
      </dl>

      <div className="mission__actions">
        <button
          type="button"
          className="button"
          onClick={onRefresh}
          disabled={refreshing}
          title="Re-read the log from disk and work the figures out again"
        >
          <Refresh />
          <span className="button__label">{refreshing ? 'Reading' : 'Refresh'}</span>
        </button>

        <button type="button" className="button button--primary" onClick={onClose}>
          <ChevronLeft />
          <span className="button__label">Back to the charts</span>
        </button>
      </div>
    </div>
  )
}
