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
    res = await fetch(`${API_BASE_URL}/templates`, { method: 'POST', body: form })
  } catch {
    throw new TemplateApiError(0, 'Could not reach the Template Hub server.')
  }

  if (!res.ok) {
    throw new TemplateApiError(res.status, messageForUploadStatus(res.status, await detailOf(res)))
  }

  return res.json()
}

export async function listTemplates(): Promise<TemplateOut[]> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}/templates`)
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
    res = await fetch(`${API_BASE_URL}/templates/${id}`)
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
    res = await fetch(`${API_BASE_URL}/templates/${id}/download`)
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
