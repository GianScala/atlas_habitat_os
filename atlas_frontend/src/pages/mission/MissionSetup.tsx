/**
 * Where a mission is declared: three facts, and everything else follows.
 *
 * Start date, length in days, and the most of each resource the whole mission
 * may draw. Nothing else is asked for, because nothing else has to be — a
 * day's allowance, a cycle's, and what is left are arithmetic on those three,
 * and arithmetic a crew does by hand is arithmetic that goes wrong at 02:00 on
 * day nineteen.
 *
 * THE CEILINGS ARE OFFERED, NOT ASSUMED. Typing a length fills the two ceiling
 * boxes with this habitat's shipped daily figures multiplied out. That is a
 * suggestion sitting visibly in a field the crew can overwrite before saving —
 * not a default applied behind their back — and the note under it says where
 * the number came from.
 *
 * The end date is shown as it is derived rather than entered. Two date fields
 * can contradict each other and one cannot, and "30 days" is how a mission is
 * actually described.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'

import { Warning } from '@/icons'
import { endOfMission } from '@/lib/missionDates'
import type { MissionPlan, PlanUpdate } from '@/lib/types'

interface MissionSetupProps {
  plan: MissionPlan
  saving: boolean
  error: string | null
  onSave: (change: PlanUpdate) => Promise<boolean>
  /** Absent while no mission exists — there is nothing to go back to. */
  onCancel?: () => void
}

