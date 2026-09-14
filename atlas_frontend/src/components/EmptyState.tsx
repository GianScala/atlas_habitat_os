/**
 * The opening screen.
 *
 * Its job is to set expectations — read-only, grounded, cited — and to hand
 * over four questions that between them exercise the whole tool surface, so a
 * first-time user finds out what the thing can do by clicking rather than
 * guessing.
 */

import type { Suggestion } from '@/lib/types'

interface EmptyStateProps {
  suggestions: Suggestion[]
  disabled: boolean
  onPick: (question: string) => void
}

export function EmptyState({ suggestions, disabled, onPick }: EmptyStateProps) {
  return (
    <div className="assistant-empty">
      <header className="assistant-empty__intro">
        <h1 className="assistant-empty__title">Ask ATLAS </h1>
        <p className="assistant-empty__blurb">
          Ask a question in plain English. ATLAS reads your telemetry, explains
          what it finds, and cites every source without changing habitat data.
        </p>
        <div className="assistant-empty__principles" aria-label="Assistant safeguards">
          <span>READ ONLY</span>
          <span>SOURCE CITED</span>
          <span>CREW VERIFIED</span>
        </div>
      </header>

      {suggestions.length > 0 && (
        <div className="assistant-empty__suggestions">
          {suggestions.map((suggestion) => (
            <button
              key={suggestion.label}
              type="button"
              className="suggestion"
              disabled={disabled}
              onClick={() => onPick(suggestion.question)}
            >
              <span className="suggestion__label">{suggestion.label}</span>
              <span className="suggestion__text">{suggestion.question}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
