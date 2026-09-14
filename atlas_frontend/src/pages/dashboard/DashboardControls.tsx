import { RangePicker } from '@/components/RangePicker'
import { Refresh, Rooms } from '@/icons'
import { RoomSelect } from '@/components/RoomSelect'
import { ViewSwitch } from '@/components/ViewSwitch'
import type { SeriesStyle } from '@/lib/palette'
import type { RoomIndex } from '@/lib/rooms'
import type { HealthStatus, RangeOption } from '@/lib/types'
import { isPanelView, VIEWS, type ViewKey } from '@/lib/views'

import { DashboardReadout } from './DashboardReadout'

interface DashboardControlsProps {
  view: ViewKey
  onViewChange: (key: ViewKey) => void
  range: string
  options: RangeOption[]
  onRangeChange: (key: string) => void
  index: RoomIndex
  styles: Map<string, SeriesStyle>
  selectedRooms: Set<string> | null
  onToggleRoom: (id: string) => void
  onSelectAllRooms: () => void
  onClearRooms: () => void
  bucketMinutes: number
  health: HealthStatus | null
  readAt: number | null
  /** Re-reads the panels. The mission view has its own, over its own request. */
  onRefresh: () => void
  refreshing: boolean
  loading: boolean
  /** Opens the crew meter log, which replaces this page while it is open. */
  onOpenLog: () => void
}

/**
 * The control strip: everything above the charts.
 *
 * Each control says what it does in a label to its left, on one column, so
 * the strip reads as a short form rather than as two rows of unexplained
 * tokens.
 *
 * Which rows appear is the point of this component. Mission plan is not made
 * of panels, so the controls that govern them — the shared window, the room
 * filter, the resolution readout — have nothing to act on while it is open,
 * and a control that changes nothing is worse than no control at all.
 */
export function DashboardControls({
  view,
  onViewChange,
  range,
  options,
  onRangeChange,
  index,
  styles,
  selectedRooms,
  onToggleRoom,
  onSelectAllRooms,
  onClearRooms,
  bucketMinutes,
  health,
  readAt,
  onRefresh,
  refreshing,
  loading,
  onOpenLog,
}: DashboardControlsProps) {
  const panels = isPanelView(view)
  const blurb = VIEWS.find((option) => option.key === view)?.blurb ?? ''

  return (
    <div className="controls">
      <div className="controls__inner bleed__inner">
        {/* The view comes first and its switch sits hard right, on the same
            column as the readout below it. It decides what the rows under it
            are even about, so it reads before them. */}
        <div className="filter-row">
          <span className="filter-row__label" id="filter-view">
            View
          </span>
          <p className="filter-row__blurb">{blurb}</p>
          <div className="filter-row__switch" aria-labelledby="filter-view">
            <ViewSwitch value={view} onChange={onViewChange} />
          </div>
        </div>

        {panels && (
          <div className="filter-row">
            <span className="filter-row__label" id="filter-window">
              Window
            </span>
            {/* Never disabled while a request is in flight. The window is what
                the reader came to change, and a picker that locks itself for
                the duration of the request it just started is the one control
                that must not. */}
            <div className="filter-row__body" aria-labelledby="filter-window">
              <RangePicker ranges={options} value={range} onChange={onRangeChange} />
            </div>

            {/* Its own column at the end of the row, so it cannot wrap into
                the middle of the picker.

                Refresh sits here rather than in the header because this is
                where its effect is visible: the figures arrive on their own,
                and the only reason to force a read is that "Read at" beside
                it has gone stale. */}
            <div className="filter-row__aside">
              <DashboardReadout
                bucketMinutes={bucketMinutes}
                health={health}
                readAt={readAt}
              />

              {/* The two actions travel together, so a narrow window wraps
                  them onto one line rather than stranding one of them under
                  the other. */}
              <div className="filter-row__buttons">
                <button
                  type="button"
                  className="button"
                  onClick={onRefresh}
                  disabled={loading || refreshing}
                  title="Read every panel again now"
                >
                  <Refresh />
                  <span className="button__label">
                    {refreshing ? 'Refreshing' : 'Refresh'}
                  </span>
                </button>

                {/* Habitat consumption only, and beside Refresh because it is
                    the same question asked of a different source: these charts
                    are the mains meter and the water feed, and the log behind
                    this button is the room-by-room account of the same draw,
                    read off dials by hand. On Room analysis it would be a
                    second, quieter way into a page that view does not own. */}
                {view === 'habitat' && (
                  <button
                    type="button"
                    className="button"
                    onClick={onOpenLog}
                    title={
                      'The crew meter log: power per room and water per tap, ' +
                      'from the rounds walked by hand, against the mission days'
                    }
                  >
                    <Rooms size={15} />
                    <span className="button__label">Crew meter log</span>
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Room analysis only. There is one clean-water tank and one mains
            meter, so a room filter over the habitat totals would be a control
            that changes nothing. */}
        {view === 'rooms' && index.rooms.length > 0 && (
          <div className="filter-row">
            <span className="filter-row__label" id="filter-rooms">
              Rooms
            </span>
            <div className="filter-row__body" aria-labelledby="filter-rooms">
              <RoomSelect
                rooms={index.rooms}
                selected={selectedRooms ?? new Set()}
                styles={styles}
                onToggle={onToggleRoom}
                onSelectAll={onSelectAllRooms}
                onClear={onClearRooms}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
