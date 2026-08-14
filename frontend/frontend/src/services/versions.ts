/**
 * A template's version history and what each version changed.
 *
 * Read-only. Approving and rejecting live in `services/notifications.ts`
 * against `/admin/approvals` — this deliberately adds no second way to decide a
 * version, only a way to see the lineage.
 */

import { authHeader } from '@/services/auth'

const API_BASE_URL = '/api/v1'

export class VersionApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'VersionApiError'
    this.status = status
  }
}

export type ApprovalStatus = 'pending' | 'approved' | 'rejected'

export interface RegionChange {
  region_id: string
  label: string | null
  op: string
  /** The value written. Null for a table, which reports `rows_written` instead. */
  value: string | null
  /** Where the value came from — a typed answer, the deriver, a review edit. */
  provenance: string | null
  rows_written: number | null
}

export interface VersionRow {
  id: string
  version_number: number
  approval_status: ApprovalStatus
  origin: 'upload' | 'generated'
  is_current: boolean
  created_at: string
  submitted_by: string | null
  submitted_by_name: string | null
  reviewed_by_name: string | null
  reviewed_at: string | null
  review_note: string | null
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
}

export interface VersionHistory {
  template_id: string
  template_title: string
  current_version_id: string | null
  versions: VersionRow[]
}

/**
 * Every version of a template, newest first.
 *
 * The server filters per caller: an admin sees the whole lineage, an author
 * additionally sees their own unapproved submissions, everyone else sees the
 * approved line. Nothing needs to be hidden here.
 */
export async function getVersionHistory(templateId: string): Promise<VersionHistory> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}/templates/${templateId}/versions`, {
      headers: { Accept: 'application/json', ...authHeader() },
    })
  } catch {
    throw new VersionApiError(0, 'Could not reach the Template Hub server.')
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const detail =
      body && typeof body === 'object' && 'detail' in body ? String(body.detail) : null
    throw new VersionApiError(res.status, detail ?? `Could not load the version history (${res.status}).`)
  }
  return (await res.json()) as VersionHistory
}
