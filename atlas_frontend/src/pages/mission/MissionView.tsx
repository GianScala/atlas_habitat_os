/**
 * The mission plan view.
 *
 * The dashboard's other two views report what the habitat did. This one
 * reports it against what the crew said it would do, which is the only page
 * here carrying a number no sensor produced. Everything on it is arranged
 * around keeping that distinction visible: a ceiling is labelled with who
 * decided it, and a figure that came from the shipped defaults rather than
 * from the crew says so wherever it appears.
 *
 * WITH NO MISSION DECLARED there is nothing to measure against, and the page
 * says so rather than drawing empty rings. The setup form takes its place —
 * not behind a button, because a page whose entire content is a sentence
 * explaining why it is empty has room for the form that fills it.
 *
 * With one declared, per resource: three rings — today, this cycle, the whole
 * mission — then the day-by-day plan, then the extras. The rings answer "where
 * are we now"; the day plan answers "and what does that do to the days left",
 * which no single window can show; the extras are where that gets changed.
 */

import { useCallback, useState } from 'react'

import { ChevronRight, Refresh, Warning } from '@/icons'
import { useMission } from '@/hooks/useMission'
import { amount, forwardReading, missionPosition, unitOf } from '@/lib/mission'
import type { ExtraWrite, MissionWindow, ResourceTracking } from '@/lib/types'

import { BudgetCard } from './BudgetCard'
import { DayPlanChart } from './DayPlanChart'
import { DayPlanTable } from './DayPlanTable'
import { ExtrasPanel } from './ExtrasPanel'
import { MissionSetup } from './MissionSetup'

export function MissionView() {
  const [editing, setEditing] = useState(false)

  const {
    tracking,
    plan,
    loading,
    refreshing,
    error,
    saveError,
    saving,
    refresh,
    save,
    reset,
    createExtra,
    editExtra,
    removeExtra,
  } = useMission()

  const onSave = useCallback(
    async (change: Parameters<typeof save>[0]) => {
      const done = await save(change)
      if (done) setEditing(false)
      return done
    },
    [save],
  )

  if (loading) {
    return <p className="dashboard__status">Loading the mission plan…</p>
  }

  if (error && !tracking) {
    return (
      <div className="error" role="alert">
        <div className="error__body">
          <div className="error__title">Could not load the mission plan</div>
          <div>{error}</div>
        </div>
      </div>
    )
  }

  if (!tracking) return null

  const mission = tracking.mission

  // No mission, no arithmetic. The form is the page.
  if (!mission.is_declared) {
    return (
      <div className="mission">
        <div className="mission__banner">
          <Warning size={15} />
          <div>
            <p className="mission__banner-title">
              Add a mission plan to track your budget
            </p>
            <p className="mission__banner-text">
              Set your mission dates and resource budgets below to compare daily
              consumption with your plan.
            </p>
          </div>
        </div>

        {plan && (
          <MissionSetup
            plan={plan}
            saving={saving}
            error={saveError}
            onSave={onSave}
          />
        )}
      </div>
    )
  }

  return (
    <div className="mission" aria-busy={refreshing}>
      <div className="mission__bar">
        <dl className="readout">
          <Readout
            label="Mission"
            value={mission.name || 'Unnamed'}
            title={`${mission.start} to ${mission.end}`}
          />
          <Readout
            label="Where we are"
            value={missionPosition(mission)}
            title="Mission days are counted from MD-01, the first day."
          />
          <Readout
            label="Cycle"
            value={
              mission.cycle_number === null
                ? ''
                : `${mission.cycle_number} · MD-${pad(mission.cycle_first)}–${pad(
                    mission.cycle_last,
                  )}`
            }
            title="Three-day cycles, counted from MD-01."
          />
          <Readout
            label="Days left"
            value={String(mission.days_remaining ?? '')}
            title="Including today."
          />
          <Readout
            label="Day starts"
            value={tracking.day_start_label}
            title={
              'Which midnight a mission day is measured from. Every window on ' +
              'this page opens and closes on it.'
            }
          />
          <Readout
            label="Read at"
            value={new Date(tracking.generated_at).toLocaleTimeString(undefined, {
              hour: '2-digit',
              minute: '2-digit',
            })}
            title="When these figures were measured."
          />
        </dl>

        <div className="mission__actions">
          <button
            type="button"
            className="button"
            onClick={refresh}
            disabled={refreshing}
            title="Re-read the meters and re-plan the days ahead"
          >
            <Refresh />
            <span className="button__label">{refreshing ? 'Reading' : 'Refresh'}</span>
          </button>

          <button
            type="button"
            className={editing ? 'button' : 'button button--primary'}
            onClick={() => setEditing((open) => !open)}
            aria-expanded={editing}
          >
            <span className="button__label">
              {editing ? 'Close' : 'Edit mission'}
            </span>
          </button>
        </div>
      </div>

      {/* Said once, at the top, rather than on six cards: until the crew has
          set a ceiling, every percentage on this page is measured against one
          we picked. */}
      {tracking.plan_is_all_default && !editing && (
        <div className="mission__banner">
          <Warning size={15} />
          <div>
            <p className="mission__banner-title">
              Review the suggested budgets
            </p>
            <p className="mission__banner-text">{tracking.default_note}</p>
          </div>
          <button
            type="button"
            className="button button--primary"
            onClick={() => setEditing(true)}
          >
            <span className="button__label">Set them</span>
          </button>
        </div>
      )}

      {tracking.warnings.map((warning) => (
        <div key={warning} className="mission__warning">
          <Warning size={13} />
          <span>{warning}</span>
        </div>
      ))}

      {editing && plan && (
        <MissionSetup
          plan={plan}
          saving={saving}
          error={saveError}
          onSave={onSave}
          onCancel={() => setEditing(false)}
        />
      )}

      {/* A failed re-read does not delete the last good one. */}
      {error && (
        <div className="error" role="alert">
          <div className="error__body">
            <div className="error__title">Could not re-read the meters</div>
            <div>{error}</div>
            <div className="error__aside">
              The figures below are the last reading that did arrive, taken at{' '}
              {new Date(tracking.generated_at).toLocaleTimeString()}.
            </div>
          </div>
        </div>
      )}

      <div className="mission__resources">
        {tracking.resources.map((resource) => (
          <ResourceSection
            key={resource.key}
            resource={resource}
            mission={mission}
            saving={saving}
            error={saveError}
            onAdd={createExtra}
            onEdit={editExtra}
            onRemove={removeExtra}
          />
        ))}
      </div>

      {plan && !plan.is_all_default && (
        <p className="mission__reset">
          <button
            type="button"
            className="link-button"
            onClick={() => void reset()}
            disabled={saving}
            title="Forget the mission, every ceiling, and every extra"
          >
            Clear the mission plan
          </button>
        </p>
      )}
    </div>
  )
}

