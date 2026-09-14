/**
 * A failure the person can act on.
 *
 * Backend errors already carry a plain reason (which credential is wrong,
 * which host is unreachable), so the job here is to show it without
 * decoration and give it a heading that says whose problem it is.
 */

import { Warning } from '@/icons'

interface ErrorBannerProps {
  message: string
  kind: string
}

const TITLES: Record<string, string> = {
  auth: 'Authentication failed',
  rate_limit: 'Rate limited',
  network: 'Network problem',
  datasource: 'Habitat data unreachable',
  model: 'Model error',
  refusal: 'Not answered',
  tool_rounds_exhausted: 'Gave up',
  transport: 'Connection problem',
  backend: 'Backend error',
  ollama: 'Local model runtime',
  ollama_offline: 'Ollama is not running',
  ollama_timeout: 'The local model took too long',
  model_not_installed: 'That model is not installed',
  empty_answer: 'Nothing came back',
  max_tokens: 'Answer cut short',
}

export function ErrorBanner({ message, kind }: ErrorBannerProps) {
  return (
    <div className="error" role="alert">
      <Warning className="error__icon" />
      <div className="error__body">
        <div className="error__title">{TITLES[kind] ?? 'Something went wrong'}</div>
        <div>{message}</div>
      </div>
    </div>
  )
}
