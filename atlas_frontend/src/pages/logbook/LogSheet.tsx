/**
 * The clipboard, on screen.
 *
 * WHAT IS TYPED IS THE METER READING — the running total on the face, not the
 * amount used. Beside or beneath each box is what that reading turned out to
 * MEAN: the consumption it opens, once the reading that closes it exists. That
 * pairing is the whole design of this sheet. It makes the arithmetic visible at
 * the moment of entry, so a digit typed wrong is caught by the crew member who
 * typed it — who is the only person who can still go back and look at the dial
 * — rather than three days later by whoever reads the chart.
 *
 * TWO LAYOUTS, because there are two jobs and one grid cannot do both.
 *
 *   ONE DAY   the default, and what the rounds actually are. Every dial in the
 *             habitat on screen at once, morning and evening side by side,
 *             with the day's consumption worked out at the end of the row. A
 *             crew member walking back from the rounds fills this in without
 *             scrolling and without hunting for a column.
 *
 *   WHOLE MISSION  a row per day and a column per dial, one table per round.
 *             The auditing view: where you go to see that MD-06 is missing, or
 *             to compare a tap against itself across a fortnight. It is wide
 *             and it scrolls, which is fine for a job nobody does daily.
 *
 * The day view came first in the ordering for a reason. The old sheet only had
 * the mission grid, and filling in one morning's eleven taps meant scrolling a
 * fourteen-row table sideways — reading a column heading, scrolling back, and
 * losing which row you were on.
 *
 * SAVING IS PER BOX, on blur, and never on every keystroke. A round trip per
 * character would fight the typist for the cursor; a Save button over a
 * fourteen-by-eleven grid would be a button nobody presses until they have lost
 * an afternoon of work. Tab to the next box and the last one is stored.
 *
 * A REFUSED WRITE KEEPS WHAT WAS TYPED. Reverting the box to the last good
 * reading is indistinguishable from the write having worked, which is the one
 * outcome that must not be possible here.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'

import { ChevronLeft, ChevronRight, Warning } from '@/icons'
import { cellKey } from '@/hooks/useLogbook'
import { BLOCK_HINT, BLOCK_LABEL } from '@/lib/logbook'
import { amount } from '@/lib/mission'
import type {
  BlockUsage,
  LogResource,
  LogSlot,
  LoggedDay,
  ReadingEntry,
  ReadingWrite,
} from '@/lib/types'

type Layout = 'day' | 'mission'

interface LogSheetProps {
  resource: LogResource
  saving: Set<string>
  onWrite: (entry: ReadingWrite) => Promise<boolean>
}

export function LogSheet({ resource, saving, onWrite }: LogSheetProps) {
  const [layout, setLayout] = useState<Layout>('day')

  /**
   * Which day the day view is showing.
   *
   * Opens on today, because the overwhelmingly common reason to open this
   * sheet is that somebody has just walked a round. Falls back to the last
   * mission day when the mission is over and to the first when it has not
   * started — always a day that exists, so nothing below has to guard.
   */
  const [dayIndex, setDayIndex] = useState<number>(
    () => defaultDay(resource.days),
  )

  // A mission whose dates moved, or a switch between the two sheets, can leave
  // the selected day pointing at nothing.
  useEffect(() => {
    setDayIndex((current) =>
      resource.days.some((day) => day.index === current)
        ? current
        : defaultDay(resource.days),
    )
  }, [resource.days])

  /**
   * What is in a box that has been typed in but not yet accepted.
   *
   * Keyed by cell. A box with no draft shows the stored reading; a box with
   * one shows the draft, whether it is on its way to the backend or was
   * refused by it. That is what lets a refusal keep the crew's figure on
   * screen next to the reason it was refused.
   */
  const [drafts, setDrafts] = useState<Record<string, string>>({})

  const stored = useMemo(() => {
    const index = new Map<string, ReadingEntry>()
    for (const entry of resource.entries) {
      index.set(cellKey({ ...entry, resource: resource.key }), entry)
    }
    return index
  }, [resource])

  const derived = useMemo(() => {
    const index = new Map<string, BlockUsage>()
    for (const cell of resource.usage) {
      index.set(cellKey({ ...cell, resource: resource.key }), cell)
    }
    return index
  }, [resource])

  const commit = useCallback(
    async (key: string, entry: Omit<ReadingWrite, 'value'>, raw: string) => {
      const text = raw.trim()
      const previous = stored.get(key)
      const before = previous === undefined ? '' : String(previous.value)

      // Nothing typed, nothing to say. Notably this is also what stops a tab
      // through forty untouched boxes from firing forty writes.
      if (text === before) {
        setDrafts((current) => strip(current, key))
        return
      }

      if (text !== '' && !Number.isFinite(Number(text))) {
        // Held locally rather than sent: the backend would refuse it too, and
        // a round trip to be told "that is not a number" is a round trip to
        // learn what the box already knows.
        return
      }

      const done = await onWrite({
        ...entry,
        value: text === '' ? null : Number(text),
      })
      if (done) setDrafts((current) => strip(current, key))
    },
    [onWrite, stored],
  )

  if (resource.days.length === 0) return null

  const shared = {
    resource,
    stored,
    derived,
    drafts,
    saving,
    onDraft: (key: string, value: string) =>
      setDrafts((current) => ({ ...current, [key]: value })),
    onCommit: commit,
  }

  const day = resource.days.find((entry) => entry.index === dayIndex) ?? null

  return (
    <div className="sheet">
      <div className="sheet__modes">
        <div className="views views--small" role="group" aria-label="Sheet layout">
          <button
            type="button"
            className={layout === 'day' ? 'view view--on' : 'view'}
            onClick={() => setLayout('day')}
            aria-pressed={layout === 'day'}
          >
            One day
          </button>
          <button
            type="button"
            className={layout === 'mission' ? 'view view--on' : 'view'}
            onClick={() => setLayout('mission')}
            aria-pressed={layout === 'mission'}
          >
            Whole mission
          </button>
        </div>

        <p className="sheet__modes-note">
          {layout === 'day'
            ? 'Every dial for one day, both rounds side by side '
            : 'A row per day and a column per dial, one table per round '}
        </p>
      </div>

      {layout === 'day' && day && (
        <DaySheet
          {...shared}
          day={day}
          days={resource.days}
          onPick={setDayIndex}
        />
      )}

      {layout === 'mission' &&
        resource.slots.map((slot) => (
          <SlotTable key={slot.key} {...shared} slot={slot} />
        ))}
    </div>
  )
}

