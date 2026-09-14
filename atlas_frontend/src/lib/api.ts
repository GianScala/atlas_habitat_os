/**
 * Every call to the backend lives here.
 *
 * Components never call `fetch` themselves, so the base URL, error shape, and
 * streaming mechanics have exactly one definition.
 */

import { postEventStream, SseError } from './sse'
import type {
  AssistantSettings,
  ConversationDetail,
  ConversationSummary,
  Dashboard,
  DocumentList,
  ExtraWrite,
  HealthStatus,
  LabelCatalogue,
  Logbook,
  MeterRound,
  MeterSpec,
  MissionPlan,
  ModelsStatus,
  PlanUpdate,
  PullEvent,
  RangeOption,
  ReadingWrite,
  StreamEvent,
  StyleKey,
  Suggestion,
  Tracking,
  VoiceStatus,
  VoiceTranscription,
} from './types'

/** Empty by default: the Vite dev server proxies /api to the backend. */
const BASE = import.meta.env.VITE_API_BASE_URL ?? ''

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { Accept: 'application/json' },
    signal,
  })

  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const body = (await response.json()) as { detail?: string }
      if (body.detail) detail = body.detail
    } catch {
      // Keep the status line.
    }
    throw new SseError(detail, response.status)
  }

  return (await response.json()) as T
}

/**
 * A write, with the backend's own refusal preserved.
 *
 * The mission plan validates what it is given and explains what it did not
 * like — "the day-start offset must be a whole number of hours". Collapsing
 * that to "HTTP 400" in transit would leave the editor with nothing useful to
 * show, so the detail is unwrapped here exactly as `getJson` unwraps it.
 */
async function sendJson<T>(path: string, method: string, body?: unknown): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const parsed = (await response.json()) as { detail?: string }
      if (parsed.detail) detail = parsed.detail
    } catch {
      // Keep the status line.
    }
    throw new SseError(detail, response.status)
  }

  return (await response.json()) as T
}

/** Can the backend actually reach the habitat database right now? */
export function fetchDatasourceHealth(signal?: AbortSignal): Promise<HealthStatus> {
  return getJson<HealthStatus>('/api/health/datasource', signal)
}

export function fetchSuggestions(signal?: AbortSignal): Promise<Suggestion[]> {
  return getJson<Suggestion[]>('/api/meta/suggestions', signal)
}

/* --- Local voice -------------------------------------------------------- */

export function fetchVoiceStatus(signal?: AbortSignal): Promise<VoiceStatus> {
  return getJson<VoiceStatus>('/api/voice/status', signal)
}

export async function transcribeVoice(recording: Blob, signal?: AbortSignal): Promise<VoiceTranscription> {
  const body = new FormData()
  body.append('file', recording, 'recording')
  const response = await fetch(`${BASE}/api/voice/transcribe`, { method: 'POST', body, signal })
  if (!response.ok) {
    const parsed = await response.json().catch(() => ({})) as { detail?: string }
    throw new SseError(parsed.detail ?? `HTTP ${response.status}`, response.status)
  }
  return (await response.json()) as VoiceTranscription
}

export function saveVoiceSettings(voice: string, language: string): Promise<VoiceStatus> {
  return sendJson<VoiceStatus>('/api/voice/settings', 'PUT', { voice, language })
}

export async function synthesizeVoice(text: string, signal?: AbortSignal, voice?: string): Promise<Blob> {
  const response = await fetch(`${BASE}/api/voice/synthesize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'audio/wav' },
    body: JSON.stringify({ text, voice }),
    signal,
  })
  if (!response.ok) {
    const parsed = await response.json().catch(() => ({})) as { detail?: string }
    throw new SseError(parsed.detail ?? `HTTP ${response.status}`, response.status)
  }
  return response.blob()
}

/** Ask a question. Yields events as the answer is produced. */
export function askQuestion(
  message: string,
  conversationId: string | null,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  return postEventStream<StreamEvent>(
    `${BASE}/api/chat`,
    { message, conversation_id: conversationId },
    { signal },
  )
}

/* --- Stored chat history ------------------------------------------------ */

/** Every stored thread, most recently active first. */
export function fetchConversations(signal?: AbortSignal): Promise<ConversationSummary[]> {
  return getJson<ConversationSummary[]>('/api/conversations', signal)
}

/** One thread, with its transcript, ready to render. */
export function fetchConversation(
  conversationId: string,
  signal?: AbortSignal,
): Promise<ConversationDetail> {
  return getJson<ConversationDetail>(`/api/conversations/${conversationId}`, signal)
}

/** Forget one thread. */
export async function deleteConversation(conversationId: string): Promise<void> {
  const response = await fetch(`${BASE}/api/conversations/${conversationId}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    throw new SseError(`Could not delete the conversation (HTTP ${response.status}).`)
  }
}

