/**
 * The chat state machine.
 *
 * Owns the transcript and the conversation id. It does NOT own the request:
 * an answer in flight lives in `lib/liveTurn.ts`, outside the React tree,
 * because this hook is unmounted the moment someone looks at the dashboard
 * and a turn must survive that. See that module for the reasoning.
 *
 * So there are two halves to what is on screen. The SETTLED transcript —
 * fetched, or restored from `lib/cache.ts` — and the turn currently being
 * written, if it belongs to the conversation being viewed. They are joined
 * for rendering and folded together once the turn lands.
 *
 * A settled transcript is cached, so stepping out to the dashboard and back
 * reopens the thread as it was instead of refetching it behind a spinner.
 * Only settled ones: a turn that errored or was stopped leaves the in-memory
 * transcript saying something the backend may not agree with, and the cache
 * is meant to be indistinguishable from a fresh fetch.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { fetchConversation } from '@/lib/api'
import {
  cachedValue,
  CacheKey,
  isFresh,
  readCache,
  TTL,
  writeCache,
} from '@/lib/cache'
import * as liveTurn from '@/lib/liveTurn'
import type { AnsweredBy, ChatMessage, TranscriptMessage } from '@/lib/types'

interface UseChat {
  messages: ChatMessage[]
  isStreaming: boolean
  conversationId: string | null
  /** The model that answered the most recent turn of this session. */
  answeredBy: AnsweredBy | null
  /** True while an existing thread is being fetched. */
  loading: boolean
  loadError: string | null
  send: (question: string) => void
  stop: () => void
  /** Clear the view for a new thread. Nothing is deleted, nothing is stopped. */
  reset: () => void
}

interface Options {
  /** Thread to open, or null for a fresh one. */
  conversationId: string | null
  /** Notified when a thread is created or a turn completes. */
  onChanged?: (conversationId: string) => void
}

/** A stored turn, widened into the shape the live stream produces. */
function fromTranscript(message: TranscriptMessage): ChatMessage {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    thinking: message.thinking,
    trace: message.trace,
    sources: message.sources,
    error: null,
    streaming: false,
    createdAt: Date.now(),
    // Neither is stored server-side, so a thread reopened after a reload
    // comes back without them. The footer simply omits what it does not have.
    answeredBy: null,
    durationMs: null,
  }
}

/** A thread already rendered this session, if it is still in the cache. */
function cachedTranscript(id: string | null): ChatMessage[] | undefined {
  return id ? cachedValue<ChatMessage[]>(CacheKey.conversation(id)) : undefined
}

export function useChat({ conversationId: requested, onChanged }: Options): UseChat {
  const [settled, setSettled] = useState<ChatMessage[]>(
    () => cachedTranscript(requested) ?? [],
  )
  const [live, setLive] = useState<liveTurn.Turn | null>(() => liveTurn.snapshot())
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  const changedRef = useRef(onChanged)
  changedRef.current = onChanged

  // Which thread the settled transcript belongs to. Held from the first
  // render when it was restored from the cache, so the effect below does not
  // then fetch what is already on screen.
  const heldRef = useRef<string | null>(cachedTranscript(requested) ? requested : null)

  // Every change to the running turn lands here. Unsubscribing on unmount is
  // all that happens when the page is left — the request is untouched.
  useEffect(() => liveTurn.subscribe(() => setLive(liveTurn.snapshot())), [])

  /** Is the running turn the one this view should be showing? */
  const mine = live !== null && liveTurn.isFor(requested)

  // A brand-new thread claims its id mid-stream. Put it in the URL — from
  // here rather than from the stream callback, because that callback may fire
  // while this page is unmounted and navigating from nowhere does nothing.
  useEffect(() => {
    if (requested === null && live?.conversationId) {
      changedRef.current?.(live.conversationId)
    }
  }, [live?.conversationId, requested])

  // A turn that has finished becomes part of the transcript. Claiming it is
  // what releases the store to accept the next question.
  useEffect(() => {
    if (!mine || live === null || live.streaming) return

    const finished = liveTurn.claim()
    if (finished === null) return

    heldRef.current = finished.conversationId
    setSettled((current) => [...current, ...finished.messages])
    setLive(null)
    if (finished.conversationId) changedRef.current?.(finished.conversationId)
  }, [live, mine])

  // Opening a stored thread, or clearing the view for a new one.
  useEffect(() => {
    // The id of a brand-new thread reaches the URL mid-stream, which lands
    // back here as a changed `requested`. That is this hook's own answer
    // arriving, not the reader opening something else — and the answer is on
    // screen already, so there is nothing to fetch.
    if (requested && requested === heldRef.current) return
    if (requested && liveTurn.isFor(requested)) {
      heldRef.current = requested
      return
    }

    setLoadError(null)

    if (!requested) {
      heldRef.current = null
      setSettled([])
      setLoading(false)
      return
    }

    // A cached thread is shown at once. If it has been sitting long enough
    // that another tab could have added to it, the fetch below still runs —
    // silently, with the transcript up, rather than behind a spinner.
    const cached = readCache<ChatMessage[]>(CacheKey.conversation(requested))
    if (cached) {
      heldRef.current = requested
      setSettled(cached.value)
      setLoading(false)
      if (isFresh(cached, TTL.conversation)) return
    }

    const controller = new AbortController()
    if (!cached) setLoading(true)

    fetchConversation(requested, controller.signal)
      .then((detail) => {
        // A revalidation that lands after a turn has started here is an older
        // transcript than the one on screen. Drop it.
        if (liveTurn.isFor(requested)) return
        heldRef.current = requested
        setSettled(detail.messages.map(fromTranscript))
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return
        // A thread that is on screen from the cache stays on screen; failing
        // to confirm it is not a reason to replace it with an error.
        if (cached) return
        // Nothing is held now, so returning to this thread should retry.
        heldRef.current = null
        setSettled([])
        setLoadError(
          caught instanceof Error ? caught.message : 'Could not open that conversation.',
        )
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })

    return () => controller.abort()
  }, [requested])

  // Keep the cache in step with the settled transcript.
  useEffect(() => {
    const id = heldRef.current
    if (mine || !id || settled.length === 0) return
    writeCache(CacheKey.conversation(id), settled)
  }, [mine, settled])

  const messages = useMemo(
    () => (mine && live ? [...settled, ...live.messages] : settled),
    [live, mine, settled],
  )

  const send = useCallback(
    (question: string) => {
      liveTurn.start(question, requested, (id) => changedRef.current?.(id))
    },
    [requested],
  )

  const stop = useCallback(() => liveTurn.stop(), [])

  const reset = useCallback(() => {
    // Deliberately does not stop a running turn. Starting a new conversation
    // is not a reason to throw away an answer that is most of the way there;
    // it keeps running, and the header says so until it lands.
    heldRef.current = null
    setSettled([])
    setLoadError(null)
  }, [])

  return {
    messages,
    isStreaming: mine && (live?.streaming ?? false),
    conversationId: requested ?? live?.conversationId ?? null,
    answeredBy: live?.answeredBy ?? null,
    loading,
    loadError,
    send,
    stop,
    reset,
  }
}
