import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import {
  clearToken,
  fetchMe,
  getToken,
  setToken,
  type AuthUser,
  type TokenResponse,
} from '@/services/auth'

/**
 * Who is signed in, for the whole app.
 *
 * Deliberately separate from `HubProvider`: that one holds this tab's scratch
 * state (the walkthrough, the toast) and is cleared on reload by design. A
 * session must survive a reload, and mixing the two is what made `loggedIn` an
 * in-memory boolean that dropped every refresh.
 *
 * `role` is never stored client-side beyond the user object the server sent.
 * Hiding the Admin tab is presentation, not authorisation — every admin route
 * on the backend re-checks the role against the database, so a user who edits
 * their local copy gains a menu item and a 403.
 */

export interface AuthState {
  user: AuthUser | null
  /** True while the stored token is being exchanged for a user on startup.
      Routes must wait for this: rendering a guard before it resolves bounces a
      signed-in user to the login page on every refresh. */
  loading: boolean
  isAdmin: boolean
  signedIn: boolean
  /** Adopt the session a login/verify call just returned. */
  adopt: (token: TokenResponse) => void
  signOut: () => void
  /** Re-read the user from the server — used after a role change. */
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  /* Startup: if there is a token, find out whether it still means anything.
     A 401 here is the normal expiry path, not an error worth showing — the
     token is dropped and the app renders signed out. */
  useEffect(() => {
    let cancelled = false

    if (!getToken()) {
      setLoading(false)
      return
    }

    fetchMe()
      .then((me) => {
        if (!cancelled) setUser(me)
      })
      .catch(() => {
        if (!cancelled) {
          clearToken()
          setUser(null)
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [])

  const adopt = useCallback((token: TokenResponse) => {
    setToken(token.access_token)
    setUser(token.user)
    setLoading(false)
  }, [])

  const signOut = useCallback(() => {
    clearToken()
    setUser(null)
  }, [])

  const refresh = useCallback(async () => {
    if (!getToken()) return
    try {
      setUser(await fetchMe())
    } catch {
      clearToken()
      setUser(null)
    }
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      isAdmin: user?.role === 'admin',
      signedIn: user !== null,
      adopt,
      signOut,
      refresh,
    }),
    [user, loading, adopt, signOut, refresh],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