/** Forget every thread. The interface confirms before calling this. */
export async function deleteAllConversations(): Promise<void> {
  const response = await fetch(`${BASE}/api/conversations`, { method: 'DELETE' })
  if (!response.ok) {
    throw new SseError(`Could not clear the history (HTTP ${response.status}).`)
  }
}

/* --- Models -------------------------------------------------------------- */

/** What is installed, what is offered, and which model is answering. */
export function fetchModels(signal?: AbortSignal): Promise<ModelsStatus> {
  return getJson<ModelsStatus>('/api/models', signal)
}

/** Answer questions with this model from now on. */
export function activateModel(provider: string, model: string): Promise<ModelsStatus> {
  return sendJson<ModelsStatus>('/api/models/active', 'POST', { provider, model })
}

/** Delete a model from disk. */
export function removeModel(name: string): Promise<ModelsStatus> {
  return sendJson<ModelsStatus>('/api/models/remove', 'POST', { name })
}

/**
 * Download a model, yielding progress as it arrives.
 *
 * Several gigabytes over a stream rather than one long request: a page that
 * says "pulling 4.7 GB, 62%" is bearable, and the same wait behind a spinner
 * is indistinguishable from a hang.
 */
export function installModel(name: string, signal?: AbortSignal): AsyncGenerator<PullEvent> {
  return postEventStream<PullEvent>(`${BASE}/api/models/install`, { name }, { signal })
}

/* --- Dashboard ---------------------------------------------------------- */

export function fetchRanges(signal?: AbortSignal): Promise<RangeOption[]> {
  return getJson<RangeOption[]>('/api/dashboard/ranges', signal)
}

export function fetchDashboard(range: string, signal?: AbortSignal): Promise<Dashboard> {
  return getJson<Dashboard>(`/api/dashboard?range=${encodeURIComponent(range)}`, signal)
}

/* --- Mission plan ------------------------------------------------------- */

/** The mission as declared, its ceilings, and its extras. */
export function fetchMissionPlan(signal?: AbortSignal): Promise<MissionPlan> {
  return getJson<MissionPlan>('/api/mission/plan', signal)
}

/**
 * The day plan, what was drawn against it, and what the days ahead now allow.
 *
 * No parameters: the window is the mission, and the mission is stored. The
 * old history-length argument selected how far back to draw, which is a
 * question that stops meaning anything once the plan has its own start date.
 */
export function fetchTracking(signal?: AbortSignal): Promise<Tracking> {
  return getJson<Tracking>('/api/mission/tracking', signal)
}

/**
 * Declare or change the mission.
 *
 * Anything left out of `change` keeps the value it had, so saving a ceiling
 * cannot revert a date edited somewhere else in the meantime. The updated plan
 * comes back, so the caller never has to guess what was stored.
 */
export function saveMissionPlan(change: PlanUpdate): Promise<MissionPlan> {
  return sendJson<MissionPlan>('/api/mission/plan', 'PUT', change)
}

/** Forget the mission, every ceiling, and every extra. */
export function resetMissionPlan(): Promise<MissionPlan> {
  return sendJson<MissionPlan>('/api/mission/plan/reset', 'POST')
}

/*
 * The three extras calls all return the WHOLE plan rather than the one row
 * they touched. Booking an extra moves every other day's allowance — the
 * ceiling did not change, so what is left for an ordinary day did — and a
 * response carrying only the new row would leave the page showing allowances
 * computed against a plan that no longer exists.
 */

export function addExtra(extra: ExtraWrite): Promise<MissionPlan> {
  return sendJson<MissionPlan>('/api/mission/extras', 'POST', extra)
}

