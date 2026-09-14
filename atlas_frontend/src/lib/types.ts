/**
 * The wire contract, mirroring `atlas_backend/app/schemas/chat.py`.
 * Keep the two in step — the backend is the source of truth.
 */

export interface ToolCall {
  id: string
  name: string
  input: Record<string, unknown>
}

export interface ToolResult {
  id: string
  name: string
  ok: boolean
  has_data: boolean
  queries: string[]
  detail: string | null
}

/** Which model produced an answer. Carried on the stream's `start` event. */
export interface AnsweredBy {
  provider: string
  model: string
  model_label: string
  /** True when nothing about this answer left the machine. */
  local: boolean
}

/** Every event the chat stream can emit, discriminated by `type`. */
export type StreamEvent =
  | ({ type: 'start'; conversation_id: string; title: string } & AnsweredBy)
  | { type: 'thinking_delta'; text: string }
  | { type: 'text_delta'; text: string }
  | { type: 'tool_call'; call: ToolCall }
  | { type: 'tool_result'; result: ToolResult }
  | { type: 'sources'; queries: string[] }
  | { type: 'done'; conversation_id: string; stop_reason: string | null }
  | { type: 'error'; message: string; kind: string; recoverable: boolean }

/**
 * One query the assistant ran, as the interface shows it: the call and its
 * outcome joined together.
 */
export interface TraceStep {
  id: string
  name: string
  input: Record<string, unknown>
  status: 'running' | 'ok' | 'empty' | 'failed'
  queries: string[]
  detail: string | null
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  /** The rendered answer. Grows as tokens arrive. */
  content: string
  /** Summarised reasoning, shown collapsed. */
  thinking: string
  /** Queries run while producing this answer. */
  trace: TraceStep[]
  /** The InfluxQL behind the answer, for the provenance footer. */
  sources: string[]
  error: { message: string; kind: string } | null
  /** True while the answer is still streaming. */
  streaming: boolean
  createdAt: number
  /**
   * Which model wrote this particular answer. Per message rather than per
   * thread: the model can be changed between two questions, and an answer
   * three turns up was not necessarily produced by the one selected now.
   */
  answeredBy: AnsweredBy | null
  /**
   * How long the answer took, wall-clock, from the question leaving to the
   * stream ending. Null while it is still running, and on a turn restored
   * from the backend — the transcript endpoint does not carry it.
   */
  durationMs: number | null
}

export interface HealthStatus {
  status: string
  /** The model in force, e.g. "qwen3:8b". */
  model: string
  provider: string
  model_label: string
  local: boolean
  datasource_configured: boolean
  /** The model could answer a question right now. */
  model_ready: boolean
  /** Why not, when it could not. */
  model_detail: string | null
  datasource_ok: boolean | null
  datasource_detail: string | null
  measurement_count: number | null
}

export interface Suggestion {
  label: string
  question: string
}

export interface VoiceStatus {
  transcription_ready: boolean
  synthesis_ready: boolean
  transcription_detail: string
  synthesis_detail: string
  max_recording_mb: number
  voices: { id: string; label: string }[]
  active_voice: string
  language: string
}

export interface VoiceTranscription {
  text: string
  processing_ms: number
}

/* --- Stored chat history ------------------------------------------------ */

export interface ConversationSummary {
  conversation_id: string
  title: string
  created_at: number
  updated_at: number
  message_count: number
}

/** One turn of a reopened thread, as the backend projects it. */
export interface TranscriptMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  thinking: string
  trace: TraceStep[]
  sources: string[]
}

export interface ConversationDetail extends ConversationSummary {
  messages: TranscriptMessage[]
}

/* --- Models -------------------------------------------------------------- */

