/**
 * The AI half of Settings: how the app looks, and which model answers.
 *
 * One page for both, because both are the same kind of thing — a preference
 * set once and then left alone — and neither earns permanent space in the
 * header. What the header kept instead is the one fact that changes minute to
 * minute: whether the sensors can be read.
 *
 * Appearance comes first: it is the cheap, reversible one, and settling it
 * gets it out of the way of the decision that actually matters. The answering
 * style follows it — also a preference, and also reversible, but one that
 * changes what a crew reads all day rather than what it looks like.
 *
 * The rest is arranged as one decision followed by its consequences. First
 * where answers come from at all — this machine or Anthropic's — because that
 * choice decides whether anything below it matters. Then the local runtime's
 * state, because a model cannot be installed while it is down. Then the
 * models themselves.
 *
 * Two things this page refuses to be vague about. A model that cannot call
 * tools cannot read a sensor and will answer from imagination, so that is said
 * on the row rather than in a footnote. And a download is minutes long, so its
 * progress is shown in Ollama's own words rather than behind a spinner.
 */

import { useCallback, useState, type FormEvent } from 'react'

import { ErrorBanner } from '@/components/ErrorBanner'
import { useHealth } from '@/hooks/useHealth'
import { useModels, type Install, type UseModels } from '@/hooks/useModels'
import { Download, Refresh, Warning } from '@/icons'
import { formatGigabytes } from '@/lib/format'
import type { ModelInfo, ProviderInfo } from '@/lib/types'

import { AppearanceSection } from './AppearanceSection'
import { AssistantSection } from './AssistantSection'
import { ModelRow } from './ModelRow'
import { VoiceSection } from './VoiceSection'

/** A download's progress in one line, in Ollama's own vocabulary. */
function describeInstall(install: Install): string {
  const { status, percent, completed, total } = install

  if (percent !== null && completed !== null && total !== null) {
    return `${status}: ${percent}% (${formatGigabytes(completed)} of ${formatGigabytes(total)})`
  }
  return status
}

