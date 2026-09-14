/**
 * The time window control.
 *
 * A single row of presets above the charts, shortest first, one selected at a
 * time. Every panel on the page shares it — a dashboard where two charts
 * cover different windows invites comparing figures that are not comparable.
 *
 * Eleven presets in an undifferentiated row is a wall of very similar tokens.
 * They are chunked into minutes, hours, and days by a heavier line between the
 * groups, so picking "5 hours" over "5 days" is a matter of looking at the
 * right third of the row rather than reading every label.
 *
 * CUSTOM sits at the end of the same row rather than in a control of its own,
 * because it is the same choice: exactly one window is in force, and it is
 * either one of the presets or one the reader set the start of. Selecting it
 * opens a start-time field under the row and leaves it open, so the window in
 * force is always legible — a custom window whose control had closed would be
 * the only selection on the page that did not say what it was.
 *
 * The presets are relative and re-answer themselves; a custom window is an
 * instant and does not. That difference is stated where it matters, in the
 * field's own caption, rather than left for a reader to discover.
 */

import { useEffect, useState } from 'react'

import {
  customRangeKey,
  customRangeProblem,
  customRangeStart,
  describeSpan,
  FALLBACK_RANGES,
  fromLocalInput,
  isCustomRange,
  MAX_CUSTOM_DAYS,
  spanMinutes,
  toLocalInput,
} from '@/lib/ranges'
import type { RangeOption } from '@/lib/types'

export { FALLBACK_RANGES } from '@/lib/ranges'

/** Minutes, hours, or days — which third of the row an option belongs to. */
function scaleOf(minutes: number): 'minutes' | 'hours' | 'days' {
  if (minutes < 60) return 'minutes'
  if (minutes < 60 * 24) return 'hours'
  return 'days'
}

interface RangePickerProps {
  ranges: RangeOption[]
  value: string
  onChange: (key: string) => void
}

export function RangePicker({ ranges, value, onChange }: RangePickerProps) {
  const custom = isCustomRange(value)

  // Open whenever a custom window is in force, and while one is being set up.
  const [editing, setEditing] = useState(custom)

  // What the field holds, which is not the window in force until Apply is
  // pressed — the reader is mid-edit between the two, and a field that
  // committed on every keystroke would fire a query per digit typed.
  const [draft, setDraft] = useState(() => toLocalInput(seedStart(value, ranges)))

  // A custom window chosen elsewhere — restored from the last visit, or set
  // in another tab — has to show up in the field rather than leave it on
  // whatever it was seeded with.
  useEffect(() => {
    const start = customRangeStart(value)
    if (start) {
      setDraft(toLocalInput(start))
      setEditing(true)
    }
  }, [value])

  const parsed = fromLocalInput(draft)
  const problem = parsed ? customRangeProblem(parsed) : 'Pick a date and a time.'
  const applied = parsed && !problem ? customRangeKey(parsed) : null

  const options = ranges.length > 0 ? ranges : FALLBACK_RANGES

  return (
    <div className="window-picker">
      <div className="ranges" role="group" aria-label="Time range">
        {options.map((option, position) => {
          const previous = options[position - 1]
          const startsGroup =
            position > 0 && scaleOf(option.minutes) !== scaleOf(previous!.minutes)

          return (
            <button
              key={option.key}
              type="button"
              className={[
                'range',
                option.key === value ? 'range--on' : '',
                startsGroup ? 'range--group' : '',
              ]
                .filter(Boolean)
                .join(' ')}
              onClick={() => {
                setEditing(false)
                onChange(option.key)
              }}
              aria-pressed={option.key === value}
              title={
                `Show the last ${option.label} on every panel, ` +
                `drawn at one point per ${option.bucket_minutes} min`
              }
            >
              {option.label}
            </button>
          )
        })}

        <button
          type="button"
          className={['range', 'range--group', custom ? 'range--on' : '']
            .filter(Boolean)
            .join(' ')}
          onClick={() => {
            // Seeded here rather than once at mount: the window to open on is
            // the one on screen NOW. Seeded at mount, the field offered
            // whatever had been selected when the page loaded, so pressing
            // Custom while looking at 48 hours proposed a fortnight.
            if (!custom) setDraft(toLocalInput(seedStart(value, options)))
            setEditing((open) => !open || !custom)
          }}
          aria-pressed={custom}
          aria-expanded={editing}
          title="Chart from a moment you choose, up to now"
        >
          Custom
        </button>
      </div>

      {editing && (
        <div className="since">
          <label className="since__label" htmlFor="since-start">
            Start
          </label>

          <input
            id="since-start"
            type="datetime-local"
            className="since__input"
            value={draft}
            max={toLocalInput(new Date())}
            min={toLocalInput(new Date(Date.now() - MAX_CUSTOM_DAYS * 86_400_000))}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && applied) onChange(applied)
            }}
          />

          <button
            type="button"
            className="button button--primary"
            onClick={() => applied && onChange(applied)}
            // Already the window on screen: pressing it again would refetch
            // the same thing, which is what the Refresh button is for.
            disabled={applied === null || applied === value}
          >
            <span className="button__label">Apply</span>
          </button>

          {problem ? (
            <span className="since__note since__note--bad" role="status">
              {problem}
            </span>
          ) : (
            <span className="since__note">
              {custom && applied === value
                ? `Showing ${describeSpan(spanMinutes(value, options))}: ` +
                  'this moment to now, growing as time passes'
                : `${describeSpan(spanMinutes(applied ?? '', options))} to now`}
            </span>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * Where the field starts when Custom is first pressed.
 *
 * The window already on screen, expressed as the instant it began. Pressing
 * Custom and then Apply without touching anything gives back what was there,
 * which is the least surprising thing it could do — and it puts the reader's
 * cursor next to the hour they actually want to change.
 */
function seedStart(value: string, ranges: RangeOption[]): Date {
  const existing = customRangeStart(value)
  if (existing) return existing

  const minutes = spanMinutes(value, ranges) || 1440
  return new Date(Date.now() - minutes * 60_000)
}
