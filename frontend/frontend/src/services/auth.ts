/**
 * Client for `/api/v1/auth`, plus the token store the rest of the app reads.
 *
 * The token lives in `localStorage` under one key, and every module that needs
 * it goes through `authHeader()` rather than reading storage directly. That is
 * what makes signing out a single `clearToken()` call instead of a hunt for
 * every place a header was assembled by hand.
 *
 * `localStorage` rather than a cookie because the backend authorises off a
 * bearer header and sets no cookie at all — there is nothing for the browser to
 * send automatically. It survives a reload, which an in-memory token did not:
 * the old provider dropped `loggedIn` on every refresh.
 */

const API_BASE_URL = '/api/v1'

/* One key, exported so tests and the provider cannot drift from each other. */
export const TOKEN_KEY = 'templatehub.token'

export type Role = 'admin' | 'user'
export type UserStatus = 'pending' | 'active' | 'disabled'

export interface AuthUser {
  id: string
  email: string
  username: string
  full_name: string | null
  role: Role
  status: UserStatus
  email_verified: boolean
  created_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: AuthUser
}

/**
 * The answer to anything that sends a code.
 *
 * `debug_code` is only ever populated when the backend is running locally with
 * no SMTP configured — it is how the flow is walkable without a mailbox. Treat
 * a null as normal, never as an error.
 */
export interface OtpSent {
  message: string
  email: string
  expires_at: string
  email_sent: boolean
  debug_code: string | null
}

export class AuthApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'AuthApiError'
    this.status = status
  }
}

/* ── token store ────────────────────────────────────────────────────────── */

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    /* Safari in private mode throws on any storage access. Losing the session
       on reload is a far better outcome than a blank page. */
    return null
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token)
  } catch {
    /* Same as above — the in-memory session still works for this tab. */
  }
}

export function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* Nothing to clear if storage was never writable. */
  }
}

/** The Authorization header, or an empty object when signed out.
 *
 *  Spread into a fetch's headers: `{ ...authHeader() }`. Returning `{}` rather
 *  than a header with an empty value matters — the backend's `optional_user`
 *  treats a malformed header as anonymous, but `templates.ts` would still be
 *  sending a token-shaped string that means nothing. */
export function authHeader(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/* ── requests ───────────────────────────────────────────────────────────── */

async function detailOf(res: Response): Promise<string | null> {
  const body = await res.json().catch(() => null)
  if (!body || typeof body !== 'object' || !('detail' in body)) return null
  const detail = (body as { detail: unknown }).detail
  /* FastAPI answers a 422 with `detail` as an array of per-field objects, not a
     string. Rendering that raw puts `[object Object]` in front of the user, so
     the first message is lifted out instead. */
  if (Array.isArray(detail)) {
    const first = detail[0]
    if (first && typeof first === 'object' && 'msg' in first) return String((first as { msg: unknown }).msg)
    return detail.length ? String(first) : null
  }
  return String(detail)
}

async function post<T>(path: string, body: unknown, withAuth = false): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(withAuth ? authHeader() : {}) },
      body: JSON.stringify(body),
    })
  } catch {
    throw new AuthApiError(0, 'Could not reach the Template Hub server.')
  }

  if (!res.ok) {
    throw new AuthApiError(res.status, (await detailOf(res)) ?? `Request failed (${res.status}).`)
  }
  return res.json()
}

export interface RegisterPayload {
  email: string
  username: string
  password: string
  full_name?: string
}

export function register(payload: RegisterPayload): Promise<OtpSent> {
  return post<OtpSent>('/auth/register', payload)
}

export function verifyEmail(email: string, code: string): Promise<TokenResponse> {
  return post<TokenResponse>('/auth/verify-email', { email, code })
}

export function resendOtp(
  email: string,
  purpose: 'email_verification' | 'password_reset' = 'email_verification',
): Promise<OtpSent> {
  return post<OtpSent>('/auth/resend-otp', { email, purpose })
}

/** Sign in with either the username or the email address — the backend works
    out which it was given, so the form needs only one field. */
export function login(identifier: string, password: string): Promise<TokenResponse> {
  return post<TokenResponse>('/auth/login', { identifier, password })
}

export function forgotPassword(email: string): Promise<{ message: string }> {
  return post<{ message: string }>('/auth/forgot-password', { email })
}

export function resetPassword(
  email: string,
  code: string,
  newPassword: string,
): Promise<{ message: string }> {
  return post<{ message: string }>('/auth/reset-password', {
    email,
    code,
    new_password: newPassword,
  })
}

export function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<{ message: string }> {
  return post<{ message: string }>(
    '/auth/change-password',
    { current_password: currentPassword, new_password: newPassword },
    true,
  )
}

/**
 * The signed-in user, from the token already in storage.
 *
 * Called once on startup to re-establish a session across a reload. A 401 here
 * means the stored token has expired or been revoked, and the caller's job is
 * to clear it rather than to retry.
 */
export async function fetchMe(): Promise<AuthUser> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}/auth/me`, { headers: { ...authHeader() } })
  } catch {
    throw new AuthApiError(0, 'Could not reach the Template Hub server.')
  }

  if (!res.ok) {
    throw new AuthApiError(res.status, (await detailOf(res)) ?? `Session check failed (${res.status}).`)
  }
  return res.json()
}