/**
 * Mirrors `atlas_backend/app/schemas/models.py`.
 *
 * The flag that matters most on this page is `supports_tools`. ATLAS answers
 * by querying InfluxDB; a model that cannot call a tool cannot query anything,
 * and will write a confident invented answer instead. `capabilities_measured`
 * says whether that flag came from Ollama looking at the weights on disk or
 * from our own expectation of a model we have not installed yet.
 */
export interface ModelInfo {
  name: string
  description: string
  size_note: string
  badge: string | null
  installed: boolean
  size_bytes: number | null
  parameter_size: string | null
  quantisation: string | null
  supports_tools: boolean
  supports_thinking: boolean
  capabilities_measured: boolean
  active: boolean
  in_catalogue: boolean
}

export interface ProviderInfo {
  key: string
  label: string
  description: string
  available: boolean
  detail: string | null
  model: string
  active: boolean
  local: boolean
}

/** A model held in memory right now — as opposed to merely on disk. */
export interface LoadedModel {
  name: string
  bytes_resident: number
  context_length: number | null
  expires_at: string | null
}

export interface RuntimeStatus {
  reachable: boolean
  host: string
  version: string | null
  detail: string | null
  models_dir: string
  installed_count: number
  loaded: LoadedModel[]
}

export interface ModelsStatus {
  provider: string
  model: string
  label: string
  local: boolean
  ready: boolean
  warning: string | null
  providers: ProviderInfo[]
  runtime: RuntimeStatus
  models: ModelInfo[]
}

/** Progress while a model downloads. */
export type PullEvent =
  | { type: 'start'; name: string }
  | {
      type: 'progress'
      status: string
      completed: number | null
      total: number | null
      percent: number | null
    }
  | { type: 'done'; name: string; message: string }
  | { type: 'error'; message: string; kind: string }

/* --- Dashboard ---------------------------------------------------------- */

export interface RangeOption {
  key: string
  label: string
  minutes: number
  bucket_minutes: number
}

export interface PanelPoint {
  t: string
  v: number
}

export interface PanelSeries {
  key: string
  label: string
  points: PanelPoint[]
}

export type ChartKind = 'line' | 'area' | 'bar'

export interface Panel {
  id: string
  title: string
  subtitle: string
  group: string
  chart: ChartKind
  mode: 'mean' | 'delta' | 'drawdown' | 'fillup'
  /** Points are a running total across the window, not one bucket each. */
  cumulative: boolean
  unit: string
  unit_source: 'known' | 'unknown'
  unit_note: string | null
  measurement: string
  field: string
  query: string
  bucket_minutes: number
  series: PanelSeries[]
  /** Set when this panel alone failed; the rest of the page still renders. */
  error: string | null
}

export interface Dashboard {
  range: string
  range_label: string
  panels: Panel[]
}

/* --- Mission plan ------------------------------------------------------- */

/**
 * Mirrors `atlas_backend/app/schemas/mission.py`.
 *
 * The one part of this contract carrying numbers no sensor produced: a plan is
 * a decision. Which is why `source` rides along with every ceiling, and why
 * `planned` and `actual` are never merged into one field.
 */

/** Who decided a figure: the crew, or the figure this repository shipped. */
export type TargetSource = 'crew' | 'default'

/** How an extra recurs: once on a mission day, or on every one of them. */
export type ExtraKind = 'once' | 'daily'

/** Where the mission sits relative to now. */
export type MissionState = 'before' | 'running' | 'after'

export interface MissionWindow {
  is_declared: boolean
  name: string
  start: string | null
  /** Derived from the start and the length; never entered separately. */
  end: string | null
  days: number | null
  state: MissionState
  /** Which mission day today is, or null outside the mission. */
  day_index: number | null
  /** `MD-14`. */
  day_code: string | null
  days_elapsed: number
  days_remaining: number | null
  elapsed_fraction: number
  cycle_number: number | null
  cycle_first: number | null
  cycle_last: number | null
  /** The habitat's calendar date, which is not always the machine's. */
  today: string
}

