/**
 * The state of the Models page.
 *
 * Three kinds of work, deliberately kept apart:
 *
 *   READING is cheap and repeatable. Every write returns the whole new status,
 *   so the page never has to guess what its own click did.
 *
 *   CHOOSING and REMOVING are quick, and the model they act on is remembered
 *   in `busy` so only that row goes quiet rather than the whole page.
 *
 *   INSTALLING is minutes long and streams. It is the one thing here that
 *   survives longer than a click, so it gets its own state, its own abort
 *   controller, and a refresh at the end.
 *
 * Only one install runs at a time. Ollama would queue a second one, but two
 * progress bars sharing one line of status text is a worse page than a
 * disabled button.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { activateModel, fetchModels, installModel, removeModel } from '@/lib/api'
import { CacheKey, dropCache } from '@/lib/cache'
import type { ModelsStatus } from '@/lib/types'

/** A download in flight. */
export interface Install {
  name: string
  /** Ollama's own words: "pulling manifest", "verifying sha256 digest"… */
  status: string
  percent: number | null
  completed: number | null
  total: number | null
}

export interface UseModels {
  status: ModelsStatus | null
  loading: boolean
  error: string | null
  /** A failed click, said next to the page rather than replacing it. */
  actionError: string | null
  /** The model a click is currently acting on. */
  busy: string | null
  install: Install | null
  refresh: () => void
  activate: (provider: string, model: string) => void
  remove: (name: string) => void
  startInstall: (name: string) => void
  cancelInstall: () => void
}

function reason(caught: unknown, fallback: string): string {
  return caught instanceof Error ? caught.message : fallback
}

export function useModels(): UseModels {
  const [status, setStatus] = useState<ModelsStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [install, setInstall] = useState<Install | null>(null)

  const readRef = useRef<AbortController | null>(null)
  const installRef = useRef<AbortController | null>(null)

  const read = useCallback(async () => {
    readRef.current?.abort()
    const controller = new AbortController()
    readRef.current = controller

    try {
      const next = await fetchModels(controller.signal)
      setStatus(next)
      setError(null)
    } catch (caught) {
      if (controller.signal.aborted) return
      setError(reason(caught, 'Could not reach the backend.'))
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }, [])

  useEffect(() => {
    void read()
    return () => {
      readRef.current?.abort()
      installRef.current?.abort()
    }
  }, [read])

  const refresh = useCallback(() => {
    setLoading(true)
    void read()
  }, [read])

  /**
   * Run a write and adopt the status it returns.
   *
   * The health badge in the header is cached, and it names the model. Changing
   * the model without dropping that entry leaves the rest of the app claiming
   * the old one for up to a minute.
   */
  const write = useCallback(
    async (name: string, action: () => Promise<ModelsStatus>, fallback: string) => {
      setBusy(name)
      setActionError(null)
      try {
        setStatus(await action())
        dropCache(CacheKey.health)
      } catch (caught) {
        setActionError(reason(caught, fallback))
      } finally {
        setBusy(null)
      }
    },
    [],
  )

  const activate = useCallback(
    (provider: string, model: string) => {
      void write(
        model || provider,
        () => activateModel(provider, model),
        'Could not switch model.',
      )
    },
    [write],
  )

  const remove = useCallback(
    (name: string) => {
      void write(name, () => removeModel(name), `Could not remove ${name}.`)
    },
    [write],
  )

  const startInstall = useCallback(
    (name: string) => {
      const wanted = name.trim()
      if (!wanted || installRef.current) return

      const controller = new AbortController()
      installRef.current = controller

      setActionError(null)
      setInstall({ name: wanted, status: 'starting', percent: null, completed: null, total: null })

      void (async () => {
        try {
          for await (const event of installModel(wanted, controller.signal)) {
            if (event.type === 'progress') {
              setInstall({
                name: wanted,
                status: event.status,
                percent: event.percent,
                completed: event.completed,
                total: event.total,
              })
            } else if (event.type === 'error') {
              setActionError(event.message)
            }
          }
        } catch (caught) {
          if (!controller.signal.aborted) {
            setActionError(reason(caught, `Could not install ${wanted}.`))
          }
        } finally {
          installRef.current = null
          setInstall(null)
          // Whether it finished, failed or was cancelled, what is on disk has
          // probably changed. Ask rather than assume.
          void read()
          dropCache(CacheKey.health)
        }
      })()
    },
    [read],
  )

  const cancelInstall = useCallback(() => {
    installRef.current?.abort()
  }, [])

  return {
    status,
    loading,
    error,
    actionError,
    busy,
    install,
    refresh,
    activate,
    remove,
    startInstall,
    cancelInstall,
  }
}
