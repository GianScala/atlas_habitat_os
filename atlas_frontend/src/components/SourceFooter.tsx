/**
 * The queries behind an answer.
 *
 * Separate from the trace on purpose: the trace is the narrative of what was
 * tried, this is the citation. Each line is the query the active adapter
 * actually ran, in that adapter's own dialect, so anyone doubting a number can
 * run it against the habitat database and get the same result. The dialect is
 * not named here: it depends on which adapter is configured, and the query
 * text shows it plainly.
 */

import { ChevronRight } from '@/icons'

interface SourceFooterProps {
  queries: string[]
}

export function SourceFooter({ queries }: SourceFooterProps) {
  if (queries.length === 0) return null

  const noun = queries.length === 1 ? 'query' : 'queries'

  return (
    <details className="panel">
      <summary className="panel__summary">
        <ChevronRight className="panel__chevron" />
        <span className="panel__label">
          Source: {queries.length} {noun}
        </span>
        <span className="panel__hint">verifiable</span>
      </summary>

      <div className="panel__body">
        <div className="sources">
          {queries.map((query) => (
            <code key={query} className="sources__query">
              {query}
            </code>
          ))}
        </div>
      </div>
    </details>
  )
}
