/**
 * The history sidebar.
 *
 * Collapsible, because a chat transcript wants the width more than a list of
 * titles does. The collapsed state persists, so the choice sticks between
 * visits rather than resetting every reload.
 */

import { useCallback } from 'react'

import type { ConversationSummary } from '@/lib/types'

import { ChevronLeft, ChevronRight, Plus, Trash } from '@/icons'

interface SidebarProps {
  open: boolean
  onToggle: () => void
  conversations: ConversationSummary[]
  activeId: string | null
  loading: boolean
  error: string | null
  onSelect: (id: string) => void
  onNew: () => void
  onDelete: (id: string) => void
  onClearAll: () => void
}

/** "3 hours ago" beats a timestamp for a list you scan. */
function relativeTime(seconds: number): string {
  const elapsed = Date.now() / 1000 - seconds
  if (elapsed < 60) return 'just now'
  if (elapsed < 3600) return `${Math.floor(elapsed / 60)}m ago`
  if (elapsed < 86400) return `${Math.floor(elapsed / 3600)}h ago`
  if (elapsed < 604800) return `${Math.floor(elapsed / 86400)}d ago`
  return new Date(seconds * 1000).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
  })
}

export function Sidebar({
  open,
  onToggle,
  conversations,
  activeId,
  loading,
  error,
  onSelect,
  onNew,
  onDelete,
  onClearAll,
}: SidebarProps) {
  /**
   * Deleting one conversation cannot be undone either, and its button now
   * sits on every row rather than appearing under the cursor — which makes a
   * misclick both easier and permanent. So it asks, the same as clearing the
   * lot does.
   */
  const confirmDelete = useCallback(
    (id: string, title: string) => {
      if (window.confirm(`Delete “${title}”? This cannot be undone.`)) {
        onDelete(id)
      }
    },
    [onDelete],
  )

  const confirmClearAll = useCallback(() => {
    if (conversations.length === 0) return
    const plural = conversations.length === 1 ? '' : 's'
    if (
      window.confirm(
        `Delete all ${conversations.length} conversation${plural}? This cannot be undone.`,
      )
    ) {
      onClearAll()
    }
  }, [conversations.length, onClearAll])

  if (!open) {
    return (
      <div className="sidebar sidebar--collapsed">
        <div className="sidebar__rail">
          <button
            type="button"
            className="icon-button"
            onClick={onToggle}
            title="Show chat history"
            aria-label="Show chat history"
            aria-expanded={false}
          >
            <ChevronRight />
          </button>
        </div>
        <div className="sidebar__rail-body">
          <button
            type="button"
            className="icon-button"
            onClick={onNew}
            title="New chat"
            aria-label="New chat"
          >
            <Plus />
          </button>
        </div>
      </div>
    )
  }

  return (
    <aside className="sidebar" aria-label="Chat history">
      <div className="sidebar__head">
        <button type="button" className="button button--primary sidebar__new" onClick={onNew}>
          <Plus />
          <span className="button__label">New chat</span>
        </button>
        <button
          type="button"
          className="icon-button"
          onClick={onToggle}
          title="Hide chat history"
          aria-label="Hide chat history"
          aria-expanded
        >
          <ChevronLeft />
        </button>
      </div>

      {/* The count belongs beside the label rather than in the list: it says
          how long the list is without the reader having to scroll it. */}
      <div className="sidebar__section">
        <span className="sidebar__section-label">Chats</span>
        {conversations.length > 0 && (
          <span className="sidebar__section-count">{conversations.length}</span>
        )}
      </div>

      <nav className="sidebar__list">
        {loading && <p className="sidebar__empty">Loading…</p>}

        {!loading && error && <p className="sidebar__empty">{error}</p>}

        {!loading && !error && conversations.length === 0 && (
          <p className="sidebar__empty">
            No conversations yet. Ask something and it will be saved here.
          </p>
        )}

        {conversations.map((conversation) => {
          const active = conversation.conversation_id === activeId

          return (
            <div
              key={conversation.conversation_id}
              className={active ? 'chat-row chat-row--active' : 'chat-row'}
            >
              <button
                type="button"
                className="chat-row__open"
                onClick={() => onSelect(conversation.conversation_id)}
                title={conversation.title}
                aria-current={active ? 'page' : undefined}
              >
                <span className="chat-row__title">{conversation.title}</span>
                <span className="chat-row__meta">{relativeTime(conversation.updated_at)}</span>
              </button>

              <button
                type="button"
                className="chat-row__delete"
                onClick={() =>
                  confirmDelete(conversation.conversation_id, conversation.title)
                }
                title="Delete this conversation"
                aria-label={`Delete ${conversation.title}`}
              >
                <Trash />
              </button>
            </div>
          )
        })}
      </nav>

      {conversations.length > 0 && (
        <footer className="sidebar__foot">
          <button
            type="button"
            className="button sidebar__clear"
            onClick={confirmClearAll}
            title="Delete every saved conversation"
          >
            <Trash />
            <span className="button__label">Clear all history</span>
          </button>
        </footer>
      )}
    </aside>
  )
}
