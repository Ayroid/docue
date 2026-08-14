/**
 * Client for `/api/v1/sessions` — the fill conversation.
 *
 * Mirrors the backend's `app/api/v1/sessions.py`. Same relative-base rule as
 * `services/templates.ts`: Vite proxies `/api`, so every call is same-origin
 * and CORS never arises.
 *
 * The shapes below are the backend's response models verbatim, in snake_case.
 * They are **not** translated into the app's camelCase preview types here —
 * `features/generate/adapters.ts` does that, in one place, so there is exactly
 * one file to change when a field moves.
 */

import { TemplateApiError, type TemplateFormat } from '@/services/templates'

const API_BASE_URL = '/api/v1'

export type Tier = 'T1' | 'T2' | 'T3'

export interface QuestionOut {
  question_id: string
  question_no: number
  question_text: string
  hint: string | null
  example: string | null
  /** The regions this question supplies — the live preview highlights these. */
  covers_regions: string[]
}

export interface ProgressOut {
  answered: number
  total_questions: number
  fields_filled: number
  fields_total: number
}

export interface TurnOut {
  question_id: string
  question_text: string
  answer: string
  extracted: Record<string, unknown>
  skipped: boolean
  /** The extractor was unavailable; the raw answer was kept and can be re-read. */
  degraded: boolean
}

export interface ChipOut {
  key: string
  value: string
}

export interface DerivedValue {
  value: unknown
  /** What in the supplied answers this came from. The backend drops any value without one. */
  basis: string
  confidence: number
  provenance: string
}

export interface SessionOut {
  session_id: string
  template_id: string
  base_version_id: string
  format: TemplateFormat
  tier: Tier
  intent: string | null
  status: string
  questions: QuestionOut[]
  current_question: QuestionOut | null
  turns: TurnOut[]
  filled_values: Record<string, unknown>
  derived_values: Record<string, DerivedValue>
  known_context: Record<string, unknown>
  progress: ProgressOut
  started_at: string
  completed_at: string | null
}

export interface SessionCreateOut extends SessionOut {
  /** One line on what the triage decided, for the top of the chat. */
  plan_summary: string
}

export interface AnswerOut {
  session_id: string
  extracted: Record<string, unknown>
  chips: ChipOut[]
  /** Only populated on the final turn — the deriver runs once, not per answer. */
  derived: Record<string, DerivedValue>
  next_question: QuestionOut | null
  progress: ProgressOut
  degraded: boolean
  warnings: string[]
}

/* The Change Spec as the backend spells it (contract C1) — snake_case, and
   `target.region_id` rather than a bare `regionId`. */
export interface ServerOperation {
  op: 'set_value' | 'set_text' | 'clear_region' | 'clone_table_rows' | 'replace_region_rows' | 'set_bullets' | 'set_notes' | 'protect'
  target: { region_id: string | null; ref: string | null; sheet: string | null }
  value?: unknown
  rows?: (Record<string, unknown> | string)[]
  items?: string[]
  text?: string
  reason?: string
  /** `user_answer:q2`, `llm_derived`, `system:protect`. Drives the review badging. */
  provenance: string
}

export interface ServerChangeSpec {
  spec_version: string
  base_version_id: string | null
  tier: Tier
  intent: string | null
  operations: ServerOperation[]
  assertions: Record<string, unknown>[]
}

export interface SpecOut {
  session_id: string
  base_version_id: string
  spec: ServerChangeSpec
  operation_count: number
  provenance_counts: Record<string, number>
  /** Values with nowhere to go, and why. The honest half of the plan. */
  skipped: { region_id: string; reason: string }[]
}

export interface DroppedOperation {
  index: number
  op: string
  target: string
  reason: string
}

export interface CompileResponse {
  change_spec_id: string
  template_id: string
  base_version_id: string
  dry_run: boolean
  status: string
  overall: 'pass' | 'fail'
  operations_submitted: number
  operations_applied: number
  dropped: DroppedOperation[]
  rows_inserted: number
  /** `{passed, lost_parts[], merged_ranges_before, merged_ranges_after}` — the integrity report. */
  structural: Record<string, unknown>
  functional: Record<string, unknown>
  assertions: { kind: string; subject: string; expected: unknown; actual: unknown; passed: boolean }[]
  /** Regions the compiler would have refused. The "we never wrote the logo" report. */
  protected_regions: string[]
  /** `surgical` when the result was rebuilt from the original zip, part for part. */
  packaging: string | null
  warnings: string[]
  duration_ms: number
  result_version_id: string | null
  /** Set instead of `result_version_id` when the commit produced a document. */
  result_document_id: string | null
  result_version_number: number | null
  download_url: string | null
  qa_run_id: string | null
  created_at: string | null
}