/** Today if the mission is running, else the nearest end of it. */
function defaultDay(days: LoggedDay[]): number {
  if (days.length === 0) return 1
  const today = days.find((day) => day.state === 'today')
  if (today) return today.index
  return days[0]!.state === 'future' ? days[0]!.index : days[days.length - 1]!.index
}

function strip(drafts: Record<string, string>, key: string): Record<string, string> {
  if (!(key in drafts)) return drafts
  const next = { ...drafts }
  delete next[key]
  return next
}

interface SharedProps {
  resource: LogResource
  stored: Map<string, ReadingEntry>
  derived: Map<string, BlockUsage>
  drafts: Record<string, string>
  saving: Set<string>
  onDraft: (key: string, value: string) => void
  onCommit: (
    key: string,
    entry: Omit<ReadingWrite, 'value'>,
    raw: string,
  ) => Promise<void>
}

/* --- One day ------------------------------------------------------------- */

interface DaySheetProps extends SharedProps {
  day: LoggedDay
  days: LoggedDay[]
  onPick: (index: number) => void
}

function DaySheet({
  resource,
  stored,
  derived,
  drafts,
  saving,
  onDraft,
  onCommit,
  day,
  days,
  onPick,
}: DaySheetProps) {
  const first = days[0]!.index
  const last = days[days.length - 1]!.index

  return (
    <section className="sheet__round">
      {/* The day picker. Arrows for the walk from yesterday to today, which is
          how it is nearly always moved, and a list for jumping to the day
          somebody is actually asking about. */}
      <div className="sheet__day-bar">
        <button
          type="button"
          className="button"
          onClick={() => onPick(day.index - 1)}
          disabled={day.index <= first}
          title="The day before"
        >
          <ChevronLeft />
          <span className="button__label">Previous</span>
        </button>

        <label className="sheet__day-pick">
          <span className="sheet__day-pick-label">Mission day</span>
          <select
            className="plan__input"
            value={day.index}
            onChange={(event) => onPick(Number(event.target.value))}
          >
            {days.map((entry) => (
              <option key={entry.code} value={entry.index}>
                {entry.code} · {entry.date}
                {entry.state === 'today' ? ' · today' : ''}
              </option>
            ))}
          </select>
        </label>

        <button
          type="button"
          className="button"
          onClick={() => onPick(day.index + 1)}
          disabled={day.index >= last}
          title="The day after"
        >
          <span className="button__label">Next</span>
          <ChevronRight />
        </button>

        <p className="sheet__day-state">
          {day.state === 'today'
            ? 'Today. The evening round closes tonight; the night closes on ' +
              "tomorrow's morning reading."
            : day.state === 'future'
              ? 'A day the mission has not reached. You can read ahead, but no ' +
                'round is due yet.'
              : `${day.blocks_logged} of ${day.blocks_expected} blocks on this day ` +
                'have both their readings.'}
        </p>
      </div>

      <div className="sheet__scroll">
        <table className="sheet__table sheet__table--day">
          <caption className="sheet__caption">
            {day.code} · the two left columns are what the DIAL SAID, in{' '}
            {resource.entry_unit}. The two right columns are what was USED
            between those readings, in {resource.unit}. Daytime is the morning
            round to the evening round, overnight is the evening round to
            tomorrow morning's.
          </caption>
          <thead>
            {/* Two headers, because the table is two different things side by
                side: readings typed in, and consumption worked out from them.
                Grouping them under a word each is what stops the derived
                columns being read as more boxes to fill. */}
            <tr className="sheet__super">
              <th scope="col" />
              <th scope="col" colSpan={resource.slots.length}>
                Readings off the dial
              </th>
              <th
                scope="col"
                colSpan={resource.slots.length + 1}
                className="sheet__super--derived"
              >
                Consumption between them
              </th>
            </tr>
            <tr>
              <th scope="col" className="sheet__corner">
                {resource.key === 'power' ? 'Room' : 'Tap'}
              </th>
              {resource.slots.map((slot) => (
                <th key={slot.key} scope="col" className="sheet__meter">
                  {slot.label}
                  <span className="sheet__code">{resource.entry_unit}</span>
                </th>
              ))}
              {resource.slots.map((slot) => (
                <th
                  key={`${slot.key}-used`}
                  scope="col"
                  className="sheet__meter sheet__meter--derived"
                  title={`Used ${slot.covers}.`}
                >
                  {slot.block_label}
                  <span className="sheet__code">{resource.unit}</span>
                </th>
              ))}
              <th
                scope="col"
                className="sheet__meter sheet__meter--derived"
                title="Daytime plus overnight: this morning's round to tomorrow morning's."
              >
                Whole day
                <span className="sheet__code">{resource.unit}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {resource.meters.map((meter) => {
              const keys = resource.slots.map((slot) =>
                cellKey({
                  resource: resource.key,
                  meter: meter.key,
                  day_index: day.index,
                  slot: slot.key,
                }),
              )
              const blocks = keys.map((key) => derived.get(key))

              return (
                <tr key={meter.key} className="sheet__row">
                  <th scope="row" className="sheet__day">
                    <span className="sheet__day-code">{meter.label}</span>
                    {meter.code && (
                      <span className="sheet__day-date">{meter.code}</span>
                    )}
                  </th>

                  {resource.slots.map((slot, position) => (
                    <td key={slot.key} className="sheet__cell">
                      <Box
                        label={`${meter.label}, ${day.code}, ${slot.label}`}
                        value={
                          drafts[keys[position]!] ??
                          (stored.has(keys[position]!)
                            ? String(stored.get(keys[position]!)!.value)
                            : '')
                        }
                        bad={blocks[position]?.status === 'backwards'}
                        future={day.state === 'future'}
                        busy={saving.has(keys[position]!)}
                        onDraft={(next) => onDraft(keys[position]!, next)}
                        onCommit={(raw) =>
                          onCommit(
                            keys[position]!,
                            {
                              resource: resource.key,
                              meter: meter.key,
                              day_index: day.index,
                              slot: slot.key,
                            },
                            raw,
                          )
                        }
                      />
                    </td>
                  ))}

                  {blocks.map((block, position) => (
                    <td
                      key={`used-${position}`}
                      className="sheet__cell sheet__cell--derived"
                    >
                      <Derived block={block} unit={resource.unit} />
                    </td>
                  ))}

                  <td className="sheet__cell sheet__cell--derived">
                    <DayTotal blocks={blocks} unit={resource.unit} />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}

/**
 * One dial's whole day: both blocks added up, or nothing at all.
 *
 * Deliberately refuses to add a half. A day with only its morning block
 * measured is not a day that used that much — it is a day nobody has finished
 * measuring, and printing the half as a total is exactly the misreading the
 * rest of this page spends its effort preventing.
 */
function DayTotal({ blocks, unit }: { blocks: (BlockUsage | undefined)[]; unit: string }) {
  const amounts = blocks.map((block) => block?.amount ?? null)
  if (amounts.some((value) => value === null)) {
    return (
      <span
        className="sheet__derived sheet__derived--open"
        title={
          'Both blocks need their readings before a day has a total. One ' +
          'block on its own is half a day, not a quiet one.'
        }
      />
    )
  }
  const total = amounts.reduce((sum: number, value) => sum + (value ?? 0), 0)
  return (
    <span className="sheet__derived sheet__derived--total">
      {amount(total, unit)}
    </span>
  )
}

/* --- The whole mission --------------------------------------------------- */

interface SlotTableProps extends SharedProps {
  slot: LogSlot
}

function SlotTable({
  slot,
  resource,
  stored,
  derived,
  drafts,
  saving,
  onDraft,
  onCommit,
}: SlotTableProps) {
  return (
    <section className="sheet__round">
      <header className="sheet__round-head">
        <h4 className="sheet__round-title">{slot.label}</h4>
        <p className="sheet__round-note">
          {slot.key === 'morning'
            ? 'Read at the start of the day. Against that evening it gives the ' +
              'DAYTIME consumption.'
            : 'Read at the end of the day. Against the NEXT morning it gives ' +
              'the OVERNIGHT consumption, which is why the last evening of the ' +
              'mission stays open.'}{' '}
          Every box takes the figure on the dial in{' '}
          <strong>{resource.entry_unit}</strong>
          {resource.entry_unit !== resource.unit && (
            <>, the analysis then converts it to {resource.unit}</>
          )}
          . The small figure under each box is the {slot.block_label.toLowerCase()}{' '}
          consumption that reading opens.
        </p>
      </header>

      <div className="sheet__scroll">
        <table className="sheet__table">
          <caption className="sheet__caption">
            {resource.label} · {slot.label.toLowerCase()} · readings in{' '}
            {resource.entry_unit}, with the consumption each one opens beneath it
            in {resource.unit}.
          </caption>
          <thead>
            <tr>
              <th scope="col" className="sheet__corner">
                Day
              </th>
              {resource.meters.map((meter) => (
                <th key={meter.key} scope="col" className="sheet__meter">
                  {meter.label}
                  {meter.code && <span className="sheet__code">{meter.code}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {resource.days.map((day) => (
              <tr
                key={day.code}
                className={`sheet__row sheet__row--${day.state}`}
                aria-current={day.state === 'today' ? 'date' : undefined}
              >
                <th scope="row" className="sheet__day">
                  <span className="sheet__day-code">{day.code}</span>
                  <span className="sheet__day-date">{day.date}</span>
                </th>

                {resource.meters.map((meter) => {
                  const key = cellKey({
                    resource: resource.key,
                    meter: meter.key,
                    day_index: day.index,
                    slot: slot.key,
                  })
                  const block = derived.get(key)
                  return (
                    <td key={meter.key} className="sheet__cell">
                      <Box
                        label={`${meter.label}, ${day.code}, ${slot.label}`}
                        value={
                          drafts[key] ??
                          (stored.has(key) ? String(stored.get(key)!.value) : '')
                        }
                        bad={block?.status === 'backwards'}
                        future={day.state === 'future'}
                        busy={saving.has(key)}
                        onDraft={(next) => onDraft(key, next)}
                        onCommit={(raw) =>
                          onCommit(
                            key,
                            {
                              resource: resource.key,
                              meter: meter.key,
                              day_index: day.index,
                              slot: slot.key,
                            },
                            raw,
                          )
                        }
                      />
                      <Derived block={block} unit={resource.unit} />
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

/* --- The two pieces every cell is made of -------------------------------- */

interface BoxProps {
  label: string
  value: string
  bad: boolean
  /** A day the mission has not reached. Typeable, but not expected. */
  future: boolean
  busy: boolean
  onDraft: (value: string) => void
  onCommit: (raw: string) => void
}

function Box({ label, value, bad, future, busy, onDraft, onCommit }: BoxProps) {
  return (
    <label className="sheet__box">
      <span className="sheet__box-label">{label}</span>
      <input
        className={
          bad
            ? 'sheet__input sheet__input--bad'
            : future
              ? 'sheet__input sheet__input--future'
              : 'sheet__input'
        }
        type="number"
        inputMode="decimal"
        step="any"
        min="0"
        value={value}
        aria-label={label}
        aria-busy={busy}
        onChange={(event) => onDraft(event.target.value)}
        onBlur={(event) => onCommit(event.target.value)}
        onKeyDown={(event) => {
          // Enter stores without leaving the box, so a crew member checking one
          // figure against the dial does not have to tab away to save it.
          if (event.key === 'Enter') {
            event.preventDefault()
            onCommit((event.target as HTMLInputElement).value)
          }
        }}
      />
    </label>
  )
}

/** What the reading turned out to mean, or which kind of nothing it is. */
function Derived({ block, unit }: { block: BlockUsage | undefined; unit: string }) {
  const status = block?.status ?? 'open'

  return (
    <span className={`sheet__derived sheet__derived--${status}`} title={BLOCK_HINT[status]}>
      {block?.amount !== null && block?.amount !== undefined ? (
        amount(block.amount, unit)
      ) : status === 'backwards' ? (
        <>
          <Warning size={11} />
          {BLOCK_LABEL[status]}
        </>
      ) : status === 'gap' ? (
        BLOCK_LABEL[status]
      ) : (
        ''
      )}
    </span>
  )
}
