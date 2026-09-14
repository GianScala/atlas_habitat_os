/**
 * The line under a finished answer: copy it, how long it took, who wrote it.
 *
 * All three are provenance of a sort. A habitat crew acting on a number wants
 * to know which model produced it and whether that model was running on this
 * machine — an answer from a local 8B and one from a hosted frontier model
 * warrant different amounts of trust, and nothing else on the page says which
 * you got. The duration is here for the same reason it is worth having at
 * all: it is how you find out that swapping the model made answers four times
 * slower, without timing anything by hand.
 *
 * Fields are omitted rather than shown empty. A thread reopened after a
 * reload has neither, because the backend transcript does not carry them, and
 * a row of em-dashes would read as a failure rather than as absence.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { Check, Copy, Speaker, Stop } from '@/icons'
import { readAloud, resumeReadAloud, stopReadAloud, useReadAloud } from '@/lib/readAloud'
import { formatDuration } from '@/lib/format'
import type { AnsweredBy } from '@/lib/types'

/** How long the button stays confirmed after a copy. */
const CONFIRM_MS = 1600

/**
 * Put text on the clipboard, by whichever route this page has.
 *
 * `navigator.clipboard` needs a secure context, which a habitat deployment
 * served over plain HTTP on a LAN address is not — there the API is simply
 * absent, and the button would be dead without the older path. That path is
 * deprecated but universally implemented, and this is exactly the case it
 * still covers.
 */
async function writeToClipboard(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // Denied, or no user activation. Fall through and try the old way.
    }
  }

  const scratch = document.createElement('textarea')
  scratch.value = text
  // Off-screen rather than hidden: `display: none` cannot hold a selection.
  scratch.setAttribute('readonly', '')
  scratch.style.cssText = 'position:fixed;top:-1000px;opacity:0'
  document.body.appendChild(scratch)
  scratch.select()

  try {
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    scratch.remove()
  }
}

interface AnswerMetaProps {
  messageId: string
  /** The markdown source of the answer — what the copy button puts on the clipboard. */
  content: string
  answeredBy: AnsweredBy | null
  durationMs: number | null
}

export function AnswerMeta({ messageId, content, answeredBy, durationMs }: AnswerMetaProps) {
  const playback = useReadAloud()
  const active = playback.id === messageId
  const speaking = active && playback.phase === 'playing'
  const preparing = active && playback.phase === 'loading'
  const blocked = active && playback.phase === 'blocked'
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(timer.current), [])

  const copy = useCallback(async () => {
    window.clearTimeout(timer.current)
    // Saying it failed beats a button that silently does nothing.
    setState((await writeToClipboard(content)) ? 'copied' : 'failed')
    timer.current = window.setTimeout(() => setState('idle'), CONFIRM_MS)
  }, [content])

  const label =
    state === 'copied' ? 'Copied' : state === 'failed' ? 'Copy failed' : 'Copy answer'

  return (
    <div className="answer-meta">
      {/* Nothing to put on the clipboard when the turn produced no text. */}
      {content && (
        <button
          type="button"
          className="answer-meta__copy"
          onClick={copy}
          aria-label={label}
        >
          {state === 'copied' ? <Check size={12} /> : <Copy size={12} />}
          <span>
            {state === 'copied' ? 'Copied' : state === 'failed' ? 'Failed' : 'Copy'}
          </span>
        </button>
      )}

      {durationMs !== null && (
        <span className="answer-meta__item" title="Time from question to finished answer">
          {formatDuration(durationMs)}
        </span>
      )}

      {content && (
        <button
          type="button"
          className="answer-meta__copy"
          aria-label={speaking ? 'Stop reading aloud' : preparing ? 'Cancel audio' : blocked ? 'Play audio' : 'Read aloud'}
          onClick={() => {
            if (speaking || preparing) stopReadAloud()
            else if (blocked) void resumeReadAloud()
            else readAloud(messageId, content)
          }}
        >
          {speaking || preparing ? <Stop size={14} /> : <Speaker size={14} />}
          <span>{speaking ? 'Stop audio' : preparing ? 'Preparing · cancel' : blocked ? 'Play audio' : 'Read aloud'}</span>
        </button>
      )}

      {active && playback.error && (
        <span className="answer-meta__voice-error" role="status">{playback.error}</span>
      )}

      {answeredBy && (
        <span
          className="answer-meta__item"
          title={`${answeredBy.model_label || answeredBy.model} via ${answeredBy.provider}`}
        >
          {/* The bare model name, not `model_label` — the backend's label
              already ends in "(local)" or "(Anthropic)", which the mark
              beside it says more legibly and in one vocabulary. */}
          {answeredBy.model}
          <span
            className={`answer-meta__where answer-meta__where--${
              answeredBy.local ? 'local' : 'remote'
            }`}
          >
            {answeredBy.local ? 'local' : 'cloud'}
          </span>
        </span>
      )}
    </div>
  )
}
