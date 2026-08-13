/**
 * Client for the real `/api/v1/templates` endpoints. Upload, list and
 * fetch-by-id are the only routes that exist on the backend today; search,
 * versions, download and delete aren't built yet.
 */

const API_BASE_URL = 'http://localhost:8000/api/v1'

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

export async function uploadTemplate(file: File): Promise<TemplateOut> {
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
