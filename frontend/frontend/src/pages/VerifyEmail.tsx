import { useEffect, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '@/store/AuthProvider'
import { AuthApiError, resendOtp, verifyEmail } from '@/services/auth'
import { Button } from '@/components/ui/button'
import { Field, Input } from '@/components/ui/input'
import { AuthLayout, FormError, FormNotice } from '@/pages/auth/AuthLayout'

/**
 * Enter the six-digit code that finishes signing up.
 *
 * Verifying returns a token, so this screen signs the user in directly rather
 * than sending them back to the login form — they have already proved the
 * password (at registration) and now the address, and asking for the password
 * again would prove nothing.
 *
 * The address arrives in router state from `/register` or from a 403 on
 * `/login`. It stays editable: someone who lands here with a typo in the
 * address has no other way to correct it, and the field is the only thing that
 * decides which account the code is checked against.
 */
export function VerifyEmail() {
  const navigate = useNavigate()
  const location = useLocation()
  const { adopt } = useAuth()

  const state = (location.state ?? null) as {
    email?: string
    debugCode?: string | null
    emailSent?: boolean
  } | null

  const [email, setEmail] = useState(state?.email ?? '')
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  /* Only ever set when the backend is local with no SMTP configured. It is how
     the flow is walkable without a mailbox; in any real deployment it is null
     and this block never renders. */
  const [debugCode, setDebugCode] = useState<string | null>(state?.debugCode ?? null)

  useEffect(() => {
    if (state?.emailSent === false && !state?.debugCode) {
      setNotice('Email delivery is not configured on this server — check the server log for the code.')
    }
  }, [state?.emailSent, state?.debugCode])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      adopt(await verifyEmail(email.trim(), code.trim()))
      navigate('/discovery', { replace: true })
    } catch (err) {
      setError(err instanceof AuthApiError ? err.message : 'Could not verify that code.')
    } finally {
      setBusy(false)
    }
  }

  const resend = async () => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const sent = await resendOtp(email.trim(), 'email_verification')
      setDebugCode(sent.debug_code)
      setNotice(
        sent.email_sent
          ? 'A new code is on its way to your inbox.'
          : 'A new code was issued. Email is not configured here, so check the server log.',
      )
      /* The old code was invalidated server-side, so anything half-typed in the
         box is now wrong and would read as "incorrect code" rather than
         "stale". */
      setCode('')
    } catch (err) {
      setError(err instanceof AuthApiError ? err.message : 'Could not send a new code.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout
      title="Check your email"
      subtitle={
        email ? (
          <>
            We sent a six-digit code to <strong className="text-ink">{email}</strong>.
          </>
        ) : (
          'Enter the address you registered with and the code we sent you.'
        )
      }
      footer={
        <Link to="/login" className="text-accent no-underline hover:underline">
          Back to sign in
        </Link>
      }
    >
      <form onSubmit={submit}>
        <Field label="Work email" htmlFor="verify-email" className="mb-4 text-left">
          <Input
            id="verify-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="name@yamaha-motor-india.com"
            autoComplete="email"
            required
          />
        </Field>
        <Field label="Verification code" htmlFor="verify-code" className="mb-5 text-left">
          <Input
            id="verify-code"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
            placeholder="000000"
            inputMode="numeric"
            autoComplete="one-time-code"
            className="tracking-[0.5em] text-center text-[18px] font-semibold"
            required
          />
        </Field>

        {debugCode ? (
          <FormNotice
            message={
              <>
                Development server — your code is{' '}
                <strong className="tracking-[0.2em]">{debugCode}</strong>
              </>
            }
          />
        ) : null}
        <FormNotice message={notice} />
        <FormError message={error} />

        <Button
          type="submit"
          variant="primary"
          block
          className="py-[11px] whitespace-nowrap"
          disabled={busy || code.length < 6}
        >
          {busy ? 'Verifying…' : 'Verify and continue'}
        </Button>

        <Button
          variant="ghost"
          block
          className="mt-3 whitespace-nowrap"
          disabled={busy || !email}
          onClick={resend}
        >
          Send a new code
        </Button>
      </form>
    </AuthLayout>
  )
}