export function saveExtra(id: string, extra: ExtraWrite): Promise<MissionPlan> {
  return sendJson<MissionPlan>(`/api/mission/extras/${id}`, 'PUT', extra)
}

export function deleteExtra(id: string): Promise<MissionPlan> {
  return sendJson<MissionPlan>(`/api/mission/extras/${id}`, 'DELETE')
}

/* --- The crew's meter log ------------------------------------------------ */

/** The sheet, the consumption derived from it, and how that distributes. */
export function fetchLogbook(signal?: AbortSignal): Promise<Logbook> {
  return getJson<Logbook>('/api/mission/log', signal)
}

/**
 * Record one meter reading, or clear the box by sending a null value.
 *
 * The whole log comes back rather than the one box, for the same reason the
 * extras calls return the whole plan: a reading closes the block before it and
 * opens the block after it, so a response carrying only the row that changed
 * would leave two days on screen derived from readings that no longer exist.
 */
export function saveReading(entry: ReadingWrite): Promise<Logbook> {
  return sendJson<Logbook>('/api/mission/log/reading', 'PUT', entry)
}

/** Forget the meter log — one resource's rounds, or every one of them. */
export function clearLogbook(resource?: string): Promise<Logbook> {
  const query = resource ? `?resource=${encodeURIComponent(resource)}` : ''
  return sendJson<Logbook>(`/api/mission/log/clear${query}`, 'POST')
}

/* --- Assistant style ----------------------------------------------------- */

export function fetchAssistantStyle(signal?: AbortSignal): Promise<AssistantSettings> {
  return getJson<AssistantSettings>('/api/settings/assistant', signal)
}

/** Answer in this register from now on. Takes effect on the next question. */
export function saveAssistantStyle(
  style: StyleKey,
  custom?: string,
): Promise<AssistantSettings> {
  return sendJson<AssistantSettings>('/api/settings/assistant', 'PUT', { style, custom })
}

export { SseError }

/* --- Naming -------------------------------------------------------------- */

export function fetchLabels(signal?: AbortSignal): Promise<LabelCatalogue> {
  return getJson<LabelCatalogue>('/api/naming/labels', signal)
}

/** Rename one thing. An empty label restores the name it had before. */
export function setLabel(
  kind: 'location' | 'measurement',
  key: string,
  label: string,
): Promise<LabelCatalogue> {
  return sendJson<LabelCatalogue>('/api/naming/labels', 'PUT', { kind, key, label })
}

export function fetchMeterRound(signal?: AbortSignal): Promise<MeterRound> {
  return getJson<MeterRound>('/api/naming/meters', signal)
}

/** Replace one resource's round, in the order it is walked. */
export function saveMeterRound(
  resource: 'power' | 'water',
  meters: MeterSpec[],
): Promise<MeterRound> {
  return sendJson<MeterRound>(`/api/naming/meters/${resource}`, 'PUT', { meters })
}

/** Hand the round back to the habitat profile's list. */
export function resetMeterRound(): Promise<MeterRound> {
  return sendJson<MeterRound>('/api/naming/meters/reset', 'POST')
}

/* --- Connectors ---------------------------------------------------------- */

export function fetchDocuments(signal?: AbortSignal): Promise<DocumentList> {
  return getJson<DocumentList>('/api/connectors/documents', signal)
}

/** Upload one document. It is extracted, indexed locally, and connected. */
export async function uploadDocument(file: File): Promise<DocumentList> {
  const body = new FormData()
  body.append('file', file)

  const response = await fetch(`${BASE}/api/connectors/documents`, {
    method: 'POST',
    body,
  })

  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const parsed = (await response.json()) as { detail?: string }
      if (parsed.detail) detail = parsed.detail
    } catch {
      // Keep the status line.
    }
    throw new SseError(detail, response.status)
  }
  return (await response.json()) as DocumentList
}

/** Attach or detach one document. Detaching keeps it, unsearched. */
export function connectDocument(id: string, connected: boolean): Promise<DocumentList> {
  return sendJson<DocumentList>(`/api/connectors/documents/${id}`, 'PUT', { connected })
}

export function deleteDocument(id: string): Promise<DocumentList> {
  return sendJson<DocumentList>(`/api/connectors/documents/${id}`, 'DELETE')
}
