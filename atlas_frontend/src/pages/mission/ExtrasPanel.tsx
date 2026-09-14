/**
 * The extras: planned consumption the flat daily rate does not cover.
 *
 * An experiment on MD-14, the dishwasher every day, a systems flush before
 * splashdown. They are part of the plan, not a deviation from it, so booking
 * one does not raise the mission's ceiling — it decides where some of the
 * ceiling goes, and every ordinary day drops to pay for it. The panel says
 * that in as many words, because it is the one thing about extras that
 * surprises people, and finding it out by watching the allowance fall is worse
 * than being told.
 *
 * ONE FORM, TWO JOBS. Adding and editing are the same six fields, so the form
 * is written once and opened with a row's values or with none. An editor that
 * looks different from the thing that created the row is an editor people
 * distrust.
 *
 * A one-off is booked by MISSION DAY, not by date. MD-14 is how the protocol
 * says it and how the crew says it; the date is shown beside the field so the
 * two can be checked against each other.
 *
 * Removing asks first. An extra is somebody's afternoon, and undo would be a
 * whole mechanism where a confirm is one line.
 */

import { useCallback, useState } from 'react'

import { Plus, Trash, Warning } from '@/icons'
import { amount, extraWhen } from '@/lib/mission'
import { dateOfMissionDay } from '@/lib/missionDates'
import type { ExtraEntry, ExtraKind, ExtraWrite, MissionWindow } from '@/lib/types'

interface ExtrasPanelProps {
  resourceKey: string
  resourceLabel: string
  unit: string
  extras: ExtraEntry[]
  mission: MissionWindow
  saving: boolean
  error: string | null
  onAdd: (extra: ExtraWrite) => Promise<boolean>
  onEdit: (id: string, extra: ExtraWrite) => Promise<boolean>
  onRemove: (id: string) => Promise<boolean>
}

export function ExtrasPanel({
  resourceKey,
  resourceLabel,
  unit,
  extras,
  mission,
  saving,
  error,
  onAdd,
  onEdit,
  onRemove,
}: ExtrasPanelProps) {
  const [adding, setAdding] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [confirmingId, setConfirmingId] = useState<string | null>(null)

  const booked = extras.reduce(
    (total, extra) =>
      total + extra.amount * (extra.kind === 'daily' ? (mission.days ?? 0) : 1),
    0,
  )

  const close = useCallback(() => {
    setAdding(false)
    setEditingId(null)
  }, [])

  return (
    <section className="extras">
      <header className="extras__head">
        <div>
          <h4 className="extras__title">Extras</h4>
          <p className="extras__lede">
            Consumption you know about in advance. Booking one takes it out of
            the mission's ceiling and puts it on the day it happens, so every
            other day's allowance drops to pay for it. The total never moves.
          </p>
        </div>

        <button
          type="button"
          className="button"
          onClick={() => {
            setEditingId(null)
            setAdding((open) => !open)
          }}
          disabled={saving}
          aria-expanded={adding}
        >
          <Plus />
          <span className="button__label">{adding ? 'Cancel' : 'Add an extra'}</span>
        </button>
      </header>

      {adding && (
        <ExtraForm
          resourceKey={resourceKey}
          resourceLabel={resourceLabel}
          unit={unit}
          mission={mission}
          saving={saving}
          error={error}
          onSubmit={async (extra) => {
            const done = await onAdd(extra)
            if (done) close()
            return done
          }}
          onCancel={close}
        />
      )}

      {extras.length === 0 && !adding ? (
        <p className="extras__empty">
          Nothing booked, so every mission day gets the same flat allowance.
        </p>
      ) : (
        <ul className="extras__list">
          {extras.map((extra) =>
            editingId === extra.id ? (
              <li key={extra.id} className="extras__item extras__item--editing">
                <ExtraForm
                  resourceKey={resourceKey}
                  resourceLabel={resourceLabel}
                  unit={unit}
                  mission={mission}
                  saving={saving}
                  error={error}
                  initial={extra}
                  onSubmit={async (changed) => {
                    const done = await onEdit(extra.id, changed)
                    if (done) close()
                    return done
                  }}
                  onCancel={close}
                />
              </li>
            ) : (
              <li key={extra.id} className="extras__item">
                <div className="extras__when">
                  <span
                    className={
                      extra.stranded
                        ? 'extras__code extras__code--stranded'
                        : 'extras__code'
                    }
                  >
                    {extraWhen(extra)}
                  </span>
                  {extra.stranded && (
                    <span className="extras__stranded" title="Outside the mission's dates">
                      <Warning size={12} />
                      budgets nothing
                    </span>
                  )}
                </div>

                <div className="extras__body">
                  <span className="extras__label">{extra.label}</span>
                  {extra.note && <span className="extras__note">{extra.note}</span>}
                </div>

                <span className="extras__amount">
                  {amount(extra.amount, unit)}
                  {extra.kind === 'daily' && (
                    <span className="extras__per"> / day</span>
                  )}
                </span>

                <div className="extras__actions">
                  {confirmingId === extra.id ? (
                    <>
                      <button
                        type="button"
                        className="link-button link-button--danger"
                        onClick={() => void onRemove(extra.id).then(() => setConfirmingId(null))}
                        disabled={saving}
                      >
                        Remove it
                      </button>
                      <button
                        type="button"
                        className="link-button"
                        onClick={() => setConfirmingId(null)}
                        disabled={saving}
                      >
                        Keep
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        className="link-button"
                        onClick={() => {
                          setAdding(false)
                          setEditingId(extra.id)
                        }}
                        disabled={saving}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="icon-button"
                        onClick={() => setConfirmingId(extra.id)}
                        disabled={saving}
                        aria-label={`Remove ${extra.label}`}
                        title={`Remove ${extra.label}`}
                      >
                        <Trash />
                      </button>
                    </>
                  )}
                </div>
              </li>
            ),
          )}
        </ul>
      )}

      {extras.length > 0 && (
        <p className="extras__total">
          {amount(booked, unit)} of the mission's {resourceLabel.toLowerCase()} is
          booked to extras, leaving the rest to be spread over the ordinary days.
        </p>
      )}
    </section>
  )
}

