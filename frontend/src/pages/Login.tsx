import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '@/store/AuthProvider'
import { AuthApiError, login as loginRequest } from '@/services/auth'
import { Button } from '@/components/ui/button'
import { Field, Input } from '@/components/ui/input'
import { AuthLayout, FormError, FormNotice } from '@/pages/auth/AuthLayout'

/**
 * Sign in with a username *or* an email address and a password.
 *
 * One identifier field rather than two: the backend resolves whichever it was
 * given, so asking the user to declare which kind of handle they are typing is
 * a question the server can answer itself.
 */
export function Login() {
  const navigate = useNavigate()
  const location = useLocation()
  const { adopt } = useAuth()

  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const routed = (location.state ?? null) as { from?: string; notice?: string } | null
  /* Where the guard bounced them from, so signing in resumes what they were
     doing instead of dropping everyone on Discovery. */
  const from = routed?.from ?? '/discovery'
  /* Set by `/reset-password` after a successful reset, so the reason they are
     back at this form is on screen rather than left to be inferred. */
  const notice = routed?.notice ?? null

  const signIn = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      adopt(await loginRequest(identifier.trim(), password))
      navigate(from, { replace: true })
    } catch (err) {
      /* 403 means the password was right but the address is unverified — the
         only useful next step is the code screen, so send them there with the
         address already filled in rather than leaving them re-reading a
         message they cannot act on. */
      if (err instanceof AuthApiError && err.status === 403 && err.message.toLowerCase().includes('verify')) {
        navigate('/verify-email', { state: { email: identifier.trim() } })
        return
      }
      setError(err instanceof AuthApiError ? err.message : 'Could not sign you in.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout
      title="Sign in"
      subtitle="Use your work email address or username."
      footer={
        <>
          <span className="text-neutral-700">New here? </span>
          <Link to="/register" className="text-accent no-underline hover:underline">
            Create an account
          </Link>
        </>
      }
    >
      <form onSubmit={signIn}>
        <Field label="Work email or username" htmlFor="hub-identifier" className="mb-4 text-left">
          <Input
            id="hub-identifier"
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            placeholder="name@yamaha-motor-india.com"
            autoComplete="username"
            required
          />
        </Field>
        <Field label="Password" htmlFor="hub-pass" className="mb-3 text-left">
          <Input
            id="hub-pass"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            autoComplete="current-password"
            required
          />
        </Field>

        <div className="flex justify-center mb-[22px]">
          <Link to="/forgot-password" className="text-body-md text-accent no-underline hover:underline">
            Forgot password?
          </Link>
        </div>

        <FormNotice message={notice} />
        <FormError message={error} />

        <Button type="submit" variant="primary" block className="py-[11px] whitespace-nowrap" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </Button>
      </form>
    </AuthLayout>
  )
}
