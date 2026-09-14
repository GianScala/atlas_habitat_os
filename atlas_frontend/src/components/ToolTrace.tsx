/**
 * The queries behind an answer, collapsed by default.
 *
 * Shown as it happens rather than after the fact: while a question is being
 * worked on, the trace is the only sign that anything is happening, and it
 * says exactly which sensor is being read.
 */

import { formatToolInput, humaniseToolName, summariseTrace } from '@/lib/format'
import type { TraceStep } from '@/lib/types'

import { ChevronRight } from '@/icons'

interface ToolTraceProps {
  steps: TraceStep[]
  /** Open while the answer is still being produced, so the work is visible. */
  defaultOpen?: boolean
}

const STATUS_LABEL: Record<TraceStep['status'], string> = {
  running: 'running…',
  ok: 'returned data',
  empty: 'no data for that combination',
  failed: 'query failed',
}

export function ToolTrace({ steps, defaultOpen = false }: ToolTraceProps) {
  if (steps.length === 0) return null

  return (
    <details className="panel" open={defaultOpen}>
      <summary className="panel__summary">
        <ChevronRight className="panel__chevron" />
        <span className="panel__label">{summariseTrace(steps)}</span>
        <span className="panel__hint">what ATLAS read</span>
      </summary>

      <div className="panel__body">
        <ol className="trace">
          {steps.map((step) => (
            <li key={step.id} className={`trace__step trace__step--${step.status}`}>
              <span className="trace__marker" aria-hidden />

              <div className="trace__detail">
                <div className="trace__name">{humaniseToolName(step.name)}</div>

                {Object.keys(step.input).length > 0 && (
                  <div className="trace__args">{formatToolInput(step.input)}</div>
                )}

                <div
                  className={
                    step.status === 'failed' ? 'trace__status trace__status--failed' : 'trace__status'
                  }
                >
                  {STATUS_LABEL[step.status]}
                </div>

                {step.detail && <div className="trace__query">{step.detail}</div>}

                {step.queries.map((query) => (
                  <code key={query} className="trace__query">
                    {query}
                  </code>
                ))}
              </div>
            </li>
          ))}
        </ol>
      </div>
    </details>
  )
}
