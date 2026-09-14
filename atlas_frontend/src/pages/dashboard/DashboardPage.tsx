/**
 * The dashboard page.
 *
 * Two views over one payload. Habitat consumption is the whole-habitat
 * meters — water drawn, mains power — which no room owns a share of, so it
 * carries no room filter. Room analysis is the per-room feeds, with a
 * selector for which rooms to draw. `lib/views.ts` has the reasoning; the
 * short version is that one room filter sitting above both kinds implied it
 * applied to both, and it never could.
 *
 * Both views share one time window, chosen once at the top, and one style
 * assignment — a room is the same colour on the temperature chart as on the
 * power chart, which is what makes reading across them possible. Switching
 * views is free: every panel arrives in a single request, and the switch
 * chooses between them rather than refetching.
 *
 * This file is the arrangement and nothing else. What the reader chose is in
 * `useDashboardState`, what a chart needs in order to draw is in `drawable`,
 * and the two blocks of interface are in `DashboardControls` and `PanelGrid`.
 */

import { lazy, Suspense, useMemo, useState } from 'react'

import { AppHeader } from '@/components/AppHeader'
import { useDashboard } from '@/hooks/useDashboard'
import { useHealth } from '@/hooks/useHealth'
import { describeRange, spanMinutes } from '@/lib/ranges'
import { isPanelView } from '@/lib/views'

import { MissionView } from '../mission/MissionView'
import { DashboardControls } from './DashboardControls'
import { buildDrawables, groupDrawables } from './drawable'
import { PanelGrid } from './PanelGrid'
import { useDashboardPrefs, useRangeOptions } from './useDashboardPrefs'
import { useRoomSelection } from './useRoomSelection'

/**
 * Loaded only when it is opened. The log is a page most visits never touch —
 * it is where a crew goes once a day with a clipboard, not where they look to
 * see how the habitat is doing — and it carries its own charts and its own
 * fourteen-by-eleven sheet.
 */
const CrewLogPage = lazy(() =>
  import('../logbook/CrewLogPage').then((module) => ({ default: module.CrewLogPage })),
)