export function MissionSetup({
  plan,
  saving,
  error,
  onSave,
  onCancel,
}: MissionSetupProps) {
  const declared = plan.mission.is_declared

  const [name, setName] = useState(plan.mission.name)
  const [start, setStart] = useState(plan.mission.start ?? plan.mission.today)
  const [days, setDays] = useState(String(plan.mission.days ?? 30))
  const [totals, setTotals] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      plan.resources.map((resource) => [
        resource.key,
        resource.total === null ? '' : String(resource.total),
      ]),
    ),
  )
  /** Which ceiling boxes the crew has typed in, and so must not be refilled. */
  const [touched, setTouched] = useState<Record<string, boolean>>({})
  const [localError, setLocalError] = useState<string | null>(null)

  const length = Number(days)
  const end = useMemo(() => endOfMission(start, length), [start, length])

  // The suggestion follows the length while the box is untouched. A crew that
  // types 30 and then 60 should see the ceiling double, because that is what
  // doubling the mission means; one that typed their own figure keeps it.
  useEffect(() => {
    if (!Number.isFinite(length) || length < 1) return
    setTotals((current) => {
      const next = { ...current }
      for (const resource of plan.resources) {
        if (touched[resource.key]) continue
        if (declared && resource.total !== null) continue
        const daily = resource.suggested_daily
        if (daily === null) continue
        next[resource.key] = String(Math.round(daily * length))
      }
      return next
    })
  }, [length, plan.resources, touched, declared])

  const setTotal = useCallback((key: string, value: string) => {
    setTouched((current) => ({ ...current, [key]: true }))
    setTotals((current) => ({ ...current, [key]: value }))
    setLocalError(null)
  }, [])

  const submit = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault()

      if (!start) {
        setLocalError('Choose the mission start date.')
        return
      }
      if (!Number.isInteger(length) || length < 1) {
        setLocalError(
          'The mission runs for a whole number of days. That is what MD-01 ' +
            'to MD-NN counts.',
        )
        return
      }

      const checked: Record<string, number | null> = {}
      for (const resource of plan.resources) {
        const raw = (totals[resource.key] ?? '').trim()
        if (raw === '') {
          // An empty box is "we are not capping this one", which is a
          // decision, and the backend stores it as one.
          checked[resource.key] = null
          continue
        }
        const parsed = Number(raw)
        if (!Number.isFinite(parsed)) {
          setLocalError(`The ${resource.label.toLowerCase()} ceiling is not a number: ${raw}`)
          return
        }
        checked[resource.key] = parsed
      }

      await onSave({ name: name.trim(), start, days: length, totals: checked })
    },
    [length, name, onSave, plan.resources, start, totals],
  )

  const complaint = localError ?? error

  return (
    <form className="setup" onSubmit={submit}>
      <header className="setup__head">
        <h2 className="setup__title">
          {declared ? 'Change the mission' : 'Add a mission plan'}
        </h2>
        <p className="setup__lede">
          Set the start date, duration, and total budget for each resource.
          ATLAS calculates a daily allowance and updates what remains as
          sensor readings arrive.
        </p>
      </header>

      <div className="setup__fields">
        <label className="setup__field setup__field--wide">
          <span className="setup__label">Mission name</span>
          <input
            className="plan__input"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="e.g. Mission VII"
            disabled={saving}
          />
          <span className="setup__note">Optional. What the crew calls it.</span>
        </label>

        <label className="setup__field">
          <span className="setup__label">First day, MD-01</span>
          <input
            className="plan__input"
            type="date"
            value={start}
            onChange={(event) => setStart(event.target.value)}
            disabled={saving}
            required
          />
          <span className="setup__note">
            Three-day cycles are counted from here, so cycle 1 is MD-01 to MD-03.
          </span>
        </label>

        <label className="setup__field">
          <span className="setup__label">Length</span>
          <span className="setup__control">
            <input
              className="plan__input plan__input--narrow"
              type="number"
              min="1"
              max="400"
              step="1"
              value={days}
              onChange={(event) => setDays(event.target.value)}
              disabled={saving}
              required
            />
            days
          </span>
          <span className="setup__note">
            {end
              ? `Ends ${end}. MD-01 to MD-${String(length).padStart(2, '0')}.`
              : 'The last day is worked out from these two.'}
          </span>
        </label>
      </div>

      <div className="setup__ceilings">
        <h3 className="setup__subtitle">Maximum use over the whole mission</h3>
        <p className="setup__lede">
          Not a daily figure. The total for the entire mission. The daily
          allowance is derived from it, drops when you book an extra, and is
          re-derived from what has actually been drawn every time this page is
          read.
        </p>

        {plan.resources.map((resource) => (
          <label key={resource.key} className="setup__field setup__field--wide">
            <span className="setup__label">
              {resource.label}
              {resource.unit && <span className="plan__unit">{resource.unit}</span>}
            </span>
            <input
              className="plan__input"
              type="number"
              min="0"
              step="any"
              inputMode="decimal"
              value={totals[resource.key] ?? ''}
              onChange={(event) => setTotal(resource.key, event.target.value)}
              placeholder="no ceiling"
              disabled={saving}
            />
            <span className="setup__note">
              {resource.suggested_daily !== null && !touched[resource.key] ? (
                <>
                  Offered: {resource.suggested_daily} {resource.unit} a day across{' '}
                  {length || 'n'} days, from what this habitat drew before the
                  mission. Overwrite it: a starting point for an argument,
                  not a plan.
                </>
              ) : (
                <>
                  Leave empty to track this resource without capping it.
                  {length > 0 && (totals[resource.key] ?? '').trim() !== ''
                    ? ` That is about ${Math.round(
                        Number(totals[resource.key]) / length,
                      )} ${resource.unit} a day before extras.`
                    : ''}
                </>
              )}
            </span>
          </label>
        ))}
      </div>

      {complaint && (
        <p className="plan__error" role="alert">
          <Warning size={13} />
          {complaint}
        </p>
      )}

      <div className="plan__actions">
        <button type="submit" className="button button--primary" disabled={saving}>
          <span className="button__label">
            {saving ? 'Saving' : declared ? 'Save mission' : 'Start the mission plan'}
          </span>
        </button>
        {onCancel && (
          <button type="button" className="button" onClick={onCancel} disabled={saving}>
            <span className="button__label">Cancel</span>
          </button>
        )}
      </div>
    </form>
  )
}
