/**
 * The question box.
 *
 * Enter sends, Shift+Enter adds a line. The textarea grows with its content
 * up to a cap, so a long question stays readable without the box swallowing
 * the transcript.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { Mic, Send, Speaker, Stop } from '@/icons'
import { fetchVoiceStatus, transcribeVoice } from '@/lib/api'
import { stopReadAloud } from '@/lib/readAloud'

interface ComposerProps {
  disabled: boolean
  isStreaming: boolean
  onSend: (question: string) => void
  onStop: () => void
  onVoiceQuestion: () => void
  voicePlayback: 'idle' | 'loading' | 'playing' | 'blocked' | 'error'
  onReplayVoice: () => void
}

const MAX_HEIGHT_PX = 192

export function Composer({
  disabled,
  isStreaming,
  onSend,
  onStop,
  onVoiceQuestion,
  voicePlayback,
  onReplayVoice,
}: ComposerProps) {
  const [value, setValue] = useState('')
  const [voiceReady, setVoiceReady] = useState(false)
  const [voiceDetail, setVoiceDetail] = useState('Checking local voice tools…')
  const [voiceState, setVoiceState] = useState<'idle' | 'starting' | 'recording' | 'transcribing'>('idle')
  const [recordingSeconds, setRecordingSeconds] = useState(0)
  const [transcriptionNote, setTranscriptionNote] = useState('')
  const [voiceError, setVoiceError] = useState('')
  const [voiceDraft, setVoiceDraft] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const timerRef = useRef<number | null>(null)
  const mountedRef = useRef(true)
  const transcriptionRef = useRef<AbortController | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    fetchVoiceStatus(controller.signal)
      .then((status) => {
        const supported = navigator.mediaDevices !== undefined && 'MediaRecorder' in window
        setVoiceReady(status.transcription_ready && supported)
        setVoiceDetail(
          supported
            ? [status.transcription_detail, status.synthesis_detail].join(' ')
            : 'This browser does not support microphone recording.',
        )
      })
      .catch(() => setVoiceDetail('Local voice status is unavailable.'))
    return () => controller.abort()
  }, [])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      transcriptionRef.current?.abort()
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
      const recorder = recorderRef.current
      if (recorder) {
        recorder.onstop = null
        if (recorder.state !== 'inactive') recorder.stop()
      }
      streamRef.current?.getTracks().forEach((track) => track.stop())
    }
  }, [])

  useEffect(() => {
    if (voiceState !== 'recording') return
    setRecordingSeconds(0)
    const tick = window.setInterval(() => setRecordingSeconds((seconds) => seconds + 1), 1000)
    return () => window.clearInterval(tick)
  }, [voiceState])

  const resize = useCallback(() => {
    const element = textareaRef.current
    if (!element) return

    // An empty box is exactly one row. Measuring scrollHeight here would size
    // it to the wrapped *placeholder* instead, which is both wrong and wildly
    // too tall before layout has settled.
    if (element.value === '') {
      element.style.height = ''
      return
    }

    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, MAX_HEIGHT_PX)}px`
  }, [])

  useEffect(resize, [value, resize])

  // Once an answer finishes, put the cursor back so the next question can be
  // typed without reaching for the mouse.
  useEffect(() => {
    if (!isStreaming) textareaRef.current?.focus()
  }, [isStreaming])

  const submit = useCallback(() => {
    const question = value.trim()
    if (!question || disabled || voiceState !== 'idle') return
    stopReadAloud()
    if (voiceDraft) onVoiceQuestion()
    onSend(question)
    setValue('')
    setVoiceDraft(false)
  }, [disabled, onSend, onVoiceQuestion, value, voiceDraft, voiceState])

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault()
        submit()
      }
    },
    [submit],
  )

  const canSend = value.trim().length > 0 && !disabled && voiceState === 'idle'

  const stopRecording = useCallback(() => {
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop()
  }, [])

  const toggleRecording = useCallback(async () => {
    if (voiceState === 'transcribing') {
      transcriptionRef.current?.abort()
      return
    }
    if (voiceState === 'recording') {
      stopRecording()
      return
    }
    if (!voiceReady || disabled || voiceState !== 'idle') return

    stopReadAloud()
    setVoiceError('')
    setTranscriptionNote('')
    setVoiceState('starting')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: {
        channelCount: 1, echoCancellation: true, noiseSuppression: true,
      } })
      if (!mountedRef.current) { stream.getTracks().forEach((track) => track.stop()); return }
      streamRef.current = stream
      const recorder = new MediaRecorder(stream)
      recorderRef.current = recorder
      chunksRef.current = []
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunksRef.current.push(event.data)
      }
      recorder.onstop = async () => {
        if (timerRef.current !== null) window.clearTimeout(timerRef.current)
        stream.getTracks().forEach((track) => track.stop())
        streamRef.current = null
        setVoiceState('transcribing')
        const controller = new AbortController()
        transcriptionRef.current = controller
        const timeout = window.setTimeout(() => controller.abort('timeout'), 20_000)
        const started = performance.now()
        try {
          const recording = new Blob(chunksRef.current, { type: recorder.mimeType })
          const result = await transcribeVoice(recording, controller.signal)
          if (!mountedRef.current) return
          setValue((draft) => [draft.trim(), result.text].filter(Boolean).join(' '))
          setVoiceDraft(true)
          setTranscriptionNote(`Transcribed in ${((performance.now() - started) / 1000).toFixed(1)}s · review and send`)
          window.requestAnimationFrame(() => textareaRef.current?.focus())
        } catch (error) {
          if (mountedRef.current && (!controller.signal.aborted || controller.signal.reason === 'timeout')) {
            setVoiceError(controller.signal.aborted ? 'Transcription timed out. Try a shorter recording.'
              : error instanceof Error ? error.message : 'Could not transcribe the recording.')
          }
        } finally {
          window.clearTimeout(timeout)
          if (mountedRef.current) setVoiceState('idle')
        }
      }
      recorder.start(250)
      setVoiceState('recording')
      timerRef.current = window.setTimeout(stopRecording, 60_000)
    } catch (error) {
      streamRef.current?.getTracks().forEach((track) => track.stop())
      if (!mountedRef.current) return
      setVoiceState('idle')
      setVoiceError(
        error instanceof DOMException && error.name === 'NotAllowedError'
          ? 'Microphone access was denied.'
          : 'Could not start the microphone.',
      )
    }
  }, [disabled, stopRecording, voiceReady, voiceState])

  const voiceNote = voiceError || (
    voiceState === 'starting' ? 'Waiting for microphone access…' :
    voiceState === 'recording' ? `Recording · ${recordingSeconds}s · tap stop when finished` :
    voiceState === 'transcribing' ? 'Transcribing locally… tap stop to cancel' :
    voicePlayback === 'loading' ? 'Preparing the local voice reply…' :
    voicePlayback === 'playing' ? 'Playing the local voice reply' :
    voicePlayback === 'blocked' ? 'Playback needs one tap' :
    voicePlayback === 'error' ? 'Use Read aloud below the answer to retry.' : transcriptionNote
  )

  return (
    <div className="composer">
      <div className="composer__inner">
        <form
          className="composer__field"
          onSubmit={(event) => {
            event.preventDefault()
            submit()
          }}
        >
          <textarea
            ref={textareaRef}
            className="composer__input"
            rows={1}
            value={value}
            readOnly={voiceState !== 'idle'}
            // Kept short so it is not clipped in a one-row box on a phone.
            // The empty state carries the worked examples.
            placeholder="Ask about telemetry…"
            aria-label="Ask a question about habitat telemetry"
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={handleKeyDown}
          />

          <button
            type="button"
            className={`composer__voice${voiceState === 'recording' ? ' composer__voice--recording' : ''}`}
            disabled={!voiceReady || disabled || voiceState === 'starting'}
            onClick={toggleRecording}
            aria-label={voiceState === 'recording' ? 'Stop recording' : voiceState === 'transcribing' ? 'Cancel transcription' : 'Record a question'}
            aria-pressed={voiceState === 'recording'}
            title={voiceState === 'recording' ? 'Stop recording' : voiceDetail}
          >
            {voiceState === 'recording' || voiceState === 'transcribing' ? <Stop /> : <Mic />}
          </button>

          {isStreaming ? (
            <button
              type="button"
              className="composer__send composer__send--stop"
              onClick={onStop}
              aria-label="Stop generating"
              title="Stop"
            >
              <Stop />
            </button>
          ) : (
            <button
              type="submit"
              className="composer__send"
              disabled={!canSend}
              aria-label="Send question"
              title="Send"
            >
              <Send />
            </button>
          )}
        </form>

        {voiceNote ? (
          <div className={`composer__voice-note${voiceError ? ' composer__voice-note--error' : ''}`} role="status">
            <span>{voiceNote}</span>
            {voicePlayback === 'blocked' && (
              <button type="button" onClick={onReplayVoice}><Speaker /> Play answer</button>
            )}
          </div>
        ) : (
          <p className="composer__footnote">
            <span className="composer__footnote-desktop">
              <kbd>Enter</kbd> to send · <kbd>Shift</kbd>+<kbd>Enter</kbd> for a new
              line · microphone audio stays local
            </span>
            <span className="composer__footnote-mobile">Tap mic to dictate · audio stays local</span>
          </p>
        )}
      </div>
    </div>
  )
}