/* --- the form ------------------------------------------------------------ */

interface ExtraFormProps {
  resourceKey: string
  resourceLabel: string
  unit: string
  mission: MissionWindow
  saving: boolean
  error: string | null
  initial?: ExtraEntry
  onSubmit: (extra: ExtraWrite) => Promise<boolean>
  onCancel: () => void
}

function ExtraForm({
  resourceKey,
  resourceLabel,
  unit,
  mission,
  saving,
  error,
  initial,
  onSubmit,
  onCancel,
}: ExtraFormProps) {
  const [label, setLabel] = useState(initial?.label ?? '')
  const [value, setValue] = useState(initial ? String(initial.amount) : '')
  const [kind, setKind] = useState<ExtraKind>(initial?.kind ?? 'once')
  const [day, setDay] = useState(
    String(initial?.mission_day ?? mission.day_index ?? 1),
  )
  const [note, setNote] = useState(initial?.note ?? '')
  const [localError, setLocalError] = useState<string | null>(null)

  const dayNumber = Number(day)
  const dateOfDay = dateOfMissionDay(mission.start, dayNumber, mission.days)

  const submit = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault()

      if (!label.trim()) {
        setLocalError(
          'Give it a name. A column of numbers with no names on it is a plan ' +
            'nobody can audit two weeks later.',
        )
        return
      }
      const parsed = Number(value)
      if (!value.trim() || !Number.isFinite(parsed)) {
        setLocalError(`How much ${resourceLabel.toLowerCase()} does it take?`)
        return
      }
      if (kind === 'once' && !Number.isInteger(dayNumber)) {
        setLocalError('Pick the mission day it happens on.')
        return
      }

      await onSubmit({
        resource: resourceKey,
        label: label.trim(),
        amount: parsed,
        kind,
        mission_day: kind === 'once' ? dayNumber : null,
        note: note.trim(),
      })
    },
    [dayNumber, kind, label, note, onSubmit, resourceKey, resourceLabel, value],
  )

  const complaint = localError ?? error

  return (
    <form className="extra-form" onSubmit={submit}>
      <label className="extra-form__field extra-form__field--grow">
        <span className="setup__label">What is it</span>
        <input
          className="plan__input"
          value={label}
          onChange={(event) => {
            setLabel(event.target.value)
            setLocalError(null)
          }}
          placeholder="e.g. Algae growth run"
          disabled={saving}
        />
      </label>

      <label className="extra-form__field">
        <span className="setup__label">Amount{unit && ` (${unit})`}</span>
        <input
          className="plan__input"
          type="number"
          min="0"
          step="any"
          inputMode="decimal"
          value={value}
          onChange={(event) => {
            setValue(event.target.value)
            setLocalError(null)
          }}
          disabled={saving}
        />
      </label>

      <label className="extra-form__field">
        <span className="setup__label">How often</span>
        <select
          className="plan__input"
          value={kind}
          onChange={(event) => setKind(event.target.value as ExtraKind)}
          disabled={saving}
        >
          <option value="once">Once, on one day</option>
          <option value="daily">Every mission day</option>
        </select>
      </label>

      {kind === 'once' && (
        <label className="extra-form__field">
          <span className="setup__label">Mission day</span>
          <span className="setup__control">
            MD-
            <input
              className="plan__input plan__input--narrow"
              type="number"
              min="1"
              max={mission.days ?? 400}
              step="1"
              value={day}
              onChange={(event) => setDay(event.target.value)}
              disabled={saving}
            />
          </span>
          <span className="setup__note">{dateOfDay ?? 'outside the mission'}</span>
        </label>
      )}

      <label className="extra-form__field extra-form__field--grow">
        <span className="setup__label">Note</span>
        <input
          className="plan__input"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Optional: why, or who asked for it"
          disabled={saving}
        />
      </label>

      {complaint && (
        <p className="plan__error extra-form__error" role="alert">
          <Warning size={13} />
          {complaint}
        </p>
      )}

      <div className="extra-form__actions">
        <button type="submit" className="button button--primary" disabled={saving}>
          <span className="button__label">
            {saving ? 'Saving' : initial ? 'Save changes' : 'Book it'}
          </span>
        </button>
        <button type="button" className="button" onClick={onCancel} disabled={saving}>
          <span className="button__label">Cancel</span>
        </button>
      </div>
    </form>
  )
}
