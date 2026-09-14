/**
 * The answer currently being written, kept outside the React tree.
 *
 * A turn takes tens of seconds against a model running on this machine. In
 * that time it is entirely reasonable to go and look at the dashboard — and
 * until this module existed, doing so killed the answer: React unmounts the
 * chat page on a route change, the hook's cleanup aborted the fetch, and the
 * backend's generator was closed mid-sentence. The work was thrown away at
 * the exact moment it was most expensive.
 *
 * So the turn lives here instead. Module scope, like `lib/cache.ts`, and for
 * the same reason: it has to outlive the components that look at it. A
 * component mounting subscribes, a component unmounting unsubscribes, and
 * neither event has any bearing on whether the request continues. The only
 * things that stop a turn are the person pressing Stop and the turn finishing.
 *
 * WHAT IT DOES NOT DO. It holds one turn, not the transcript — the settled
 * history belongs to the conversation and is fetched or cached like anything
 * else. And it does not render: it accumulates and notifies, and `useChat`
 * decides what that looks like.
 */

import { askQuestion, SseError } from './api'
import { CacheKey, dropCache } from './cache'
import { makeId } from './format'
import type { AnsweredBy, ChatMessage, StreamEvent, TraceStep } from './types'

/** One turn in flight, or the last one to finish. */
export interface Turn {
  /** Null until the `start` event names it, on a brand-new thread. */
  conversationId: string | null
  /** The question and the answer being built, in transcript order. */
  messages: ChatMessage[]
  streaming: boolean
  answeredBy: AnsweredBy | null
  /** True once the stream ended cleanly and the turn is on disk. */
  settled: boolean
  startedAt: number
}

let turn: Turn | null = null
let controller: AbortController | null = null

const listeners = new Set<() => void>()

function announce(): void {
  for (const listener of listeners) listener()
}

/** Watch the live turn. Returns the unsubscribe. */
export function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** The turn as it stands, or null if nothing is running or pending. */
export function snapshot(): Turn | null {
  return turn
}

/** Is a turn running for this conversation? A null id means a brand-new one. */
export function isFor(conversationId: string | null): boolean {
  if (turn === null) return false
  // A turn that has not claimed an id yet belongs to whoever started it, which
  // is the view that had no conversation open.
  if (turn.conversationId === null) return conversationId === null
  return turn.conversationId === conversationId
}

/**
 * Hand the finished turn over and forget it.
 *
 * Called by whichever view folds it into its transcript. Until someone does,
 * a completed turn is kept: the person may have been on another page when it
 * landed, and coming back to find the answer missing would be worse than
 * anything the abort ever did.
 */
export function claim(): Turn | null {
  const finished = turn !== null && !turn.streaming ? turn : null
  if (finished) {
    turn = null
    controller = null
  }
  return finished
}

/** Abort the turn. The only thing besides completion that ends one. */
export function stop(): void {
  controller?.abort()
}

/** Throw away whatever is held, running or not. */
export function reset(): void {
  controller?.abort()
  turn = null
  controller = null
  announce()
}

function emptyAssistant(): ChatMessage {
  return {
    id: makeId(),
    role: 'assistant',
    content: '',
    thinking: '',
    trace: [],
    sources: [],
    error: null,
    streaming: true,
    createdAt: Date.now(),
    answeredBy: null,
    durationMs: null,
  }
}

function patchAssistant(change: (message: ChatMessage) => ChatMessage): void {
  if (turn === null) return
  const next = [...turn.messages]
  const last = next[next.length - 1]
  if (!last || last.role !== 'assistant') return
  next[next.length - 1] = change(last)
  turn = { ...turn, messages: next }
}

