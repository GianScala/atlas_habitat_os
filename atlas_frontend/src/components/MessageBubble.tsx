/**
 * One turn in the transcript.
 *
 * A user message is a bubble. An assistant message is a full-width block with
 * its answer, the queries behind it, and any failure — because the answer is
 * the point and the evidence has to sit next to it.
 */

import type { ChatMessage } from '@/lib/types'

import { AnswerMeta } from './AnswerMeta'
import { ErrorBanner } from './ErrorBanner'
import { Markdown } from './Markdown'
import { SourceFooter } from './SourceFooter'
import { ThinkingTrace } from './ThinkingTrace'
import { ToolTrace } from './ToolTrace'

interface MessageBubbleProps {
  message: ChatMessage
}

export function MessageBubble({ message }: MessageBubbleProps) {
  if (message.role === 'user') {
    return (
      <article className="message message--user">
        <div className="message__bubble">{message.content}</div>
      </article>
    )
  }

  const hasAnswer = message.content.trim().length > 0
  const isWorking = message.streaming && !hasAnswer

  return (
    <article className="message">
      <div className="message__role">ATLAS</div>

      {/* Each block below is a `message__section`; the gap between them is a
          single CSS rule rather than a margin repeated at five call sites,
          and a fragment cannot break the adjacent-sibling selector because
          every section is a direct child. */}
      <div className="message__body">
        {/* While a query is in flight the trace is the only visible progress. */}
        {message.trace.length > 0 && (
          <div className="message__section">
            <ToolTrace steps={message.trace} defaultOpen={message.streaming} />
          </div>
        )}

        {isWorking && (
          <div className="message__section working">
            <span className="working__dots" aria-hidden>
              <span />
              <span />
              <span />
            </span>
            <span>{message.trace.length > 0 ? 'Reading the database…' : 'Working…'}</span>
          </div>
        )}

        {hasAnswer && (
          <div className="message__section">
            <Markdown>{message.content}</Markdown>
            {message.streaming && <span className="cursor" aria-hidden />}
          </div>
        )}

        {message.error && (
          <div className="message__section">
            <ErrorBanner message={message.error.message} kind={message.error.kind} />
          </div>
        )}

        {!message.streaming && message.thinking && (
          <div className="message__section">
            <ThinkingTrace text={message.thinking} />
          </div>
        )}

        {!message.streaming && message.sources.length > 0 && (
          <div className="message__section">
            <SourceFooter queries={message.sources} />
          </div>
        )}

        {/* Last, as the message's footer. Shown for a turn that failed too:
            how long it ran before it gave up is worth knowing. */}
        {!message.streaming &&
          (hasAnswer || message.durationMs !== null || message.answeredBy) && (
            <div className="message__section">
              <AnswerMeta
                messageId={message.id}
                content={hasAnswer ? message.content : ''}
                answeredBy={message.answeredBy}
                durationMs={message.durationMs}
              />
            </div>
          )}
      </div>
    </article>
  )
}