/* FastAPI's body for a route that does not exist. It carries no information
   about *what* was not found, so treating it as a detail puts the bare words
   "Not Found" in front of a user — which is what happened the first time the
   backend was running a process older than these endpoints. Recognised here so
   the message can say something actionable instead. */
const FRAMEWORK_404 = 'Not Found'

async function detailOf(res: Response): Promise<string | null> {
  try {
    const body = await res.json()
    if (typeof body?.detail !== 'string') return null
    return body.detail === FRAMEWORK_404 ? null : body.detail
  } catch {
    return null
  }
}

async function call<T>(path: string, init?: RequestInit, notFound?: string): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}${path}`, init)
  } catch {
    throw new TemplateApiError(0, 'Could not reach the Template Hub server.')
  }

  if (!res.ok) {
    const detail = await detailOf(res)
    if (detail) throw new TemplateApiError(res.status, detail)

    // No usable detail. A 404 on a route the server does not publish almost
    // always means the API is running older code than this build expects.
    const message =
      res.status === 404
        ? `${notFound ?? 'Not found.'} If this persists, the backend may be running an older build — restart it and try again.`
        : `Request failed (${res.status}).`
    throw new TemplateApiError(res.status, message)
  }

  return res.json()
}

function post<T>(path: string, body: unknown, notFound?: string): Promise<T> {
  return call<T>(
    path,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
    notFound,
  )
}

/**
 * Start a conversation. Runs the context agent and, on a cache miss, the planner.
 *
 * Slower than the other calls by design — two model calls, once per session.
 * A second session against the same version reuses the cached question plan and
 * returns markedly faster.
 */
export function startSession(input: {
  templateId: string
  versionId?: string
  intent?: string
  tier?: Tier
}): Promise<SessionCreateOut> {
  return post<SessionCreateOut>(
    '/sessions',
    {
      template_id: input.templateId,
      version_id: input.versionId ?? null,
      intent: input.intent ?? null,
      tier: input.tier ?? 'T2',
    },
    'Template not found.',
  )
}

/**
 * Answer the current question.
 *
 * `skip` records the turn with no values, which leaves the regions it covered
 * untouched and *visible* on the review screen rather than quietly filled.
 */
export function sendAnswer(
  sessionId: string,
  input: { questionId: string; answer: string; skip?: boolean },
): Promise<AnswerOut> {
  return post<AnswerOut>(
    `/sessions/${sessionId}/answer`,
    { question_id: input.questionId, answer: input.answer, skip: input.skip ?? false },
    'Session not found.',
  )
}

/** Full state — enough to rebuild the chat screen after a reload. */
export function getSession(sessionId: string): Promise<SessionOut> {
  return call<SessionOut>(`/sessions/${sessionId}`, undefined, 'Session not found.')
}

/** The Change Specification this session would compile. */
export function getSpec(sessionId: string): Promise<SpecOut> {
  return call<SpecOut>(`/sessions/${sessionId}/spec`, undefined, 'Session not found.')
}

/** Edit one operation's value. Only the value moves; the target is fixed. */
export function patchSpecOperation(
  sessionId: string,
  opIndex: number,
  patch: { value?: unknown; rows?: Record<string, unknown>[] },
): Promise<SpecOut> {
  return call<SpecOut>(`/sessions/${sessionId}/spec/${opIndex}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
}

/** Compile without keeping anything — the QA verdict the review screen shows. */
export function compileSession(
  sessionId: string,
  overrides: Record<string, unknown> = {},
): Promise<CompileResponse> {
  return post<CompileResponse>(`/sessions/${sessionId}/compile`, { dry_run: true, overrides })
}

/**
 * Compile for real and keep the result.
 *
 * By default that is a **document** — the caller's own file, with no version
 * number and no claim on the template it was made from. `submitAsVersion` is
 * the other thing: it mints a template version and sends it to doc control.
 * Filling a form's fields makes a document, not a better form, so the default
 * is the common case.
 */
export function commitSession(
  sessionId: string,
  options: {
    submitAsVersion?: boolean
    publish?: boolean
    overrides?: Record<string, unknown>
  } = {},
): Promise<CompileResponse> {
  return post<CompileResponse>(`/sessions/${sessionId}/commit`, {
    dry_run: false,
    submit_as_version: options.submitAsVersion ?? false,
    publish: options.publish ?? false,
    overrides: options.overrides ?? {},
  })
}

export function abandonSession(sessionId: string): Promise<SessionOut> {
  return post<SessionOut>(`/sessions/${sessionId}/abandon`, {})
}
