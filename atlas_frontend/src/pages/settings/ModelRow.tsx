/**
 * One model, offered or installed.
 *
 * The row has to answer four questions at a glance, and they are not equally
 * important. In order: can it query the habitat, is it on this machine, is it
 * the one answering right now, and what does it cost to keep. Tool support
 * comes first because it is the one that decides whether the model is usable
 * here at all — a model that cannot call a tool cannot read a sensor, and
 * will invent the reading rather than admit it.
 */

import { Check, Download, Trash, Warning } from '@/icons'
import { formatGigabytes } from '@/lib/format'
import type { ModelInfo } from '@/lib/types'

interface ModelRowProps {
  model: ModelInfo
  /** Progress text while this model is downloading, if it is. */
  progress: string | null
  /** A click is in flight on this row. */
  busy: boolean
  /** Another row is busy, or an install is running elsewhere. */
  locked: boolean
  onInstall: (name: string) => void
  onRemove: (name: string) => void
  onUse: (name: string) => void
  onCancel: () => void
}

export function ModelRow({
  model,
  progress,
  busy,
  locked,
  onInstall,
  onRemove,
  onUse,
  onCancel,
}: ModelRowProps) {
  const installing = progress !== null

  return (
    <article className={model.active ? 'model model--active' : 'model'}>
      <div className="model__head">
        <h3 className="model__name">{model.name}</h3>

        {model.badge && <span className="model__badge">{model.badge}</span>}

        {model.active && <span className="model__badge model__badge--active">in use</span>}

        {!model.in_catalogue && <span className="model__badge">yours</span>}
      </div>

      <p className="model__description">{model.description}</p>

      <p className="model__facts">
        <span
          className={model.supports_tools ? 'model__fact' : 'model__fact model__fact--warn'}
          title={
            model.capabilities_measured
              ? 'Reported by Ollama for the weights on disk.'
              : 'Expected for this model. Confirmed once it is installed.'
          }
        >
          {model.supports_tools ? (
            'calls tools'
          ) : (
            <>
              <Warning size={12} /> cannot query telemetry
            </>
          )}
        </span>

        {model.supports_thinking && <span className="model__fact">reasons first</span>}

        {model.installed ? (
          <span className="model__fact">
            {model.size_bytes ? formatGigabytes(model.size_bytes) : 'on disk'}
            {model.quantisation ? ` · ${model.quantisation}` : ''}
          </span>
        ) : (
          model.size_note && <span className="model__fact">{model.size_note} download</span>
        )}
      </p>

      {/* Ollama reports progress per layer, so the percentage restarts several
          times over one download. Said in its own words rather than smoothed
          into a single bar that would have to be invented. */}
      {installing && (
        <p className="model__progress" role="status">
          {progress}
        </p>
      )}

      <div className="model__actions">
        {installing ? (
          <button type="button" className="button" onClick={onCancel}>
            <span className="button__label">Stop</span>
          </button>
        ) : model.installed ? (
          <>
            {!model.active && (
              <button
                type="button"
                className="button button--primary"
                onClick={() => onUse(model.name)}
                disabled={locked || busy}
                title={
                  model.supports_tools
                    ? `Answer questions with ${model.name}`
                    : `${model.name} cannot call tools, so it cannot read the habitat`
                }
              >
                <Check />
                <span className="button__label">Use this</span>
              </button>
            )}

            {model.active && (
              <span className="model__state">
                <Check />
                answering questions
              </span>
            )}

            <button
              type="button"
              className="button"
              onClick={() => onRemove(model.name)}
              disabled={locked || busy}
              title={`Delete ${model.name} from disk`}
            >
              <Trash />
              <span className="button__label">Remove</span>
            </button>
          </>
        ) : (
          <button
            type="button"
            className="button"
            onClick={() => onInstall(model.name)}
            disabled={locked || busy}
            title={`Download ${model.name}`}
          >
            <Download />
            <span className="button__label">Install</span>
          </button>
        )}
      </div>
    </article>
  )
}
