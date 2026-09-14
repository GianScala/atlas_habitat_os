/**
 * Summarised reasoning, collapsed.
 *
 * This is a summary the model produces, not its raw chain of thought, and it
 * is never the basis for an answer — it sits behind a disclosure so it does
 * not compete with the number the person asked for.
 */

import { ChevronRight } from '@/icons'

interface ThinkingTraceProps {
  text: string
}

export function ThinkingTrace({ text }: ThinkingTraceProps) {
  if (!text.trim()) return null

  return (
    <details className="panel">
      <summary className="panel__summary">
        <ChevronRight className="panel__chevron" />
        <span className="panel__label">Reasoning</span>
        <span className="panel__hint">summarised</span>
      </summary>

      <div className="panel__body">
        <div className="thinking">{text}</div>
      </div>
    </details>
  )
}
