/**
 * The crew's hand-read meter round, made editable.
 *
 * Which rooms are sub-metered and which taps have a meter on them is a fact
 * about a habitat's wiring and plumbing. One station meters seven rooms;
 * another meters three and calls the kitchen `2B`. So the round is edited here
 * rather than shipped in the source.
 *
 * Edits are held locally and saved as a whole round, because a round is an
 * ordered walk: "here is the round now" is the only edit that makes sense of
 * reordering. Nothing is written until Save, and Discard puts it back.
 *
 * A meter's id is what readings are keyed by, so renaming keeps its history
 * and removing one hides it rather than deleting what was logged.
 */

import { useEffect, useState } from 'react'

import { Plus, Trash } from '@/icons'
import type { MeterRound, MeterSpec } from '@/lib/types'

interface MeterEditorProps {
  round: MeterRound
  onSave: (resource: 'power' | 'water', meters: MeterSpec[]) => Promise<void>
  onReset: () => void
}

const BLANK: MeterSpec = {
  key: '',
  label: '',
  code: '',
  group: '',
  group_label: '',
  stream: 'none',
}

export function MeterEditor({ round, onSave, onReset }: MeterEditorProps) {
  return (
    <section className="panel">
      <div className="panel__head">
        <h3 className="panel__title">Crew meter log</h3>
        <span className="panel__count">
          {round.power.length + round.water.length} dials
        </span>
      </div>
      <p className="panel__blurb">
        Dials read by hand. Add the ones this habitat has, name them as the
        crew does, remove the rest.{' '}
        {round.customised ? (
          <>
            This round is yours.{' '}
            <button type="button" className="naming__link" onClick={onReset}>
              Restore the default list
            </button>
            .
          </>
        ) : (
          <>Showing the habitat default. Saving makes it yours to edit.</>
        )}
      </p>

      <ResourceEditor
        resource="power"
        heading="Power by room"
        note="One dial per sub-metered room, in kWh."
        meters={round.power}
        onSave={onSave}
      />
      <ResourceEditor
        resource="water"
        heading="Water by tap"
        note="One dial per tap, in m³. The code is stencilled on the pipe. Warm and cold are logged separately: warm water costs power too."
        meters={round.water}
        onSave={onSave}
        showPlumbing
      />
    </section>
  )
}

function ResourceEditor({
  resource,
  heading,
  note,
  meters,
  onSave,
  showPlumbing = false,
}: {
  resource: 'power' | 'water'
  heading: string
  note: string
  meters: MeterSpec[]
  onSave: (resource: 'power' | 'water', meters: MeterSpec[]) => Promise<void>
  showPlumbing?: boolean
}) {
  const [draft, setDraft] = useState<MeterSpec[]>(meters)
  const [saving, setSaving] = useState(false)

  useEffect(() => setDraft(meters), [meters])

  const dirty = JSON.stringify(draft) !== JSON.stringify(meters)

  const update = (index: number, patch: Partial<MeterSpec>) =>
    setDraft((current) =>
      current.map((meter, at) => (at === index ? { ...meter, ...patch } : meter)),
    )

  const save = async () => {
    setSaving(true)
    try {
      await onSave(resource, draft)
    } catch {
      // The page shows the refusal; keep the draft so nothing is lost.
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="naming__round">
      <p className="panel__blurb">
        <strong>{heading}.</strong> {note}
      </p>

      <div className={showPlumbing ? 'meter__head' : 'meter__head meter--power'}>
        <span>Name</span>
        {showPlumbing && <span>Code</span>}
        {showPlumbing && <span>Stream</span>}
        <span>Id</span>
        <span />
      </div>

      {draft.map((meter, index) => (
        <div
          className={showPlumbing ? 'meter' : 'meter meter--power'}
          key={`${meter.key || 'new'}-${index}`}
        >
          <input
            className="meter__field"
            value={meter.label}
            placeholder="Name it as the crew does"
            aria-label={`Name of ${resource} meter ${index + 1}`}
            onChange={(event) => update(index, { label: event.target.value })}
          />

          {showPlumbing && (
            <input
              className="meter__field"
              value={meter.code}
              placeholder="2B"
              aria-label={`Pipe code of meter ${index + 1}`}
              onChange={(event) => update(index, { code: event.target.value })}
            />
          )}

          {showPlumbing && (
            <select
              className="meter__field"
              value={meter.stream}
              aria-label={`Stream of meter ${index + 1}`}
              onChange={(event) =>
                update(index, { stream: event.target.value as MeterSpec['stream'] })
              }
            >
              <option value="none">none</option>
              <option value="warm">warm</option>
              <option value="cold">cold</option>
            </select>
          )}

          <code className="meter__id">{meter.key || 'from the name'}</code>

          <button
            type="button"
            className="naming__icon-button"
            aria-label={`Remove ${meter.label || 'this meter'}`}
            onClick={() => setDraft((current) => current.filter((_, at) => at !== index))}
          >
            <Trash />
          </button>
        </div>
      ))}

      <div className="meter__actions">
        <button
          type="button"
          className="naming__button"
          onClick={() => setDraft((current) => [...current, { ...BLANK }])}
        >
          <Plus /> Add a dial
        </button>

        {dirty && (
          <>
            <button
              type="button"
              className="naming__button naming__button--primary"
              disabled={saving}
              onClick={() => void save()}
            >
              {saving ? 'Saving…' : 'Save this round'}
            </button>
            <button
              type="button"
              className="naming__button"
              onClick={() => setDraft(meters)}
            >
              Discard
            </button>
          </>
        )}
      </div>
    </div>
  )
}