export interface ExtraEntry {
  id: string
  resource: string
  label: string
  amount: number
  kind: ExtraKind
  on_date: string | null
  mission_day: number | null
  day_code: string | null
  note: string
  /** The mission's dates moved out from under it; it now budgets nothing. */
  stranded: boolean
  updated_at: number
}

/** An extra as the interface sends it — a mission day OR a date, not both. */
export interface ExtraWrite {
  resource: string
  label: string
  amount: number
  kind: ExtraKind
  on_date?: string | null
  mission_day?: number | null
  note?: string
}

export interface PlanResource {
  key: string
  label: string
  unit: string
  /** The most that may be drawn across the whole mission. */
  total: number | null
  source: TargetSource
  /** A ceiling to offer in the setup form. Never stored, never computed with. */
  suggested_total: number | null
  suggested_daily: number | null
  extras: ExtraEntry[]
}

export interface MissionPlan {
  day_start_offset_minutes: number
  day_start_label: string
  mission: MissionWindow
  updated_at: number | null
  is_all_default: boolean
  default_note: string
  warnings: string[]
  resources: PlanResource[]
}

/** A change to the plan. Anything left out keeps the value it had. */
export interface PlanUpdate {
  name?: string
  start?: string
  days?: number
  totals?: Record<string, number | null>
  day_start_offset_minutes?: number
}

/**
 * nominal   on course to finish inside the allowance
 * caution   still inside it, on course to pass it
 * over      past it already
 * unset     no ceiling set for this resource
 * no_data   the sensors did not cover this window
 */
export type BudgetStatus = 'nominal' | 'caution' | 'over' | 'unset' | 'no_data'

/**
 * over     drew more than the day allowed
 * under    drew less
 * on_plan  within tolerance — and the only verdict a day still running can get
 * no_data  the sensors did not cover it
 * pending  not reached yet
 */
export type DayStatus = 'over' | 'under' | 'on_plan' | 'no_data' | 'pending'

/** Where a mission day sits relative to now. */
export type DayState = 'past' | 'today' | 'future'

export interface Budget {
  horizon: string
  label: string
  days: number
  period_start: string
  period_end: string
  first_code: string | null
  last_code: string | null
  /** How much of the window has passed, 0…1. */
  elapsed_fraction: number
  used: number | null
  /** The original plan's allowance across this window. */
  target: number | null
  /** What the forward plan now allows across it. */
  revised_target: number | null
  extras: number
  source: TargetSource
  /** How much of the allowance is gone, 0…1. The "we are at 80%" figure. */
  used_fraction: number | null
  /**
   * What the plan itself expected by now — extras on their own days, not
   * smeared across the window. The line the fill is compared against.
   */
  planned_by_now: number | null
  remaining: number | null
  /** Where the window lands at the current rate. Null early on. */
  projected: number | null
  /** used / planned_by_now. Above 1 is spending faster than planned. */
  pace_ratio: number | null
  status: BudgetStatus
  days_covered: number
  days_expected: number
  note: string | null
}

export interface PlannedDay {
  index: number
  /** `MD-07`. */
  code: string
  date: string
  start: string
  state: DayState
  /** The original allowance: the flat rate plus this day's extras. */
  planned: number
  /** What the forward plan now allows. Null on a day already behind us. */
  revised: number | null
  extras: number
  extra_labels: string[]
  /** Null is a day the sensors did not cover — not a day of zero use. */
  actual: number | null
  variance: number | null
  status: DayStatus
  /** False on a day older than the lookback window, never asked about. */
  queried: boolean
}

export interface ResourceTracking {
  key: string
  label: string
  noun: string
  unit: string
  unit_source: 'known' | 'unknown'
  measurement: string
  field: string
  query: string

  total: number | null
  source: TargetSource

  /** The ceiling less every extra, spread over the mission. */
  flat_per_day: number | null
  /** What an ordinary day gets from here on. The number to act on. */
  revised_per_day: number | null
  extras_total: number
  extras_to_come: number