function apply(event: StreamEvent): void {
  if (turn === null) return

  switch (event.type) {
    case 'start': {
      const answeredBy: AnsweredBy = {
        provider: event.provider,
        model: event.model,
        model_label: event.model_label,
        local: event.local,
      }
      turn = { ...turn, conversationId: event.conversation_id, answeredBy }
      // Also stamped on the message, because the turn is discarded once it
      // settles and the transcript has to keep saying who wrote each answer.
      patchAssistant((m) => ({ ...m, answeredBy }))
      break
    }

    case 'text_delta':
      patchAssistant((m) => ({ ...m, content: m.content + event.text }))
      break

    case 'thinking_delta':
      patchAssistant((m) => ({ ...m, thinking: m.thinking + event.text }))
      break

    case 'tool_call':
      patchAssistant((m) => ({
        ...m,
        // Text written before a query and text written after it are separate
        // thoughts from separate rounds; without a break they run together.
        content:
          m.content && !m.content.endsWith('\n\n')
            ? `${m.content.trimEnd()}\n\n`
            : m.content,
        trace: [
          ...m.trace,
          {
            id: event.call.id,
            name: event.call.name,
            input: event.call.input,
            status: 'running',
            queries: [],
            detail: null,
          } satisfies TraceStep,
        ],
      }))
      break

    case 'tool_result':
      patchAssistant((m) => ({
        ...m,
        trace: m.trace.map((step) =>
          step.id === event.result.id
            ? {
                ...step,
                status: !event.result.ok
                  ? 'failed'
                  : event.result.has_data
                    ? 'ok'
                    : 'empty',
                queries: event.result.queries,
                detail: event.result.detail,
              }
            : step,
        ),
      }))
      break

    case 'sources':
      patchAssistant((m) => ({ ...m, sources: event.queries }))
      break

    case 'error':
      patchAssistant((m) => ({
        ...m,
        error: { message: event.message, kind: event.kind },
      }))
      break

    case 'done':
      turn = { ...turn, conversationId: event.conversation_id, settled: true }
      break
  }
}

/**
 * Ask a question. Returns immediately; watch it with `subscribe`.
 *
 * `onConversation` fires as soon as the thread has an id, so the page can put
 * it in the URL — including a page that mounts later and wants to know where
 * the answer it can see is being written.
 */
export function start(
  question: string,
  conversationId: string | null,
  onConversation?: (id: string) => void,
): void {
  if (turn?.streaming) return

  const trimmed = question.trim()
  if (!trimmed) return

  controller = new AbortController()
  const signal = controller.signal

  turn = {
    conversationId,
    messages: [
      {
        id: makeId(),
        role: 'user',
        content: trimmed,
        thinking: '',
        trace: [],
        sources: [],
        error: null,
        streaming: false,
        createdAt: Date.now(),
        answeredBy: null,
        durationMs: null,
      },
      emptyAssistant(),
    ],
    streaming: true,
    answeredBy: null,
    settled: false,
    startedAt: Date.now(),
  }
  announce()

  void (async () => {
    let claimed: string | null = conversationId
    try {
      for await (const event of askQuestion(trimmed, conversationId, signal)) {
        apply(event)
        if (event.type === 'start' && event.conversation_id !== claimed) {
          claimed = event.conversation_id
          onConversation?.(event.conversation_id)
        }
        announce()
      }
    } catch (error) {
      if (signal.aborted) {
        patchAssistant((m) => ({ ...m, content: m.content || '_Stopped._' }))
      } else {
        const detail =
          error instanceof SseError || error instanceof Error
            ? error.message
            : 'Something went wrong talking to the backend.'
        patchAssistant((m) => ({
          ...m,
          error: { message: detail, kind: 'transport' },
        }))
      }
    } finally {
      // A turn that never reached `done` may have left a partial answer on
      // disk that this transcript does not match. Forget the cached thread
      // rather than keep a guess; the next visit fetches what was really kept.
      if (turn !== null) {
        if (!turn.settled && turn.conversationId) {
          dropCache(CacheKey.conversation(turn.conversationId))
        }
        // Wall-clock from the question leaving to the stream ending — which
        // is the wait the reader actually sat through, not the model's own
        // generation time. Recorded for a stopped or failed turn too: how
        // long it ran before giving up is the more interesting number.
        const durationMs = Date.now() - turn.startedAt
        patchAssistant((m) => ({ ...m, streaming: false, durationMs }))
        turn = { ...turn, streaming: false }
      }
      controller = null
      announce()
    }
  })()
}
