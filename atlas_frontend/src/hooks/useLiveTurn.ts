/**
 * The turn in flight, for anything that is not the chat page.
 *
 * The header uses it to say that an answer is still being written, from
 * whichever page you happen to be on. `useChat` does its own subscribing
 * because it needs the messages too; this is the read-only view.
 */

import { useEffect, useState } from 'react'

import * as liveTurn from '@/lib/liveTurn'

export function useLiveTurn(): liveTurn.Turn | null {
  const [turn, setTurn] = useState<liveTurn.Turn | null>(() => liveTurn.snapshot())

  useEffect(() => liveTurn.subscribe(() => setTurn(liveTurn.snapshot())), [])

  return turn
}

/** Seconds since a turn started, ticking. Null when nothing is running. */
export function useElapsed(startedAt: number | null): number | null {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (startedAt === null) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [startedAt])

  return startedAt === null ? null : Math.max(0, Math.round((now - startedAt) / 1000))
}