function pad(value: number | null): string {
  return value === null ? '' : String(value).padStart(2, '0')
}

function Readout({
  label,
  value,
  title,
}: {
  label: string
  value: string
  title?: string
}) {
  return (
    <div className="readout__item" title={title}>
      <dt className="readout__key">{label}</dt>
      <dd className="readout__value">{value}</dd>
    </div>
  )
}

interface ResourceSectionProps {
  resource: ResourceTracking
  mission: MissionWindow
  saving: boolean
  error: string | null
  onAdd: (extra: ExtraWrite) => Promise<boolean>
  onEdit: (id: string, extra: ExtraWrite) => Promise<boolean>
  onRemove: (id: string) => Promise<boolean>
}

function ResourceSection({
  resource,
  mission,
  saving,
  error,
  onAdd,
  onEdit,
  onRemove,
}: ResourceSectionProps) {
  const unit = unitOf(resource)
  const isDefault = resource.total !== null && resource.source === 'default'
  const forward = forwardReading(resource, unit)

  return (
    <section className="dashboard__group">
      <h2 className="dashboard__group-title">
        {resource.label}
        {unit && <span className="card__unit">{unit}</span>}
      </h2>

      {resource.error ? (
        <div className="card">
          <div className="card__state card__state--error" role="alert">
            <Warning size={20} />
            <p className="card__state-title">This resource could not be read</p>
            <p className="card__state-text">{resource.error}</p>
          </div>
        </div>
      ) : (
        <>
          {/* The one number on this page a crew can act on, above the ones
              that explain it. */}
          {forward && (
            <p
              className={
                resource.feasible
                  ? 'mission__forward'
                  : 'mission__forward mission__forward--bad'
              }
            >
              {!resource.feasible && <Warning size={14} />}
              {forward}
            </p>
          )}

          <div className="dashboard__grid">
            {resource.budgets.map((budget) => (
              <BudgetCard
                key={budget.horizon}
                budget={budget}
                unit={unit}
                isDefault={isDefault}
              />
            ))}
          </div>

          <section className="card mission__history">
            <header className="card__head">
              <div className="card__heading">
                <h3 className="card__title">Day by day</h3>
                <span className="card__unit">
                  MD-01 to MD-{pad(mission.days)}
                </span>
              </div>
              <p className="card__subtitle">
                Daily {resource.label.toLowerCase()} use compared with your allowance.
                Missing sensor data leaves a gap; today is still in progress.
                {resource.total !== null && (
                  <>
                    {' '}
                    {amount(resource.consumed, unit)} of{' '}
                    {amount(resource.total, unit)} drawn so far.
                  </>
                )}
              </p>
            </header>

            <DayPlanChart days={resource.days} unit={unit} />

            {resource.notes.map((note) => (
              <p key={note} className="card__note">
                {note}
              </p>
            ))}
          </section>

          <details className="panel">
            <summary className="panel__summary">
              <ChevronRight className="panel__chevron" />
              <span className="panel__label">Every day</span>
              <span className="panel__hint">
                exact daily use, planned allowance, and revised allowance
              </span>
            </summary>
            <div className="panel__body">
              <DayPlanTable days={resource.days} unit={unit} />
            </div>
          </details>

          <ExtrasPanel
            resourceKey={resource.key}
            resourceLabel={resource.label}
            unit={unit}
            extras={resource.extras}
            mission={mission}
            saving={saving}
            error={error}
            onAdd={onAdd}
            onEdit={onEdit}
            onRemove={onRemove}
          />

          {resource.query && (
            <details className="panel">
              <summary className="panel__summary">
                <ChevronRight className="panel__chevron" />
                <span className="panel__label">Source</span>
                <span className="panel__hint">
                  {resource.measurement}.{resource.field}, the query behind these consumption figures
                </span>
              </summary>
              <div className="panel__body">
                <code className="sources__query">{resource.query}</code>
              </div>
            </details>
          )}
        </>
      )}
    </section>
  )
}