  consumed: number | null
  remaining: number | null
  days_measured: number
  days_uncovered: number
  /** False where the extras still booked cost more than what is left. */
  feasible: boolean
  shortfall: number

  budgets: Budget[]
  days: PlannedDay[]
  extras: ExtraEntry[]
  notes: string[]
  /** Set when this resource alone could not be read; the other still draws. */
  error: string | null
}

export interface Tracking {
  generated_at: string
  day_start_offset_minutes: number
  day_start_label: string
  mission: MissionWindow
  plan_updated_at: number | null
  plan_is_all_default: boolean
  default_note: string
  warnings: string[]
  resources: ResourceTracking[]
}

/* --- The crew's meter log ------------------------------------------------ */

/**
 * Mirrors `atlas_backend/app/schemas/logbook.py`.
 *
 * The distinction this contract is built around: a `ReadingEntry` is what
 * somebody typed off a dial, and a `BlockUsage` is what the backend worked out
 * from two of them. They are never merged into one field, for the same reason
 * `planned` and `actual` never are — one is a record, the other a derivation,
 * and a page that cannot tell them apart cannot say which of the two is wrong.
 */

/** Which round a reading was taken on. A position on the rounds, not a time. */
export type LogSlotKey = 'morning' | 'evening' | 'daily'

/**
 * ok         derived from two readings
 * open       waiting on a closing reading that has not been taken yet
 * gap        both rounds have happened and one was not written down
 * backwards  the meter appears to have counted down; both readings suspect
 */
export type BlockStatus = 'ok' | 'open' | 'gap' | 'backwards'

export interface LogMeter {
  key: string
  label: string
  /** The tag on the pipe — `2R`. Empty for the power sub-meters. */
  code: string
  group: string
  group_label: string
  stream: 'warm' | 'cold' | 'none'
}

/**
 * One position on the rounds, under two names.
 *
 * A round and the consumption it opens are different things, and one name for
 * both is what made a bar labelled "Morning round" read as "the reading taken
 * in the morning" rather than "everything drawn between the morning round and
 * the evening one".
 */
export interface LogSlot {
  key: LogSlotKey
  /** "Morning round" — the walk. Heads the column a reading is typed into. */
  label: string
  /** "Daytime" — the consumption it opens. Titles every derived figure. */
  block_label: string
  /** The span in words: "evening round to the next morning's round". */
  covers: string
}

/** One figure the crew typed off a meter face. Cumulative, never a delta. */
export interface ReadingEntry {
  meter: string
  day_index: number
  slot: LogSlotKey
  value: number
  updated_at: number
}

/** What was drawn between two readings. In the REPORTED unit — water in litres. */
export interface BlockUsage {
  meter: string
  day_index: number
  slot: LogSlotKey
  amount: number | null
  status: BlockStatus
  opens: number | null
  closes: number | null
  /** Which mission day supplies the closing reading, where one can exist. */
  closes_code: string | null
}

export interface LoggedDay {
  index: number
  code: string
  date: string
  state: DayState
  total: number | null
  blocks_logged: number
  blocks_expected: number
  /** False while any block is still waiting on its closing reading. */
  complete: boolean
}

export interface Share {
  key: string
  label: string
  code: string
  /** Set on the day/night split, where the slice is a span of hours. */
  covers: string
  amount: number
  /** Null where the window's total is zero or unknown — not zero percent. */
  share: number | null
  /** False where this meter logged nothing at all, which is not a zero. */
  logged: boolean
}

export interface LogWindow {
  key: string
  label: string
  first_code: string | null
  last_code: string | null
  days_covered: number
  days_in_window: number
  total: number | null
  per_day_mean: number | null
  complete: boolean
  meters: Share[]
  groups: Share[]
  streams: Share[]
  slots: Share[]
}

