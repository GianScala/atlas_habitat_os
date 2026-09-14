/**
 * One group of renameable things.
 *
 * The database's spelling on the left in mono, an arrow, and an editable name
 * on the right in the body face. That contrast is the whole idea of the page:
 * the left is the tag a query matches and never changes, the right is what the
 * crew reads.
 *
 * A name is saved on blur or Enter rather than per keystroke. A rename is a
 * decision, not a live filter, and one request per letter would be silly.
 * Clearing the box restores whatever it was called before.
 */

import { useEffect, useMemo, useState } from 'react'

import type { LabelEntry } from '@/lib/types'

interface LabelTableProps {
  title: string
  blurb: string
  entries: LabelEntry[]
  onRename: (key: string, label: string) => void
  /** Show which measurements report a location. */
  showSeenIn?: boolean
  /** Offer a filter box once a list is long enough to need one. */
  filterFrom?: number
}

export function LabelTable({
  title,
  blurb,
  entries,
  onRename,
  showSeenIn = false,
  filterFrom = 8,
}: LabelTableProps) {
  const [query, setQuery] = useState('')

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return entries
    return entries.filter(
      (entry) =>
        entry.key.toLowerCase().includes(needle) ||
        entry.label.toLowerCase().includes(needle),
    )
  }, [entries, query])

  if (entries.length === 0) return null

  return (
    <section className="panel">
      <div className="panel__head">
        <h3 className="panel__title">{title}</h3>
        <span className="panel__count">{entries.length}</span>
      </div>

      <p className="panel__blurb">{blurb}</p>

      <div className="panel__body">
        {entries.length >= filterFrom && (
          <div className="filter" style={{ padding: '0 var(--space-4)' }}>
            <input
              className="filter__input"
              value={query}
              placeholder="Filter"
              aria-label={`Filter ${title.toLowerCase()}`}
              onChange={(event) => setQuery(event.target.value)}
            />
            {query && (
              <span className="filter__count">
                {shown.length} of {entries.length}
              </span>
            )}
          </div>
        )}

        {shown.map((entry) => (
          <LabelRow
            key={entry.key}
            entry={entry}
            onRename={onRename}
            showSeenIn={showSeenIn}
          />
        ))}

        {shown.length === 0 && (
          <p className="panel__blurb" style={{ paddingBottom: 'var(--space-3)' }}>
            Nothing matches {query}.
          </p>
        )}
      </div>
    </section>
  )
}

function LabelRow({
  entry,
  onRename,
  showSeenIn,
}: {
  entry: LabelEntry
  onRename: (key: string, label: string) => void
  showSeenIn: boolean
}) {
  const [draft, setDraft] = useState(entry.label)

  // Re-sync when the server answers. It is the source of truth for what a
  // thing is now called, including after a clear restored an older name.
  useEffect(() => setDraft(entry.label), [entry.label])

  const own = entry.source === 'crew'

  const commit = () => {
    if (draft.trim() === entry.label) return
    onRename(entry.key, draft.trim())
  }

  return (
    <div className="entry">
      <div className="entry__key">
        <code className="entry__code">{entry.key}</code>
        {showSeenIn && entry.seen_in.length > 0 && (
          <span className="entry__meta">{entry.seen_in.join(', ')}</span>
        )}
      </div>

      <span className="entry__arrow" aria-hidden="true">
        &rarr;
      </span>

      <input
        className={own ? 'entry__input entry__input--own' : 'entry__input'}
        value={draft}
        aria-label={`Display name for ${entry.key}`}
        placeholder={entry.key}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === 'Enter') event.currentTarget.blur()
          if (event.key === 'Escape') setDraft(entry.label)
        }}
      />

      <span className={own ? 'entry__badge entry__badge--own' : 'entry__badge'}>
        {own ? 'yours' : entry.source === 'profile' ? 'profile' : ''}
      </span>
    </div>
  )
}
