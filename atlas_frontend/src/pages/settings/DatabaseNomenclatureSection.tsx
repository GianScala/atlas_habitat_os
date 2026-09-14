/**
 * The nomenclature half of Settings: what the database calls things, and what
 * this crew should read instead.
 *
 * A habitat's database speaks whatever vocabulary its engineers chose. One
 * station tags the sleeping quarters `Container3`, another `2B`, another
 * `crew_room`. None is wrong, and none is what a crew wants to read on a chart.
 *
 * So this separates the two. The left column of each table is what the DATABASE
 * says, read live from it — which is also the point of showing it, since it is
 * the only place in the interface that answers "what is actually in there". The
 * right column is what the INTERFACE shows. Renaming touches only the right: the
 * habitat database is read-only and every query still matches the real tag.
 *
 * The meter round below is the same idea for the dials the crew reads by hand.
 * Which rooms and taps a habitat sub-meters is a fact about its plumbing, so the
 * round is editable rather than shipped — add one, rename one, remove one.
 * Readings are keyed by a meter's id, so a rename keeps its history.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'

import { ErrorBanner } from '@/components/ErrorBanner'
import { NoSignal } from '@/icons'
import {
  fetchLabels,
  fetchMeterRound,
  resetMeterRound,
  saveMeterRound,
  setLabel,
} from '@/lib/api'
import type { LabelCatalogue, MeterRound, MeterSpec } from '@/lib/types'

import { LabelTable } from './LabelTable'
import { MeterEditor } from './MeterEditor'

export function DatabaseNomenclatureSection() {
  const [labels, setLabels] = useState<LabelCatalogue | null>(null)
  const [round, setRound] = useState<MeterRound | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    try {
      const [catalogue, meters] = await Promise.all([
        fetchLabels(signal),
        fetchMeterRound(signal),
      ])
      setLabels(catalogue)
      setRound(meters)
      setError(null)
    } catch (cause) {
      if ((cause as Error)?.name === 'AbortError') return
      setError((cause as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal)
    return () => controller.abort()
  }, [load])

  const renamed = useMemo(
    () =>
      [...(labels?.locations ?? []), ...(labels?.measurements ?? [])].filter(
        (entry) => entry.source === 'crew',
      ).length,
    [labels],
  )

  const rename = useCallback(
    async (kind: 'location' | 'measurement', key: string, label: string) => {
      try {
        setLabels(await setLabel(kind, key, label))
        setError(null)
      } catch (cause) {
        setError((cause as Error).message)
      }
    },
    [],
  )

  const saveRound = useCallback(
    async (resource: 'power' | 'water', meters: MeterSpec[]) => {
      try {
        setRound(await saveMeterRound(resource, meters))
        setError(null)
      } catch (cause) {
        setError((cause as Error).message)
        throw cause
      }
    },
    [],
  )

  const restoreRound = useCallback(async () => {
    try {
      setRound(await resetMeterRound())
      setError(null)
    } catch (cause) {
      setError((cause as Error).message)
    }
  }, [])

  return (
    <div className="naming">
      {/* The switch above already says what this half is for, so this adds
          only the part a reader needs reassuring about: nothing here writes. */}
      <p className="naming__intro">
        Read only. Renaming changes what you see, never your data.
        Answers still cite the real tag.
      </p>

      {error && <ErrorBanner message={error} kind="request" />}
      {loading && <p className="dashboard__status">Reading the database…</p>}

      {/* Nothing loaded is a state, not a failure. An empty table would read as
          a habitat with no sensors, which is a different and wrong claim. */}
      {labels && !labels.connected && (
        <div className="panel">
          <div className="empty">
            <NoSignal size={26} className="empty__mark" />
            <p className="empty__title">No database loaded</p>
            <p className="empty__detail">{labels.detail}</p>
            <p className="empty__detail">
              Set <code>DATA_SOURCE</code> and its credentials in{' '}
              <code>.env</code>. Your rooms and datasets appear here to rename.
            </p>
          </div>
        </div>
      )}

      {labels?.connected && (
        <>
          <div className="stats">
            <div className="stat">
              <span className="stat__value">{labels.locations.length}</span>
              <span className="stat__label">Locations</span>
            </div>
            <div className="stat">
              <span className="stat__value">{labels.measurements.length}</span>
              <span className="stat__label">Datasets</span>
            </div>
            <div className="stat">
              <span className="stat__value">{renamed}</span>
              <span className="stat__label">Renamed by you</span>
            </div>
            <div className="stat stat--wide">
              <span className="stat__value">{labels.source}</span>
              <span className="stat__label">Loaded from</span>
            </div>
          </div>

          <LabelTable
            title="Rooms and locations"
            blurb="Every place tag in your database. A new name shows on charts, in answers, and on the mission page."
            entries={labels.locations}
            onRename={(key, label) => rename('location', key, label)}
            showSeenIn
          />

          <LabelTable
            title="Datasets"
            blurb="The measurements your database holds, read just now. This is everything ATLAS can see."
            entries={labels.measurements}
            onRename={(key, label) => rename('measurement', key, label)}
          />
        </>
      )}

      {round && (
        <MeterEditor round={round} onSave={saveRound} onReset={restoreRound} />
      )}
    </div>
  )
}
