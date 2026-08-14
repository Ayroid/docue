/**
 * Client for `/api/v1/admin/templates/{id}/access` — who may see a template.
 *
 * Mirrors the backend's `app/api/v1/access.py`. Every route here is admin-only
 * and answers 403 for anyone else, so callers should gate the UI on
 * `useAuth().isAdmin` rather than relying on the request failing.
 *
 * Each of the four calls returns the **whole** access state, not just the thing
 * it changed. That is deliberate on the backend's side and it is why there is no
 * local reducer here: the dialog re-renders from one authoritative response
 * after every action, so a failed grant cannot leave the list showing a row the
 * server does not have.
 */

import { authHeader } from '@/services/auth'
import { TemplateApiError } from '@/services/templates'

const API_BASE_URL = '/api/v1'

export type Visibility = 'public' | 'restricted'
export type Permission = 'view' | 'manage'

export interface Grant {
  user_id: string
  email: string
  username: string
  full_name: string | null
  /** 'pending' means they registered but never verified — the grant is real but unusable. */
  user_status: string
  permission: Permission
  granted_by: string | null
  granted_by_name: string | null
  granted_at: string
  expires_at: string | null
  expired: boolean
}

export interface TemplateAccess {
  template_id: string
  title: string
  visibility: Visibility
  owner_id: string | null
  owner_email: string | null
  grants: Grant[]
}

async function detailOf(res: Response): Promise<string | null> {
  try {
    const body = await res.json()
    return typeof body?.detail === 'string' ? body.detail : null
  } catch {
    return null
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...(init?.headers as Record<string, string> | undefined),
        ...authHeader(),
      },
    })
  } catch {
    throw new TemplateApiError(0, 'Could not reach the Template Hub server.')
  }
  if (!res.ok) {
    /* The backend's messages here are written to be shown: "No account is
       registered to x@y.com", "They own this template". Passing them through
       beats inventing a generic failure. */
    throw new TemplateApiError(res.status, (await detailOf(res)) ?? `Request failed (${res.status}).`)
  }
  return res.json()
}

export function getTemplateAccess(templateId: string): Promise<TemplateAccess> {
  return call<TemplateAccess>(`/admin/templates/${templateId}/access`)
}

export function setTemplateVisibility(
  templateId: string,
  visibility: Visibility,
): Promise<TemplateAccess> {
  return call<TemplateAccess>(`/admin/templates/${templateId}/visibility`, {
    method: 'PUT',
    body: JSON.stringify({ visibility }),
  })
}

export function grantTemplateAccess(
  templateId: string,
  email: string,
  permission: Permission = 'view',
): Promise<TemplateAccess> {
  return call<TemplateAccess>(`/admin/templates/${templateId}/grants`, {
    method: 'POST',
    body: JSON.stringify({ email, permission }),
  })
}

export function revokeTemplateAccess(templateId: string, userId: string): Promise<TemplateAccess> {
  return call<TemplateAccess>(`/admin/templates/${templateId}/grants/${userId}`, {
    method: 'DELETE',
  })
}
