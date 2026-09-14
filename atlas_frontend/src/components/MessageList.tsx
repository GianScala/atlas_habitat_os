/**
 * The scrolling transcript.
 *
 * Follows the newest content while it streams, but stops following the moment
 * the reader scrolls up — otherwise checking an earlier answer fights the
 * autoscroll.
 */

import { useEffect, useRef } from 'react'

import type { ChatMessage, Suggestion } from '@/lib/types'

import { EmptyState } from './EmptyState'
import { MessageBubble } from './MessageBubble'

interface MessageListProps {
  messages: ChatMessage[]
  suggestions: Suggestion[]
  isStreaming: boolean
  /** True while a stored thread is being fetched. */
  loading?: boolean
  onPickSuggestion: (question: string) => void
}

/** Treat "within this many pixels of the bottom" as following along. */
const STICK_THRESHOLD_PX = 80

export function MessageList({
  messages,
  suggestions,
  isStreaming,
  loading = false,
  onPickSuggestion,
}: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const stickToBottom = useRef(true)

  useEffect(() => {
    const element = scrollRef.current
    if (!element) return

    const onScroll = () => {
      const distanceFromBottom =
        element.scrollHeight - element.scrollTop - element.clientHeight
      stickToBottom.current = distanceFromBottom < STICK_THRESHOLD_PX
    }

    element.addEventListener('scroll', onScroll, { passive: true })
    return () => element.removeEventListener('scroll', onScroll)
  }, [])

  // Re-runs on every token, which is what keeps a streaming answer in view.
  useEffect(() => {
    const element = scrollRef.current
    if (element && stickToBottom.current) {
      element.scrollTop = element.scrollHeight
    }
  })

  return (
    <div className="chat__scroll" ref={scrollRef}>
      <div className="chat__inner">
        {loading ? (
          <p className="chat__loading">Opening conversation…</p>
        ) : messages.length === 0 ? (
          <EmptyState
            suggestions={suggestions}
            disabled={isStreaming}
            onPick={onPickSuggestion}
          />
        ) : (
          messages.map((message) => <MessageBubble key={message.id} message={message} />)
        )}
      </div>
    </div>
  )
}
