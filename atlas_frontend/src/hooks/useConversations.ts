/**
 * The sidebar's list of stored threads.
 *
 * Deliberately separate from `useChat`: the list changes for reasons the
 * transcript does not (a delete, a rename, another tab adding a thread), and
 * keeping them apart means neither re-renders for the other's reasons.
 *
 * The list is cached across route changes, so returning from the dashboard
 * shows the same sidebar you left rather than a row of skeletons. It is
 * revalidated behind that, because a finished turn changes a thread's title
 * and its position in the order.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import {
  deleteAllConversations,
  deleteConversation,
  fetchConversations,
} from '@/lib/api'
import {
  CacheKey,
  dropCache,
  dropConversationCache,
  isFresh,
  readCache,
  TTL,
  updateCache,
  writeCache,
} from '@/lib/cache'
import type { ConversationSummary } from '@/lib/types'

interface UseConversations {
  conversations: ConversationSummary[]
  loading: boolean
  error: string | null
  refresh: () => void
  remove: (id: string) => Promise<void>
  clearAll: () => Promise<void>
}

export function useConversations(): UseConversations {
  const [conversations, setConversations] = useState<ConversationSummary[]>(
    () => readCache<ConversationSummary[]>(CacheKey.conversations)?.value ?? [],
  )
  // Only an empty sidebar has anything to wait for.
  const [loading, setLoading] = useState(
    () => readCache(CacheKey.conversations) === undefined,
  )
  const [error, setError] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)

  const refresh = useCallback(() => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    fetchConversations(controller.signal)
      .then((rows) => {
        writeCache(CacheKey.conversations, rows)
        setConversations(rows)
        setError(null)
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return
        setError(caught instanceof Error ? caught.message : 'Could not load history.')
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
  }, [])

  // On mount, only go back to the backend if the cached list has had time to
  // go out of date. `refresh` is still called outright whenever a turn ends.
  useEffect(() => {
    if (!isFresh(readCache(CacheKey.conversations), TTL.conversations)) refresh()
    return () => abortRef.current?.abort()
  }, [refresh])

  const remove = useCallback(async (id: string) => {
    // Drop it locally first — the row disappearing on click is the whole
    // point of the button, and the refresh below reconciles either way. The
    // cache is corrected alongside, or the row would come back on the next
    // visit and vanish again once the revalidation landed.
    const without = (rows: ConversationSummary[]) =>
      rows.filter((row) => row.conversation_id !== id)

    setConversations(without)
    updateCache<ConversationSummary[]>(CacheKey.conversations, without)
    dropCache(CacheKey.conversation(id))

    await deleteConversation(id)
  }, [])

  const clearAll = useCallback(async () => {
    setConversations([])
    writeCache(CacheKey.conversations, [])
    dropConversationCache()

    await deleteAllConversations()
  }, [])

  return { conversations, loading, error, refresh, remove, clearAll }
}
