/**
 * Client for `/api/v1/notifications` and the admin approval queue.
 *
 * Both are signed-in-only, so every call carries the bearer header. The two
 * live together because the bell and the queue are the same feature seen from
 * two sides: an admin's unread notification is a row in their approval queue,
 * and approving it is what produces the submitter's.
 */

import { authHeader, AuthApiError } from '@/services/auth'

const API_BASE_URL = '/api/v1'

export type NotificationKind = 'approval_requested' | 'template_approved' | 'template_rejected'

export interface AppNotification {
  id: string
  kind: NotificationKind
  title: string
  body: string
  template_id: string | null
  version_id: string | null
  read_at: string | null
  created_at: string
}

export interface NotificationList {
  items: AppNotification[]
  /** Counted server-side across every notification, not just the page. */
  unread: number
  total: number
}

export type ApprovalStatus = 'pending' | 'approved' | 'rejected'

export interface Approval {
  version_id: string
  template_id: string
  title: string
  original_filename: string
  format: 'docx' | 'xlsx' | 'pptx'
  version_number: number
  approval_status: ApprovalStatus
  size_bytes: number
  file_hash: string
  purpose: string | null
  category: string | null
  form_id: string | null
  submitted_by: string | null
  submitted_by_name: string | null
  submitted_by_email: string | null
  reviewed_by_name: string | null
  reviewed_at: string | null
  review_note: string | null
  submitted_at: string
}

export interface ApprovalQueue {
  items: Approval[]
  /** Pending across the whole queue — safe to drive the nav badge from. */
  pending: number
  total: number
}

async function detailOf(res: Response): Promise<string | null> {
  const body = await res.json().catch(() => null)
  return body && typeof body === 'object' && 'detail' in body ? String(body.detail) : null
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { ...(init.headers ?? {}), ...authHeader() },
    })
  } catch {
    throw new AuthApiError(0, 'Could not reach the Template Hub server.')
  }

  if (!res.ok) {
    throw new AuthApiError(res.status, (await detailOf(res)) ?? `Request failed (${res.status}).`)
  }
  return res.json()
}

/* ── the bell ───────────────────────────────────────────────────────────── */

export function listNotifications(limit = 30): Promise<NotificationList> {
  return request<NotificationList>(`/notifications?limit=${limit}`)
}

export function markNotificationRead(id: string): Promise<AppNotification> {
  return request<AppNotification>(`/notifications/${id}/read`, { method: 'POST' })
}

export function markAllNotificationsRead(): Promise<{ message: string }> {
  return request<{ message: string }>('/notifications/read-all', { method: 'POST' })
}

/* ── the approval queue (admins only) ───────────────────────────────────── */

export function listApprovals(status?: ApprovalStatus): Promise<ApprovalQueue> {
  const query = status ? `?status_filter=${status}` : ''
  return request<ApprovalQueue>(`/admin/approvals${query}`)
}

export function approveVersion(versionId: string, note?: string): Promise<Approval> {
  return request<Approval>(`/admin/approvals/${versionId}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ note: note ?? null }),
  })
}

/** The note is required on a rejection — the API refuses an empty one, because
    a "no" the submitter cannot act on is worse than no review at all. */
export function rejectVersion(versionId: string, note: string): Promise<Approval> {
  return request<Approval>(`/admin/approvals/${versionId}/reject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ note }),
  })
}