export interface LogCoverage {
  filled: number
  /** Every box on the sheet, including days the mission has not reached. */
  total: number
  /** Rounds that have already happened — the figure the crew is judged on. */
  expected: number
  expected_filled: number
}

export interface LogResource {
  key: 'power' | 'water'
  label: string
  /** What the input box takes — m³ for water, straight off the dial. */
  entry_unit: string
  /** What every figure below is reported in — litres for water. */
  unit: string
  slots: LogSlot[]
  meters: LogMeter[]
  entries: ReadingEntry[]
  usage: BlockUsage[]
  days: LoggedDay[]
  latest_day: number | null
  windows: LogWindow[]
  coverage: LogCoverage
  issues: string[]
}

export interface LogMission {
  is_declared: boolean
  name: string
  start: string | null
  end: string | null
  days: number | null
  today: string
  day_index: number | null
  day_code: string | null
}

export interface Logbook {
  generated_at: string
  day_start_label: string
  mission: LogMission
  days: LoggedDay[]
  resources: LogResource[]
}

/** One box on the sheet. A null `value` withdraws the reading. */
export interface ReadingWrite {
  resource: string
  meter: string
  day_index: number
  slot: LogSlotKey
  value: number | null
}

/* --- Assistant style ----------------------------------------------------- */

/** Mirrors `atlas_backend/app/schemas/settings.py`. */
export type StyleKey = 'concise' | 'detailed' | 'unhinged' | 'custom'

export interface AssistantStyleOption {
  key: StyleKey
  label: string
  blurb: string
}

export interface AssistantSettings {
  style: StyleKey
  /** Kept even while another style is selected, so switching back is free. */
  custom: string
  options: AssistantStyleOption[]
}

/* --- Naming: what the crew calls what the database names ----------------- */

/** One renameable thing: the database's spelling, and the crew's. */
export interface LabelEntry {
  /** The value in the database. Queries use it; renaming never changes it. */
  key: string
  /** What the interface shows. */
  label: string
  /** Where the display name came from. */
  source: 'crew' | 'profile' | 'raw'
  /** For a location: which measurements report it. */
  seen_in: string[]
}

export interface LabelCatalogue {
  /** False when no database could be read. The lists are then empty because
   *  nothing is loaded, not because the habitat has no sensors. */
  connected: boolean
  /** Why nothing could be read, when nothing could. */
  detail: string | null
  /** Which data source answered. */
  source: string
  measurements: LabelEntry[]
  locations: LabelEntry[]
}

/** One dial on the crew's hand-read round. */
export interface MeterSpec {
  /** Stable id. Readings are keyed by it, so it survives a rename. */
  key: string
  label: string
  /** What is stencilled on the pipe or panel. */
  code: string
  group: string
  group_label: string
  stream: 'warm' | 'cold' | 'none'
}

export interface MeterRound {
  /** True once the crew has taken the round over from the habitat profile. */
  customised: boolean
  power: MeterSpec[]
  water: MeterSpec[]
}

/* --- Connectors: documents the assistant may read ------------------------ */

export interface KnowledgeDocument {
  id: string
  filename: string
  /** PDF, Word document, CSV, text file, Markdown. */
  kind: string
  bytes: number
  characters: number
  /** How many retrievable passages it was cut into. */
  chunks: number
  /** vector (embedded) or lexical (matched on shared words). */
  indexing: 'vector' | 'lexical'
  /** Whether the assistant may search it right now. */
  connected: boolean
  note: string
  uploaded_at: number
}

export interface ConnectorStatus {
  /** A local embedding model is installed and reachable. */
  embeddings_ready: boolean
  /** Why not, when it is not. */
  embeddings_detail: string
  embedding_model: string
  /** The file types accepted. */
  accepts: string
  max_mb: number
  /** How many documents the assistant may currently search. */
  connected: number
}

export interface DocumentList {
  documents: KnowledgeDocument[]
  status: ConnectorStatus
}
