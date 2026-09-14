import { useEffect, useState } from 'react'

import { fetchVoiceStatus, saveVoiceSettings } from '@/lib/api'
import { readAloud, resumeReadAloud, stopReadAloud, useReadAloud } from '@/lib/readAloud'
import type { VoiceStatus } from '@/lib/types'
import { Speaker, Stop } from '@/icons'

export function VoiceSection() {
  const [status, setStatus] = useState<VoiceStatus | null>(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const playback = useReadAloud()
  const previewing = playback.id === 'voice-preview'
  const busy = previewing && (playback.phase === 'loading' || playback.phase === 'playing')

  useEffect(() => {
    const abort = new AbortController()
    fetchVoiceStatus(abort.signal).then(setStatus).catch((err: Error) => {
      if (!abort.signal.aborted) setError(err.message)
    })
    return () => { abort.abort(); stopReadAloud() }
  }, [])

  async function save(voice: string, language: string) {
    stopReadAloud()
    setSaving(true)
    setError('')
    try { setStatus(await saveVoiceSettings(voice, language)) }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not save the voice.') }
    finally { setSaving(false) }
  }

  return (
    <section className="settings__section">
      <h2 className="settings__title">Voice & dictation</h2>
      <p className="settings__lede">
        Choose the voice for spoken answers. Use Read aloud below any response,
        or dictate a question to hear its answer automatically. Speech runs on your ATLAS server.
      </p>
      {status ? (
        <div className="voice-settings">
          <label>
            <span>Answer voice</span>
            <select aria-label="Answer voice" value={status.active_voice} disabled={saving || !status.voices.length}
              onChange={(event) => void save(event.target.value, status.language)}>
              {!status.voices.length && <option value="">No local voices installed</option>}
              {status.voices.map((voice) => <option key={voice.id} value={voice.id}>{voice.label}</option>)}
            </select>
          </label>
          <label>
            <span>Dictation language</span>
            <select aria-label="Dictation language" value={status.language} disabled={saving || !status.voices.length}
              onChange={(event) => void save(status.active_voice, event.target.value)}>
              <option value="auto">Detect automatically</option>
              <option value="en">English</option><option value="it">Italiano</option>
              <option value="de">Deutsch</option><option value="fr">Français</option>
              <option value="es">Español</option><option value="pt">Português</option>
            </select>
          </label>
          <button type="button" className="button" disabled={saving || !status.synthesis_ready}
            onClick={() => {
              if (busy) stopReadAloud()
              else if (previewing && playback.phase === 'blocked') void resumeReadAloud()
              else readAloud('voice-preview', 'Hello. I am ATLAS, your habitat telemetry assistant.', status.active_voice)
            }}>
            {busy ? <Stop /> : <Speaker />}
            {busy ? 'Stop preview' : previewing && playback.phase === 'blocked' ? 'Play preview' : 'Preview voice'}
          </button>
          <p className="voice-settings__status" role="status">
            {saving ? 'Saving…' : !status.transcription_ready ? status.transcription_detail
              : !status.synthesis_ready ? status.synthesis_detail : 'Local dictation and speech ready'}
          </p>
        </div>
      ) : !error && <p role="status">Checking local voice tools…</p>}
      {(error || (previewing && playback.error)) && (
        <p className="answer-meta__voice-error" role="alert">{error || playback.error}</p>
      )}
    </section>
  )
}
