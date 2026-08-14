/**
 * Version control: promote a generated document, decide a request, read history.
 *
 * Every call carries the caller's identity in `X-User-Id`. That header is the
 * backend's temporary seam (`app/core/identity.py`) while the auth branch is in
 * flight — when it lands this file should send whatever that branch's client
 * sends instead, and `identityHeaders` is the one function to change.
 */

const API_BASE_URL = '/api/v1'

export class PromotionApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'PromotionApiError'
    this.status = status
  }
}

export type PromotionStatus = 'pending' | 'approved' | 'rejected'

export interface RegionChange {
  region_id: string
  label: string | null
  op: string
  /** The value written. Null for a table, which reports `rows_written` instead. */
  value: string | null
  provenance: string | null
  rows_written: number | null
}

export interface Promotion {
  id: string
  template_id: string
  template_title: string | null
  version_id: string
  version_number: number | null
  requested_by_id: string
  requested_by: string | null
  requested_role: string
  note: string | null
  status: PromotionStatus
  decided_by_id: string | null
  decided_by: string | null
  decision_note: string | null
  created_at: string
  decided_at: string | null
  /** Set when the decision published something — poll it like an upload's job. */
  ingestion_job_id: string | null
}

export interface VersionRow {
  id: string
  version_number: number
  lifecycle: 'draft' | 'pending' | 'published' | 'superseded'
  origin: 'upload' | 'generated'
  is_current: boolean
  created_at: string
  created_by_id: string | null
  created_by: string | null
  size_bytes: number
  in_doc_version: string | null
  /** The file's own `Ver.` disagrees with the hub's number — drift, no diff needed. */
  claims_stale_version: boolean
  download_url: string | null
  summary: string
  changed: RegionChange[]
  dropped: Array<{ target: string; reason: string }>
  protected_regions: string[]
  qa_overall: string | null
  intent: string | null
  pending_promotion_id: string | null
}

export interface VersionHistory {
  template_id: string
  template_title: string
  current_version_id: string | null
  versions: VersionRow[]
}

/**
 * Who the backend should think is calling.
 *
 * Returns no header at all when there is no signed-in user, rather than a
 * placeholder id: the backend treats an unknown id and a missing one alike
 * (anonymous), and sending a fake one would put a name on an audit row.
 */
export function identityHeaders(userId?: string | null): Record<string, string> {
  return userId ? { 'X-User-Id': userId } : {}
}

async function detailOf(res: Response): Promise<string | null> {
  const body = await res.json().catch(() => null)
  return body && typeof body === 'object' && 'detail' in body ? String(body.detail) : null
}

async function request<T>(
  path: string,
  { method = 'GET', body, userId }: { method?: string; body?: unknown; userId?: string | null } = {},
): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: {
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...identityHeaders(userId),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    })
  } catch {
    throw new PromotionApiError(0, 'Could not reach the Template Hub server.')
  }

  if (!res.ok) {
    const detail = await detailOf(res)
    if (res.status === 401) throw new PromotionApiError(401, detail ?? 'Sign in to do that.')
    if (res.status === 403)
      throw new PromotionApiError(403, detail ?? 'Only doc control can decide a request.')
    throw new PromotionApiError(res.status, detail ?? `Request failed (${res.status}).`)
  }
  return (await res.json()) as T
}

/**
 * Ask for a generated version to become the template's next version.
 *
 * An admin's call publishes immediately and comes back `approved`; anyone
 * else's comes back `pending`. Read `status` off the response rather than
 * inferring it from the local role — the server decides, and a role can change
 * between rendering the button and pressing it.
 */
export function promoteVersion(
  templateId: string,
  versionId: string,
  note: string | null,
  userId?: string | null,
): Promise<Promotion> {
  return request<Promotion>(`/templates/${templateId}/versions/${versionId}/promote`, {
    method: 'POST',
    body: { note },
    userId,
  })
}

export function listPromotions(
  status: PromotionStatus | 'all' = 'pending',
  userId?: string | null,
): Promise<Promotion[]> {
  return request<Promotion[]>(`/promotions?status=${status}`, { userId })
}

export function approvePromotion(
  promotionId: string,
  note: string | null,
  userId?: string | null,
): Promise<Promotion> {
  return request<Promotion>(`/promotions/${promotionId}/approve`, {
    method: 'POST',
    body: { note },
    userId,
  })
}

export function rejectPromotion(
  promotionId: string,
  note: string | null,
  userId?: string | null,
): Promise<Promotion> {
  return request<Promotion>(`/promotions/${promotionId}/reject`, {
    method: 'POST',
    body: { note },
    userId,
  })
}

export function getVersionHistory(
  templateId: string,
  { includeDrafts = true, userId }: { includeDrafts?: boolean; userId?: string | null } = {},
): Promise<VersionHistory> {
  return request<VersionHistory>(
    `/templates/${templateId}/versions?include_drafts=${includeDrafts}`,
    { userId },
  )
}
