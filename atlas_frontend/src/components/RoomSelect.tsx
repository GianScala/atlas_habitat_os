/**
 * Which rooms appear on the per-room charts.
 *
 * A dropdown rather than a row of chips. Eleven chips wrapped across two
 * lines pushed the charts down the page and made the control strip the
 * loudest thing on it, for a choice most readers make once. Closed, it is one
 * button saying how many rooms are on; open, it is the whole list.
 *
 * Any number of rooms may be selected — one, several, or all of them. Past
 * the eighth the palette starts a second lap and those rooms are drawn
 * dashed, so no two rooms are ever the same mark; the swatch here shows the
 * mark each room will get, dash included, which is what makes the list a key
 * as well as a control.
 *
 * One entry is one room, even where the database reports it under more than
 * one tag spelling — see `lib/rooms.ts`.
 *
 * The rows are real checkboxes. Tab reaches them, space toggles them, and a
 * screen reader announces the state without any of it being reimplemented
 * here. The popup closes on Escape, on a click outside, and when focus
 * leaves it — and Escape hands focus back to the button that opened it.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import type { SeriesStyle } from '@/lib/palette'
import type { Room } from '@/lib/rooms'

import { ChevronDown } from '@/icons'

interface RoomSelectProps {
  rooms: Room[]
  /** Room ids currently shown. */
  selected: Set<string>
  /** Room id -> the colour and stroke its lines are drawn in. */
  styles: Map<string, SeriesStyle>
  onToggle: (id: string) => void
  onSelectAll: () => void
  onClear: () => void
}

/** What the closed button says. */
function summarise(rooms: Room[], selected: Set<string>): string {
  if (selected.size === 0) return 'No rooms'
  if (selected.size === rooms.length) return `All ${rooms.length} rooms`
  if (selected.size === 1) {
    const only = rooms.find((room) => selected.has(room.id))
    if (only) return only.label
  }
  return `${selected.size} of ${rooms.length} rooms`
}

export function RoomSelect({
  rooms,
  selected,
  styles,
  onToggle,
  onSelectAll,
  onClear,
}: RoomSelectProps) {
  const [open, setOpen] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)

  const close = useCallback(() => setOpen(false), [])

  useEffect(() => {
    if (!open) return

    // Pointer down rather than click: a mousedown outside should dismiss
    // before whatever was clicked reacts, not after.
    const onPointerDown = (event: PointerEvent) => {
      if (!wrap.current?.contains(event.target as Node)) close()
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      close()
      trigger.current?.focus()
    }

    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [close, open])

  if (rooms.length === 0) return null

  const allOn = selected.size === rooms.length

  return (
    <div
      className="room-select"
      ref={wrap}
      // Tabbing off the last checkbox leaves an open popup behind with
      // nothing in it focused, which reads as a stuck menu.
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) close()
      }}
    >
      <button
        type="button"
        ref={trigger}
        className={open ? 'room-select__trigger room-select__trigger--open' : 'room-select__trigger'}
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        aria-haspopup="dialog"
        title="Choose which rooms are drawn on every chart in this view"
      >
        <span className="room-select__value">{summarise(rooms, selected)}</span>
        <ChevronDown className="room-select__caret" />
      </button>

      {open && (
        <div className="room-select__popup" role="dialog" aria-label="Rooms shown">
          <div className="room-select__head">
            <span className="room-select__count">
              {selected.size} of {rooms.length}
            </span>
            <div className="room-select__actions">
              <button
                type="button"
                className="link-button"
                onClick={onSelectAll}
                disabled={allOn}
                title="Show every room"
              >
                Select all
              </button>
              <button
                type="button"
                className="link-button"
                onClick={onClear}
                disabled={selected.size === 0}
                title="Hide every room"
              >
                Clear
              </button>
            </div>
          </div>

          <ul className="room-select__list">
            {rooms.map((room) => {
              const style = styles.get(room.id)
              const tags = room.keys.length

              return (
                <li key={room.id}>
                  <label
                    className="room-option"
                    title={
                      tags > 1
                        ? `${room.label}, reported under ${tags} tag spellings ` +
                          `(${room.keys.join(', ')}). Each is a separate sensor group, ` +
                          `drawn in this room's colour; the extra ones are dashed.`
                        : room.label
                    }
                  >
                    <input
                      type="checkbox"
                      className="room-option__box"
                      checked={selected.has(room.id)}
                      onChange={() => onToggle(room.id)}
                    />
                    {/* `color`, not `background`, so the dashed variant can
                        build its pattern out of the same value — the same
                        mark the chart legend uses. */}
                    <span
                      className={
                        style?.dash
                          ? 'room-option__swatch room-option__swatch--dashed'
                          : 'room-option__swatch'
                      }
                      style={{ color: style?.colour }}
                      aria-hidden
                    />
                    <span className="room-option__name">{room.label}</span>
                    {tags > 1 && <span className="room-option__note">{tags} tags</span>}
                  </label>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </div>
  )
}
