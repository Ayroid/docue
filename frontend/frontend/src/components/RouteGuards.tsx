import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '@/store/AuthProvider'

/**
 * Session gates for the router.
 *
 * These are presentation, not security. Every protected route on the backend
 * re-checks the token and re-reads the role from the database, so a user who
 * edits their local storage reaches a page that shows them a 403. What these
 * do is stop the app rendering a screen it cannot fill.
 */

/** Held while the stored token is exchanged for a user on startup.
 *
 *  Rendering a guard's decision before that resolves is what bounces a
 *  signed-in user to the login page on every refresh — `signedIn` is false for
 *  the first tick simply because the answer has not arrived. */
function Waiting() {
  return (
    <div className="min-h-screen grid place-items-center bg-bg">
      <p className="text-body-md text-neutral-700">Checking your session…</p>
    </div>
  )
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { signedIn, loading } = useAuth()
  const location = useLocation()

  if (loading) return <Waiting />
  if (!signedIn) {
    /* Where they were headed, so signing in lands there instead of dumping
       everyone on Discovery. Read back by `Login`. */
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  }
  return <>{children}</>
}

export function RequireAdmin({ children }: { children: ReactNode }) {
  const { signedIn, isAdmin, loading } = useAuth()
  const location = useLocation()

  if (loading) return <Waiting />
  if (!signedIn) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  }
  /* A signed-in non-admin is sent to Discovery rather than to the login page:
     they are not short of a session, they are short of a role, and offering
     them the sign-in form suggests a different account would help. */
  if (!isAdmin) return <Navigate to="/discovery" replace />
  return <>{children}</>
}

/** For the login and register screens — someone already signed in has no
    business on them, and landing there after a refresh is disorienting. */
export function RedirectIfSignedIn({ children }: { children: ReactNode }) {
  const { signedIn, loading } = useAuth()

  if (loading) return <Waiting />
  if (signedIn) return <Navigate to="/discovery" replace />
  return <>{children}</>
}