export function AiModelsSection() {
  // The header (owned by the page shell) shows health; this section only
  // needs to re-poll it after a model change, and to report a failure.
  const { error: healthError, refresh: refreshHealth } = useHealth()
  const models = useModels()
  const [custom, setCustom] = useState('')

  const { status, install, startInstall } = models

  // Every write returns the new status, but the header badge is fed by the
  // health poll, which has a cache of its own. Re-checking after a change
  // keeps the two from disagreeing about which model is in use.
  const activate = useCallback(
    (provider: string, model: string) => {
      models.activate(provider, model)
      window.setTimeout(refreshHealth, 300)
    },
    [models, refreshHealth],
  )

  const useLocal = useCallback((name: string) => activate('ollama', name), [activate])

  const installCustom = useCallback(
    (event: FormEvent) => {
      event.preventDefault()
      const wanted = custom.trim()
      if (!wanted) return
      startInstall(wanted)
      setCustom('')
    },
    [custom, startInstall],
  )

  // Any work in flight locks every other control: two installs at once, or a
  // switch made while the model being switched to is still downloading, are
  // states this page would then have to explain.
  const busy = models.busy !== null || install !== null
  const runtimeDown = status !== null && !status.runtime.reachable

  return (
    <>
      {healthError && <ErrorBanner message={healthError} kind="backend" />}

      <AppearanceSection />
          <AssistantSection />
          <VoiceSection />

          {models.error && !status && <ErrorBanner message={models.error} kind="backend" />}

          {models.loading && !status && (
            <p className="dashboard__status">Reading the model list…</p>
          )}

          {status && (
            <>
              <section className="settings__section">
                <h2 className="settings__title">Where answers come from</h2>
                <p className="settings__lede">
                  Questions, telemetry and retrieved document passages go to the
                  provider you select. For private inference, use Ollama on a
                  trusted local host. Anthropic sends this context to its cloud API.
                </p>

                <div className="settings__providers">
                  {status.providers.map((provider) => (
                    <ProviderCard
                      key={provider.key}
                      provider={provider}
                      busy={busy}
                      onChoose={() => activate(provider.key, provider.model)}
                    />
                  ))}
                </div>
              </section>

              {/* The one thing on this page that has to be read: the reason a
                  question asked right now would not be answered. */}
              {status.warning && (
                <div className="settings__warning" role="status">
                  <Warning size={15} />
                  <p>{status.warning}</p>
                </div>
              )}

              {models.actionError && <ErrorBanner message={models.actionError} kind="ollama" />}

              <section className="settings__section">
                <h2 className="settings__title">Models</h2>

                {/* Beside the list it reloads, rather than in the header: the
                    only reason to press it is that the figures below — what is
                    installed, what is in memory — look out of date. */}
                <div className="settings__row">
                  <p className="settings__lede">
                    Downloaded once and kept in{' '}
                    <code className="settings__path">{status.runtime.models_dir}</code>,
                    Ollama's own store.
                  </p>

                  <button
                    type="button"
                    className="button"
                    onClick={models.refresh}
                    disabled={models.loading}
                    title="Ask Ollama again what is installed"
                  >
                    <Refresh />
                    <span className="button__label">
                      {models.loading ? 'Refreshing' : 'Refresh'}
                    </span>
                  </button>
                </div>

                <dl className="readout settings__readout">
                  <div className="readout__item">
                    <dt className="readout__key">Runtime</dt>
                    <dd className="readout__value">
                      {status.runtime.reachable
                        ? `Ollama ${status.runtime.version ?? 'running'}`
                        : 'not running'}
                    </dd>
                  </div>
                  <div className="readout__item">
                    <dt className="readout__key">Host</dt>
                    <dd className="readout__value">{status.runtime.host}</dd>
                  </div>
                  <div className="readout__item">
                    <dt className="readout__key">On disk</dt>
                    <dd className="readout__value">
                      {status.runtime.installed_count}{' '}
                      {status.runtime.installed_count === 1 ? 'model' : 'models'}
                    </dd>
                  </div>
                  {/* What is on disk is free. What is loaded is competing for
                      memory with everything else running, and two at once on a
                      small machine is why an answer takes a minute. */}
                  <div
                    className="readout__item"
                    title="Models held in memory right now. Ollama unloads them after a period of disuse."
                  >
                    <dt className="readout__key">In memory</dt>
                    <dd className="readout__value">
                      {status.runtime.loaded.length === 0
                        ? 'none'
                        : status.runtime.loaded
                            .map((m) => `${m.name} ${formatGigabytes(m.bytes_resident)}`)
                            .join(' + ')}
                    </dd>
                  </div>
                </dl>

                <div className="settings__list">
                  {status.models.map((model) => (
                    <Row
                      key={model.name}
                      model={model}
                      models={models}
                      install={install}
                      locked={runtimeDown}
                      onUse={useLocal}
                    />
                  ))}
                </div>
              </section>

              <section className="settings__section">
                <h2 className="settings__title">Install another model</h2>
                <p className="settings__lede">
                  Anything in the Ollama catalogue, by its exact name. It must
                  support tool calling: a model that cannot call a tool cannot
                  read a sensor.
                </p>

                <form className="settings__install" onSubmit={installCustom}>
                  <input
                    className="settings__field"
                    value={custom}
                    onChange={(event) => setCustom(event.target.value)}
                    placeholder="e.g. llama3.2:3b"
                    aria-label="Model name, as listed in the Ollama catalogue"
                    disabled={busy || runtimeDown}
                    spellCheck={false}
                  />
                  <button
                    type="submit"
                    className="button"
                    disabled={busy || runtimeDown || !custom.trim()}
                  >
                    <Download />
                    <span className="button__label">Install</span>
                  </button>
                </form>
              </section>
        </>
      )}
    </>
  )
}

interface ProviderCardProps {
  provider: ProviderInfo
  busy: boolean
  onChoose: () => void
}

function ProviderCard({ provider, busy, onChoose }: ProviderCardProps) {
  return (
    <article className={provider.active ? 'provider provider--active' : 'provider'}>
      <div className="provider__head">
        <h3 className="provider__label">{provider.label}</h3>
        {provider.active && <span className="model__badge model__badge--active">in use</span>}
      </div>

      <p className="provider__description">{provider.description}</p>
      <p className="provider__model">{provider.model}</p>

      {/* Why it is unavailable, where it is — no key, or no daemon. */}
      {provider.detail && (
        <p className={provider.available ? 'provider__detail' : 'provider__detail provider__detail--warn'}>
          {provider.detail}
        </p>
      )}

      <button
        type="button"
        className="button"
        onClick={onChoose}
        disabled={provider.active || busy}
        title={`Answer questions with ${provider.model}`}
      >
        {/* Bare text, not `button__label`: that class is hidden below 640px,
            and this button has no icon to fall back to — it was rendering as
            an empty box on a phone. */}
        {provider.active ? 'Selected' : 'Use this'}
      </button>
    </article>
  )
}

interface RowProps {
  model: ModelInfo
  models: UseModels
  install: Install | null
  /** The runtime is down, so nothing here can be acted on. */
  locked: boolean
  onUse: (name: string) => void
}

/** Works out which of the page's several busy states applies to one row. */
function Row({ model, models, install, locked, onUse }: RowProps) {
  const downloading = install?.name === model.name

  return (
    <ModelRow
      model={model}
      progress={downloading ? describeInstall(install) : null}
      busy={models.busy === model.name}
      locked={locked || models.busy !== null || (install !== null && !downloading)}
      onInstall={models.startInstall}
      onRemove={models.remove}
      onUse={onUse}
      onCancel={models.cancelInstall}
    />
  )
}
