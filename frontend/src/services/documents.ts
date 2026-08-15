/**
 * Documents people made from templates.
 *
 * A document is not a version of its template — it has no version number and
 * nobody approves it. `submitAsVersion` is the one route from one to the other,
 * and it is a claim about the *template*, so it goes to doc control.
 */

import { authHeader } from '@/services/auth'

const API_BASE_URL = '/api/v1'

export class DocumentApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'DocumentApiError'
    this.status = status
  }
}

export interface GeneratedDocument {
  id: string
  template_id: string
  template_title: string | null
  format: 'xlsx' | 'docx' | 'pptx' | null
  title: string
  base_version_id: string
  base_version_number: number | null
  /** False when the template has moved on since this was generated. */
  base_version_is_current: boolean
  session_id: string | null
  size_bytes: number
  created_at: string
  created_by: string | null
  promoted_version_id: string | null
  promoted_version_number: number | null
  promoted_status: 'pending' | 'approved' | 'rejected' | null
  download_url: string
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { Accept: 'application/json', ...(init.headers ?? {}), ...authHeader() },
    })
  } catch {
    throw new DocumentApiError(0, 'Could not reach the Template Hub server.')
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const detail = body && typeof body === 'object' && 'detail' in body ? String(body.detail) : null
    throw new DocumentApiError(res.status, detail ?? `Request failed (${res.status}).`)
  }
  return (await res.json()) as T
}

export function listDocuments(templateId?: string): Promise<GeneratedDocument[]> {
  const query = templateId ? `?template_id=${templateId}` : ''
  return request<GeneratedDocument[]>(`/documents${query}`)
}

export function getDocument(documentId: string): Promise<GeneratedDocument> {
  return request<GeneratedDocument>(`/documents/${documentId}`)
}

/** Put a document forward as the template's next version, for doc control. */
export function submitAsVersion(
  documentId: string,
  note?: string | null,
): Promise<GeneratedDocument> {
  return request<GeneratedDocument>(`/documents/${documentId}/submit-as-version`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ note: note ?? null }),
  })
}

/**
 * Download a document's bytes.
 *
 * Fetched rather than linked, because the route needs an Authorization header
 * and an `<a href>` cannot carry one.
 */
export async function downloadDocumentFile(doc: GeneratedDocument): Promise<void> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}/documents/${doc.id}/download`, {
      headers: authHeader(),
    })
  } catch {
    throw new DocumentApiError(0, 'Could not reach the Template Hub server.')
  }
  if (!res.ok) throw new DocumentApiError(res.status, `Could not download (${res.status}).`)

  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const ext = doc.format ? `.${doc.format}` : ''
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${doc.title}${ext}`
  anchor.click()
  URL.revokeObjectURL(url)
}
