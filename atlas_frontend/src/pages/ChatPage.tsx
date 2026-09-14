/**
 * The chat page: sidebar, transcript, composer.
 *
 * The open thread lives in the URL (`/c/:conversationId`), so a conversation
 * can be linked, bookmarked, and reached with the back button.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { AppHeader } from '@/components/AppHeader'
import { Composer } from '@/components/Composer'
import { ErrorBanner } from '@/components/ErrorBanner'
import { MessageList } from '@/components/MessageList'
import { Sidebar } from '@/components/Sidebar'
import { useChat } from '@/hooks/useChat'
import { useConversations } from '@/hooks/useConversations'
import { useHealth } from '@/hooks/useHealth'
import { fetchSuggestions } from '@/lib/api'
import { readAloud, resumeReadAloud, stopReadAloud, useReadAloud } from '@/lib/readAloud'
import { cachedValue, CacheKey, writeCache } from '@/lib/cache'
import type { Suggestion } from '@/lib/types'

const SIDEBAR_KEY = 'atlas.sidebar.open'

/** Below this the sidebar floats over the transcript rather than beside it. */
const WIDE_ENOUGH = '(min-width: 900px)'

function isWide(): boolean {
  return window.matchMedia(WIDE_ENOUGH).matches
}

export default function ChatPage() {
  const { conversationId = null } = useParams<{ conversationId: string }>()
  const navigate = useNavigate()

  const { health, checking, error: healthError, refresh: refreshHealth } = useHealth()
  const history = useConversations()
  const [suggestions, setSuggestions] = useState<Suggestion[]>(
    () => cachedValue<Suggestion[]>(CacheKey.suggestions) ?? [],
  )
  const [voiceReplyArmed, setVoiceReplyArmed] = useState(false)
  const playback = useReadAloud()
  const previousAnswerRef = useRef<string | undefined>()

  // The stored preference only applies where the sidebar has room to sit
  // beside the transcript. On a phone it covers most of the page, so it
  // starts closed however it was left on a desktop.
  const [sidebarOpen, setSidebarOpen] = useState(
    () => isWide() && window.localStorage.getItem(SIDEBAR_KEY) !== 'closed',
  )

  // A new thread gets its id from the first `start` event; put it in the URL
  // so a reload reopens the same conversation.
  const handleChanged = useCallback(
    (id: string) => {
      if (id !== conversationId) navigate(`/c/${id}`, { replace: true })
      history.refresh()
    },
    [conversationId, history, navigate],
  )

  const chat = useChat({ conversationId, onChanged: handleChanged })

  // A question entered through the microphone opts its next answer into local
  // speech. Text-only questions remain quiet.
  useEffect(() => {
    if (!voiceReplyArmed || chat.isStreaming || chat.loading) return
    const answer = [...chat.messages].reverse().find((message) => message.role === 'assistant')
    if (!answer || answer.id === previousAnswerRef.current || answer.streaming) return
    setVoiceReplyArmed(false)
    if (!answer.error && answer.content.trim()) readAloud(answer.id, answer.content)
  }, [chat.isStreaming, chat.loading, chat.messages, voiceReplyArmed])

  useEffect(() => stopReadAloud, [])

  // Fixed for the session, so one fetch covers every visit to this page.
  useEffect(() => {
    if (cachedValue<Suggestion[]>(CacheKey.suggestions)) return

    const controller = new AbortController()
    fetchSuggestions(controller.signal)
      .then((rows) => {
        writeCache(CacheKey.suggestions, rows)
        setSuggestions(rows)
      })
      .catch(() => {
        // Starter questions are a nicety; the composer works without them.
      })
    return () => controller.abort()
  }, [])

  const toggleSidebar = useCallback(() => {
    setSidebarOpen((open) => {
      window.localStorage.setItem(SIDEBAR_KEY, open ? 'closed' : 'open')
      return !open
    })
  }, [])

  // Picking a thread on a narrow screen should reveal it, not leave it behind
  // the sidebar. The stored preference is left alone — this is a response to
  // the window, not a choice the reader made.
  const dismissOverlay = useCallback(() => {
    if (!isWide()) setSidebarOpen(false)
  }, [])

  // Re-checks the link on the way out of the old thread: a new question is
  // the moment the answer to "can the sensors be read" matters again, and the
  // header light would otherwise be as old as the conversation just closed.
  const startNew = useCallback(() => {
    stopReadAloud()
    setVoiceReplyArmed(false)
    chat.reset()
    navigate('/')
    dismissOverlay()
    refreshHealth()
  }, [chat, dismissOverlay, navigate, refreshHealth])

  const openThread = useCallback(
    (id: string) => {
      stopReadAloud()
      setVoiceReplyArmed(false)
      navigate(`/c/${id}`)
      dismissOverlay()
    },
    [dismissOverlay, navigate],
  )

  const removeThread = useCallback(
    async (id: string) => {
      await history.remove(id)
      // Deleting the thread you are reading should leave you somewhere real.
      if (id === conversationId) startNew()
    },
    [conversationId, history, startNew],
  )

  const clearAll = useCallback(async () => {
    await history.clearAll()
    startNew()
  }, [history, startNew])

  return (
    <div className="shell">
      <Sidebar
        open={sidebarOpen}
        onToggle={toggleSidebar}
        conversations={history.conversations}
        activeId={chat.conversationId}
        loading={history.loading}
        error={history.error}
        onSelect={openThread}
        onNew={startNew}
        onDelete={removeThread}
        onClearAll={clearAll}
      />

      <div className="app">
        {/* No "New" here: the sidebar already owns starting a conversation,
            open or collapsed, and two buttons for it left the reader working
            out whether they did the same thing. */}
        <AppHeader
          tagline="telemetry assistant"
          health={health}
          checking={checking}
          error={healthError}
        />

        <main className="chat">
          {chat.loadError ? (
            <div className="chat__scroll">
              <div className="chat__inner">
                <ErrorBanner message={chat.loadError} kind="backend" />
              </div>
            </div>
          ) : (
            <MessageList
              messages={chat.messages}
              suggestions={suggestions}
              isStreaming={chat.isStreaming}
              loading={chat.loading}
              onPickSuggestion={chat.send}
            />
          )}

          <Composer
            disabled={chat.isStreaming || chat.loading}
            isStreaming={chat.isStreaming}
            onSend={chat.send}
            onStop={() => { setVoiceReplyArmed(false); chat.stop() }}
            onVoiceQuestion={() => {
              previousAnswerRef.current = [...chat.messages].reverse().find((m) => m.role === 'assistant')?.id
              setVoiceReplyArmed(true)
            }}
            voicePlayback={playback.phase}
            onReplayVoice={resumeReadAloud}
          />
        </main>
      </div>
    </div>
  )
}
