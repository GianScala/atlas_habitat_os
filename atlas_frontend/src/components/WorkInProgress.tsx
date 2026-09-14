/**
 * An answer still being written, said in the header of every page.
 *
 * A model running on this machine takes tens of seconds, which is long enough
 * that people leave — to the dashboard, to another thread — and reasonably
 * conclude nothing is happening. The request now survives that (see
 * `lib/liveTurn.ts`), so the interface has to admit it: something is running,
 * this is what it is doing, this is how long it has been, and here is the way
 * back to it.
 *
 * The elapsed count is deliberate. On a local model the honest answer to "is
 * it stuck?" is "no, it is nineteen seconds in", and a number that keeps
 * moving says that better than a spinner ever does.
 */

import { Link } from 'react-router-dom'

import { useElapsed } from '@/hooks/useLiveTurn'
import type { Turn } from '@/lib/liveTurn'
import { humaniseToolName } from '@/lib/format'

interface WorkInProgressProps {
  turn: Turn | null
}

/** What the turn is doing at this instant, in two or three words. */
function activity(turn: Turn): string {
  const assistant = turn.messages[turn.messages.length - 1]
  if (!assistant) return 'working'

  const running = assistant.trace.find((step) => step.status === 'running')
  if (running) return humaniseToolName(running.name)

  if (assistant.content.trim()) return 'writing the answer'
  if (assistant.thinking.trim()) return 'thinking'
  return 'working'
}

export function WorkInProgress({ turn }: WorkInProgressProps) {
  const elapsed = useElapsed(turn?.streaming ? turn.startedAt : null)

  if (turn === null || !turn.streaming) return null

  const to = turn.conversationId ? `/c/${turn.conversationId}` : '/'

  return (
    <Link
      className="working-pill"
      to={to}
      title={`${activity(turn)}, ${elapsed}s so far. Click to watch it.`}
    >
      <span className="working__dots" aria-hidden>
        <span />
        <span />
        <span />
      </span>
      <span className="working-pill__what">{activity(turn)}</span>
      <span className="working-pill__clock">{elapsed}s</span>
    </Link>
  )
}
