/**
 * Client for the real `/api/v1/templates` endpoints. Upload, list,
 * fetch-by-id and download are the routes that exist on the backend today;
 * search, versions and delete aren't built yet.
 */

/* Relative on purpose: Vite proxies `/api` to the backend (see `vite.config.ts`),
   so every call is same-origin and CORS never enters the picture. Naming the
   backend origin directly here makes each call cross-origin, and the backend's
   `.env` only allows a couple of fixed ports — the dev server isn't one of them,
   so those requests get silently blocked. */
const API_BASE_URL = '/api/v1'

/* Every call carries the bearer token when there is one. Uploading *requires*
   it; the read routes accept it optionally and use it to decide whether the
   caller may also see their own not-yet-approved submissions. Signed out,
   `authHeader()` is `{}` and the reads behave exactly as they did before. */
import { authHeader } from '@/services/auth'

export type TemplateFormat = 'xlsx' | 'docx' | 'pptx'

export interface TemplateVersion {
  id: string
  version_number: number
  storage_bucket: string
  storage_key: string
  size_bytes: number
  mime_type: string
  file_hash: string
  upload_status: string
  created_at: string
}

export interface TemplateOut {
  id: string
  title: string
  original_filename: string
  format: TemplateFormat
  status: string
  /** Read off the document itself, e.g. `YMSLI-F-MOM`. */
  form_id: string | null
  house_pattern: string | null
  /* Written by the backend's enrichment pass, not by the uploader. Null until
     that pass finishes — which is normal for ~45s after upload, and stays null
     if the model was unavailable. Treat as pending, never as an error. */
  purpose: string | null
  when_to_use: string | null
  audience: string | null
  category: string | null
  tags: string[]
  /** True once the template is embedded and reachable by semantic search. */
  searchable: boolean
  /* Review state of the current version. Anything the library lists is
     'approved' by construction — the other values only appear on a template
     the caller submitted themselves, or when the caller is an admin. */
  approval_status: 'pending' | 'approved' | 'rejected'
  /** The reviewer's note. Set on a rejection, optional on an approval. */
  review_note: string | null
  owner_id: string | null
  current_version_id: string
  created_at: string
  updated_at: string
  current_version: TemplateVersion | null
}

export class TemplateApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'TemplateApiError'
    this.status = status
  }
}

function messageForUploadStatus(status: number, detail: string | null): string {
  switch (status) {
    case 400:
      return detail ?? 'That file was rejected — only .docx, .xlsx and .pptx are accepted.'
    case 413:
      return 'That file is over the 25 MB upload limit.'
    case 502:
      return 'Upload storage is unavailable right now. Try again shortly.'
    case 500:
      return 'The upload saved to storage but failed to record — try again.'
    default:
      return detail ?? `Upload failed (${status}).`
  }
}

async function detailOf(res: Response): Promise<string | null> {
  const body = await res.json().catch(() => null)
  return body && typeof body === 'object' && 'detail' in body ? String(body.detail) : null
}

/**
 * What `POST /templates` answers with — a 202 and a job id, not the finished
 * template. Ingestion (region detection) takes 15-40s, so the upload returns
 * as soon as the file is stored and the job is queued. The template row itself
 * exists immediately, so `getTemplate(template_id)` resolves right away.
 */
export interface UploadAccepted {
  template_id: string
  version_id: string
  job_id: string
  /** Always 'ingesting' — the job has been queued. */
  status: string
}

/**
 * The id of the template just uploaded, from either upload contract.
 *
 * A server on the current API answers 202 with `template_id`; one still on the
 * previous build answers 201 with a whole `TemplateOut`, whose id is `id`.
 * Reading both means a running server that hasn't been restarted since the
 * ingestion work landed doesn't silently break uploads. Drop the fallback once
 * every deployment is on the ingestion API.
 */
export function uploadedTemplateId(result: UploadAccepted | TemplateOut): string {
  return 'template_id' in result ? result.template_id : result.id
}

export async function uploadTemplate(file: File): Promise<UploadAccepted | TemplateOut> {
  const form = new FormData()
  form.append('file', file)

  let res: Response
  try {
    /* No Content-Type header: the browser has to set it itself so it can add
       the multipart boundary. Only the Authorization header is ours. */
    res = await fetch(`${API_BASE_URL}/templates`, {
      method: 'POST',
      headers: { ...authHeader() },
      body: form,
    })
  } catch {
    throw new TemplateApiError(0, 'Could not reach the Template Hub server.')
  }

  if (!res.ok) {
    throw new TemplateApiError(res.status, messageForUploadStatus(res.status, await detailOf(res)))
  }

  return res.json()
}

/**
 * The library. Approved templates only, unless `mine` is set — which returns
 * the caller's own submissions whatever their review state, so someone can
 * watch an upload through the queue.
 */
