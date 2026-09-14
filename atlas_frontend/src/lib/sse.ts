/**
 * A minimal server-sent-events reader over `fetch`.
 *
 * The browser's own `EventSource` only does GET and cannot send a JSON body,
 * so asking a question needs this instead. The backend puts each event on a
 * single `data:` line, which keeps the parsing here honest: buffer until a
 * blank line, take the `data:` payload, parse it.
 */

export interface SseOptions {
  signal?: AbortSignal
}

/** Anything the server said that was not a clean HTTP or parse failure. */
export class SseError extends Error {
  readonly status: number

  constructor(message: string, status = 0) {
    super(message)
    this.name = 'SseError'
    this.status = status
  }
}

/**
 * POST `body` to `url` and yield each event's parsed JSON payload.
 *
 * Yields as an async generator so the caller can `for await` and update the
 * interface token by token.
 */
export async function* postEventStream<T>(
  url: string,
  body: unknown,
  options: SseOptions = {},
): AsyncGenerator<T> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal: options.signal,
  })

  if (!response.ok) {
    throw new SseError(await describeFailure(response), response.status)
  }
  if (!response.body) {
    throw new SseError('The server returned no response body.', response.status)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        buffer += decoder.decode()
        if (buffer.trim()) throw new SseError('The event stream ended mid-event. Try again.')
        break
      }

      buffer += decoder.decode(value, { stream: true })

      // Events are separated by a blank line. Anything after the last
      // separator is a partial event; keep it for the next chunk.
      let separator = /\r?\n\r?\n/.exec(buffer)
      while (separator !== null) {
        const frame = buffer.slice(0, separator.index)
        buffer = buffer.slice(separator.index + separator[0].length)

        const payload = extractData(frame)
        if (payload !== null) {
          yield JSON.parse(payload) as T
        }
        separator = /\r?\n\r?\n/.exec(buffer)
      }
    }
  } finally {
    // Cancel unread data when a consumer stops early, then release the lock.
    try { await reader.cancel() } catch { /* The transport may already be aborted. */ }
    reader.releaseLock()
  }
}

/** The `data:` payload of one frame, or null for comments and keep-alives. */
function extractData(frame: string): string | null {
  const lines = frame.split(/\r?\n/)
  const data: string[] = []

  for (const line of lines) {
    if (line.startsWith(':')) continue // a comment, e.g. the stream prelude
    if (line.startsWith('data:')) {
      data.push(line.slice(5).trimStart())
    }
  }

  return data.length > 0 ? data.join('\n') : null
}

/** Turn a failed response into the clearest message we can manage. */
async function describeFailure(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string }
    if (body.detail) return body.detail
  } catch {
    // Not JSON — fall through to the status line.
  }
  return `Request failed with HTTP ${response.status}.`
}
