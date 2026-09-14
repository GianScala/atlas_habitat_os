/**
 * Connectors: the documents the assistant may read.
 *
 * Telemetry answers what the habitat is doing. Some questions are not telemetry
 * at all: the emergency numbers, the procedure for a pressure drop, who is on
 * call. Those live in documents, and this is where a crew attaches them.
 *
 * Uploading and connecting are separate. A document in the list is inert;
 * only a connected one is searched. That is what makes it safe to keep a draft
 * procedure around without the assistant quoting it as current.
 *
 * Everything happens on this machine: the file is stored locally, the passages
 * are indexed locally, and the embeddings come from the local model runtime.
 * Nothing is uploaded anywhere and nothing costs anything.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { ErrorBanner } from '@/components/ErrorBanner'
import { Check, Chip, Plus, Trash, Warning } from '@/icons'
import {
  connectDocument,
  deleteDocument,
  fetchDocuments,
  uploadDocument,
} from '@/lib/api'
import type { DocumentList, KnowledgeDocument } from '@/lib/types'

export function ConnectorsSection() {
  const [data, setData] = useState<DocumentList | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [over, setOver] = useState(false)
  const input = useRef<HTMLInputElement>(null)

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      setData(await fetchDocuments(signal))
      setError(null)
    } catch (cause) {
      if ((cause as Error)?.name === 'AbortError') return
      setError((cause as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal)
    return () => controller.abort()
  }, [load])

  const upload = useCallback(async (files: FileList | null) => {
    if (!files?.length) return
    setBusy('upload')
    setError(null)
    try {
      // One at a time, so a failure names the file that caused it.
      for (const file of Array.from(files)) {
        setData(await uploadDocument(file))
      }
    } catch (cause) {
      setError((cause as Error).message)
    } finally {
      setBusy(null)
      if (input.current) input.current.value = ''
    }
  }, [])

  const toggle = useCallback(async (document: KnowledgeDocument) => {
    setBusy(document.id)
    try {
      setData(await connectDocument(document.id, !document.connected))
      setError(null)
    } catch (cause) {
      setError((cause as Error).message)
    } finally {
      setBusy(null)
    }
  }, [])

  const remove = useCallback(async (document: KnowledgeDocument) => {
    setBusy(document.id)
    try {
      setData(await deleteDocument(document.id))
      setError(null)
    } catch (cause) {
      setError((cause as Error).message)
    } finally {
      setBusy(null)
    }
  }, [])

  const status = data?.status

  return (
    <div className="naming">
      <p className="naming__intro">
        Files and indexes are stored on the ATLAS server. Retrieved passages are sent to your selected AI provider, including the cloud when selected.
      </p>

      {error && <ErrorBanner message={error} kind="request" />}
      {loading && <p className="dashboard__status">Reading the knowledge base…</p>}

      {status && (
        <>
          <input
            ref={input}
            type="file"
            id="connector-file"
            className="drop__input"
            multiple
            accept=".pdf,.docx,.csv,.txt,.md"
            onChange={(event) => void upload(event.target.files)}
            disabled={busy !== null}
          />
          <label
            htmlFor="connector-file"
            className={[
              'drop',
              over ? 'drop--over' : '',
              busy === 'upload' ? 'drop--busy' : '',
            ]
              .filter(Boolean)
              .join(' ')}
            onDragOver={(event) => {
              event.preventDefault()
              setOver(true)
            }}
            onDragLeave={() => setOver(false)}
            onDrop={(event) => {
              event.preventDefault()
              setOver(false)
              void upload(event.dataTransfer.files)
            }}
          >
            <Plus size={22} className="drop__mark" />
            <span className="drop__title">
              {busy === 'upload' ? 'Reading and indexing…' : 'Add a document'}
            </span>
            <span className="drop__hint">
              Drop a file here or click to browse. {status.accepts}. Up to{' '}
              {status.max_mb} MB.
            </span>
          </label>

          {/* Said once, plainly: the difference between a good index and a
              workable one, and the single command that upgrades it. */}
          {!status.embeddings_ready && (
            <p className="notice" role="status">
              <Warning size={14} className="notice__mark" />
              <span>
                Matching on shared words, not meaning. {status.embeddings_detail}{' '}
                It runs locally and is free.
              </span>
            </p>
          )}

          {data.documents.length === 0 ? (
            <div className="panel">
              <div className="empty">
                <Chip size={26} className="empty__mark" />
                <p className="empty__title">Nothing attached yet</p>
                <p className="empty__detail">
                  Add a procedure, a contact sheet or a checklist. The assistant
                  searches it and cites it alongside the telemetry.
                </p>
              </div>
            </div>
          ) : (
            <section className="panel">
              <div className="panel__head">
                <h3 className="panel__title">Documents</h3>
                <span className="panel__count">
                  {status.connected} of {data.documents.length} connected
                </span>
              </div>

              <div className="panel__body">
                {data.documents.map((document) => (
                  <div className="doc" key={document.id}>
                    <Chip size={17} className="doc__mark" />

                    <div>
                      <span className="doc__name">{document.filename}</span>
                      <span className="doc__meta">
                        {document.kind}, {formatBytes(document.bytes)}
                      </span>
                    </div>

                    <div className="doc__index">
                      <strong>{document.chunks}</strong>
                      {document.indexing === 'vector'
                        ? 'passages, by meaning'
                        : 'passages, by words'}
                    </div>

                    <button
                      type="button"
                      className={
                        document.connected
                          ? 'doc__toggle doc__toggle--on'
                          : 'doc__toggle'
                      }
                      onClick={() => void toggle(document)}
                      disabled={busy !== null}
                      aria-pressed={document.connected}
                      title={
                        document.connected
                          ? 'The assistant can search this'
                          : 'Kept, but not searched'
                      }
                    >
                      {document.connected && <Check size={13} />}
                      {document.connected ? 'Connected' : 'Connect'}
                    </button>

                    <button
                      type="button"
                      className="naming__icon-button"
                      aria-label={`Remove ${document.filename}`}
                      onClick={() => void remove(document)}
                      disabled={busy !== null}
                    >
                      <Trash />
                    </button>
                  </div>
                ))}
              </div>
            </section>
          )}

          {status.connected > 0 && (
            <p className="drop__hint" style={{ display: 'block' }}>
              The assistant quotes connected documents and names the source, and
              says so when they do not answer.
            </p>
          )}
        </>
      )}
    </div>
  )
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