export async function listTemplates(options: { mine?: boolean } = {}): Promise<TemplateOut[]> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}/templates${options.mine ? '?mine=true' : ''}`, {
      headers: { ...authHeader() },
    })
  } catch {
    throw new TemplateApiError(0, 'Could not reach the Template Hub server.')
  }

  if (!res.ok) {
    throw new TemplateApiError(res.status, (await detailOf(res)) ?? `Listing failed (${res.status}).`)
  }

  return res.json()
}

export async function getTemplate(id: string): Promise<TemplateOut> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}/templates/${id}`, { headers: { ...authHeader() } })
  } catch {
    throw new TemplateApiError(0, 'Could not reach the Template Hub server.')
  }

  if (!res.ok) {
    const message = res.status === 404 ? 'Template not found.' : ((await detailOf(res)) ?? `Lookup failed (${res.status}).`)
    throw new TemplateApiError(res.status, message)
  }

  return res.json()
}

/** Raw file bytes for client-side preview — parsed and rendered entirely in
    the browser, never opened in Office or an Office Online iframe. */
export async function downloadTemplateFile(id: string): Promise<ArrayBuffer> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}/templates/${id}/download`, { headers: { ...authHeader() } })
  } catch {
    throw new TemplateApiError(0, 'Could not reach the Template Hub server.')
  }

  if (!res.ok) {
    const message =
      res.status === 404 ? 'Template file not found.' : ((await detailOf(res)) ?? `Download failed (${res.status}).`)
    throw new TemplateApiError(res.status, message)
  }

  return res.arrayBuffer()
}

/* ── ingestion progress ─────────────────────────────────────────────────── */

/** The AI half of ingestion: semantic labels, discovery metadata, embedding. */
export interface EnrichmentOut {
  enrichment_version: string
  model_id: string
  classifier_prompt: string
  metadata_prompt: string
  regions_labelled: number
  /** Regions the model judged a generation agent should not write. */
  regions_write_refused: number
  /** False when the model call failed and the filename was used instead. */
  metadata_generated: boolean
  /** Whether the template is findable by semantic search. */
  embedded: boolean
  title: string | null
  tags: string[]
  elapsed_ms: number | null
  warnings: string[]
}

export type JobStatusValue = 'queued' | 'running' | 'succeeded' | 'failed'

/**
 * What `GET /templates/{id}/ingestion/{job_id}` answers with.
 *
 * Two things are easy to get wrong here, and both come from how the backend is
 * built rather than from taste:
 *
 * - `enrichment` is null on a *succeeded* job whenever the model was
 *   unavailable. Enrichment runs after the structural result is committed and
 *   is not allowed to fail it, so that combination means "not searchable yet",
 *   not "broken". Render it as pending.
 * - A *failed* job still leaves a downloadable template: the file and the
 *   version row are committed before the job starts.
 */
export interface JobStatus {
  job_id: string
  kind: string
  status: JobStatusValue
  /** fingerprint | detect | harvest | verify | persist | enrich | done */
  stage: string | null
  /** 0-100. Safe to drive a progress bar from the first response. */
  progress: number
  error: string | null
  pipeline_version: string | null
  detector_version: string | null
  regions_detected: number | null
  regions_writable: number | null
  counts_by_kind: Record<string, number> | null
  containers: string[] | null
  house_pattern_matched: string | null
  form_id: string | null
  in_doc_version: string | null
  enrichment: EnrichmentOut | null
  warnings: string[]
  elapsed_ms: number | null
}

export async function getIngestionStatus(templateId: string, jobId: string): Promise<JobStatus> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}/templates/${templateId}/ingestion/${jobId}`, {
      headers: { ...authHeader() },
    })
  } catch {
    throw new TemplateApiError(0, 'Could not reach the Template Hub server.')
  }

  if (!res.ok) {
    throw new TemplateApiError(res.status, (await detailOf(res)) ?? `Job lookup failed (${res.status}).`)
  }

  return res.json()
}

/* ── search ─────────────────────────────────────────────────────────────── */

export interface SignalScores {
  bm25_rank: number | null
  vector_rank: number | null
  bm25: number | null
  vector: number | null
  rrf: number
}

export interface SearchResult {
  template_id: string
  title: string
  format: TemplateFormat
  purpose: string | null
  when_to_use: string | null
  audience: string | null
  tags: string[]
  form_id: string | null
  current_version_id: string | null
  score: number
  /** Derived from the ranks by the backend, never written by a model — safe to show verbatim. */
  match_explanation: string
  /** Fragments with <mark> around matched terms. Render as HTML, sanitised to <mark>. */
  highlights: string[]
  scores: SignalScores
}

export interface SearchResponse {
  query: string
  results: SearchResult[]
  latency_ms: number
  lexical_candidates: number
  vector_candidates: number
  /** Set when the query could not be embedded — results are keyword-only. */
  degraded: string | null
}

export async function searchTemplates(query: string, topK = 5): Promise<SearchResponse> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader() },
      body: JSON.stringify({ query, top_k: topK }),
    })
  } catch {
    throw new TemplateApiError(0, 'Could not reach the Template Hub server.')
  }

  if (!res.ok) {
    throw new TemplateApiError(res.status, (await detailOf(res)) ?? `Search failed (${res.status}).`)
  }

  return res.json()
}
