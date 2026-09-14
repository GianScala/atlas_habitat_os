/**
 * How ATLAS talks.
 *
 * Four registers, shown as a row you read rather than a menu you open, for the
 * same reason Appearance is: the choice is between four things you have to
 * compare, and a closed dropdown shows you one of them.
 *
 * The custom box is only submitted when Custom is the selection, but the text
 * is kept either way — someone who writes a paragraph, tries Concise, and
 * comes back should find their paragraph.
 *
 * The note under the row is the one thing on this page that has to be read:
 * the register changes the VOICE and nothing else. A style that quietly
 * loosened the grounding rules would be the most dangerous setting in this
 * application — an assistant that is funnier and occasionally makes a number
 * up is worse than no assistant, because a crew would take longer to notice.
 */

import { useCallback, useEffect, useState } from 'react'

import { ErrorBanner } from '@/components/ErrorBanner'
import { fetchAssistantStyle, saveAssistantStyle } from '@/lib/api'
import type { AssistantSettings, StyleKey } from '@/lib/types'

export function AssistantSection() {
  const [settings, setSettings] = useState<AssistantSettings | null>(null)
  const [custom, setCustom] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    fetchAssistantStyle(controller.signal)
      .then((found) => {
        setSettings(found)
        setCustom(found.custom)
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return
        setError(
          caught instanceof Error ? caught.message : 'Could not read the answer style.',
        )
      })
    return () => controller.abort()
  }, [])

  const apply = useCallback(
    async (style: StyleKey, text: string) => {
      setSaving(true)
      setError(null)
      setSaved(false)
      try {
        const stored = await saveAssistantStyle(style, text)
        setSettings(stored)
        setCustom(stored.custom)
        setSaved(true)
      } catch (caught) {
        setError(
          caught instanceof Error ? caught.message : 'Could not save the answer style.',
        )
      } finally {
        setSaving(false)
      }
    },
    [],
  )

  if (!settings) {
    return (
      <section className="settings__section">
        <h2 className="settings__title">How ATLAS answers</h2>
        {error ? (
          <ErrorBanner message={error} kind="backend" />
        ) : (
          <p className="dashboard__status">Reading the answer style…</p>
        )}
      </section>
    )
  }

  const chosen = settings.style

  return (
    <section className="settings__section">
      <h2 className="settings__title">How ATLAS answers</h2>
      <p className="settings__lede">
        Choose how answers are written. Every style is instructed to use queried
        data and cite its sources. Style instructions do not guarantee accuracy;
        verify important figures against the source readings.
      </p>

      <div className="settings__choices" role="group" aria-label="Answer style">
        {settings.options.map((option) => (
          <button
            key={option.key}
            type="button"
            className={option.key === chosen ? 'button button--primary' : 'button'}
            onClick={() => void apply(option.key, custom)}
            aria-pressed={option.key === chosen}
            disabled={saving}
            title={option.blurb}
          >
            {/* Not `button__label`: that class disappears below 640px, which
                is fine for a button with an icon and leaves this one blank. */}
            {option.label}
          </button>
        ))}
      </div>

      <p className="settings__note">
        {settings.options.find((option) => option.key === chosen)?.blurb}
      </p>

      <div className="style-custom">
        <label className="style-custom__field">
          <span className="setup__label">Your own instructions</span>
          <textarea
            className="style-custom__input"
            value={custom}
            onChange={(event) => {
              setCustom(event.target.value)
              setSaved(false)
            }}
            rows={5}
            placeholder={
              'e.g. Answer in Italian. Lead with the number, then one line on ' +
              'whether it worries you. Never use bullet points.'
            }
            disabled={saving}
            spellCheck
          />
          <span className="setup__note">
            Used when Custom is selected. It goes into every prompt underneath
            the rules that keep the answers honest, so an instruction that would
            need ATLAS to round, guess, or skip a figure is the one thing it
            will not follow.
          </span>
        </label>

        <div className="style-custom__actions">
          <button
            type="button"
            className="button button--primary"
            onClick={() => void apply('custom', custom)}
            disabled={saving || !custom.trim()}
            title={
              custom.trim()
                ? 'Save this and answer in it from the next question on'
                : 'Write the instructions first'
            }
          >
            <span className="button__label">
              {saving ? 'Saving' : 'Use my instructions'}
            </span>
          </button>
          {saved && (
            <span className="style-custom__saved" role="status">
              Saved. Applies to the next question.
            </span>
          )}
        </div>
      </div>

      {error && <ErrorBanner message={error} kind="backend" />}
    </section>
  )
}