export default function DashboardPage() {
  const { health, checking, error: healthError } = useHealth()

  /**
   * The crew meter log, open over the charts rather than beside them.
   *
   * Held here rather than in the URL for the same reason the view is: it is a
   * place in the page, not a page of its own, and the charts underneath it
   * keep their window and their scroll while it is open.
   */
  const [logOpen, setLogOpen] = useState(false)

  // Order matters here, and it is the reason these are three hooks rather
  // than one: the window has to settle before the request can be made, the
  // offered windows only exist once it has come back, and the rooms are read
  // out of the payload it returned.
  const { range, changeRange, view, changeView, resetRange } = useDashboardPrefs()

  const {
    dashboard,
    ranges,
    loading,
    refreshing,
    superseded,
    readAt,
    error,
    refresh,
  } = useDashboard(range)

  const options = useRangeOptions(ranges, range, resetRange)

  const {
    index,
    styles,
    selected: selectedRooms,
    toggle: toggleRoom,
    selectAll: selectAllRooms,
    clear: clearRooms,
  } = useRoomSelection(dashboard?.panels)

  // The window the charts are DRAWN from, which is the old one for as long as
  // a change is in flight. The axes are formatted from this, so reading it off
  // the selected range instead would label a 24-hour chart as five hours for
  // the moment in between.
  const windowMinutes = useMemo(
    () => spanMinutes(dashboard?.range ?? range, options) || 1440,
    [dashboard, options, range],
  )

  /**
   * The next window out, offered by a panel that came back empty.
   *
   * "No readings in this window" is usually the window's fault rather than the
   * sensor's, and the fix is one click — but only if the page hands it over
   * instead of leaving the reader to guess which preset is far enough.
   */
  const wider = useMemo(() => {
    const next = options.find((option) => option.minutes > windowMinutes)
    return next ? { key: next.key, label: next.label } : null
  }, [options, windowMinutes])

  const groups = useMemo(
    () =>
      groupDrawables(
        buildDrawables(dashboard?.panels ?? [], view, index, styles, selectedRooms),
      ),
    [dashboard, index, selectedRooms, styles, view],
  )

  // How often a point is plotted — read back from the data rather than from
  // the picker's advertised figure, since a range with sparse data can come
  // back coarser than the preset promised.
  const bucketMinutes = useMemo(
    () => dashboard?.panels.find((panel) => panel.bucket_minutes > 0)?.bucket_minutes ?? 0,
    [dashboard],
  )

  const panels = isPanelView(view)

  return (
    <div className="app">
      {/* Refresh is not up here. It belongs with the window it reloads and
          the "read at" it corrects, which are both in the control strip. */}
      <AppHeader
        tagline="habitat dashboard"
        health={health}
        checking={checking}
        error={healthError}
      />

      <div className="dashboard">
        {/* The log takes the whole page while it is open. Its figures are not
            telemetry and its window is the mission's own days, so the control
            strip above the charts governs nothing on it — and a strip of
            controls that changes nothing is worse than no strip at all. */}
        {logOpen ? (
          <div className="dashboard__scroll">
            <div className="dashboard__inner">
              <Suspense
                fallback={<p className="dashboard__status">Loading the meter log…</p>}
              >
                <CrewLogPage onClose={() => setLogOpen(false)} />
              </Suspense>
            </div>
          </div>
        ) : (
          <>
            <DashboardControls
              view={view}
              onViewChange={changeView}
              range={range}
              options={options}
              onRangeChange={changeRange}
              index={index}
              styles={styles}
              selectedRooms={selectedRooms}
              onToggleRoom={toggleRoom}
              onSelectAllRooms={selectAllRooms}
              onClearRooms={clearRooms}
              bucketMinutes={bucketMinutes}
              health={health}
              readAt={readAt}
              onRefresh={refresh}
              refreshing={refreshing}
              loading={loading}
              onOpenLog={() => setLogOpen(true)}
            />

            {/* Said between the controls and the charts, in the reading path from
                one to the other, because that is the journey the reader is making
                when it matters: they changed the window and are looking down to
                see what changed. */}
            {panels && !loading && (superseded || refreshing) && (
              <p className="dashboard__pending" role="status">
                <span className="dashboard__pending-dot" aria-hidden="true" />
                {superseded
                  ? `Loading ${describeRange(range, options)}. The charts below are ` +
                    `still ${describeRange(dashboard!.range, options)}`
                  : `Refreshing ${describeRange(range, options)}…`}
              </p>
            )}

            <div className="dashboard__scroll">
              {/* Superseded charts stay up rather than being blanked — a page that
                  empties itself loses the reader's place and tells them nothing
                  they did not already know. What it must not do is let them read
                  as the answer to the window now selected, so they are dimmed and
                  taken out of the tab order until they are. */}
              <div
                className={
                  superseded ? 'dashboard__inner dashboard__inner--superseded' : 'dashboard__inner'
                }
                aria-busy={loading || refreshing}
              >
                {!panels && <MissionView />}

                {panels && loading && <p className="dashboard__status">Loading panels…</p>}

                {/* A failed refresh does not delete the last good answer. Before,
                    any error emptied the page of charts that were still perfectly
                    readable — and still the best available account of the
                    habitat. */}
                {panels && error && (
                  <div className="error" role="alert">
                    <div className="error__body">
                      <div className="error__title">Could not load the dashboard</div>
                      <div>{error}</div>
                      {dashboard && (
                        <div className="error__aside">
                          The charts below are the last reading that did arrive,
                          from {describeRange(dashboard.range, options)} as at{' '}
                          {readAt !== null
                            ? new Date(readAt).toLocaleTimeString()
                            : 'an earlier moment'}
                          .
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* A view with no panels on this habitat — e.g. a deployment
                    with only per-room sensors has nothing for Habitat
                    consumption. Say so rather than showing a blank page. */}
                {panels && !loading && !error && groups.length === 0 && (
                  <p className="dashboard__status">
                    No {view === 'rooms' ? 'per-room' : 'habitat-wide'} charts
                    for this habitat. The dashboard follows the sensors your
                    database actually records.
                  </p>
                )}

                {panels && !loading && (
                  <PanelGrid
                    groups={groups}
                    windowMinutes={windowMinutes}
                    wider={wider}
                    onWiden={changeRange}
                  />
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
