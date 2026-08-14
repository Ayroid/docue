import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { AuthApiError, resendOtp, resetPassword } from '@/services/auth'
import { PASSWORD_HINT, passwordProblem } from '@/lib/password'
import { Button } from '@/components/ui/button'
import { Field, Input } from '@/components/ui/input'
import { AuthLayout, FormError, FormNotice } from '@/pages/auth/AuthLayout'

/**
 * Redeem a reset code and set a new password.
 *
 * Ends at the login form rather than signing the user straight in. Unlike
 * email verification, the person here has just proved only *one* thing —
 * access to the mailbox — and has by definition forgotten the password. Typing
 * the new one once, deliberately, is what confirms they can actually use it.
 */
export function ResetPassword() {
  const navigate = useNavigate()
  const location = useLocation()
  const state = (location.state ?? null) as { email?: string } | null

  const [email, setEmail] = useState(state?.email ?? '')
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()

    if (password !== confirm) {
      setError('Those passwords do not match.')
      return
    }
    const problem = passwordProblem(password)
    if (problem !== null) {
      setError(problem)
      return
    }

    setBusy(true)
    setError(null)
    try {
      await resetPassword(email.trim(), code.trim(), password)
      navigate('/login', {
        replace: true,
        state: { notice: 'Password updated. Sign in with your new password.' },
      })
    } catch (err) {
      setError(err instanceof AuthApiError ? err.message : 'Could not reset that password.')
    } finally {
      setBusy(false)
    }
  }

  const resend = async () => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const sent = await resendOtp(email.trim(), 'password_reset')
      setNotice(
        sent.email_sent
          ? 'A new code is on its way to your inbox.'
          : 'A new code was issued. Email is not configured here, so check the server log.',
      )
      setCode('')
    } catch (err) {
      setError(err instanceof AuthApiError ? err.message : 'Could not send a new code.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout
      title="Choose a new password"
      subtitle={
        email ? (
          <>
            If <strong className="text-ink">{email}</strong> has an account, a code is on its way.
          </>
        ) : (
          'Enter your email, the code we sent, and a new password.'
        )
      }
      footer={
        <Link to="/login" className="text-accent no-underline hover:underline">
          Back to sign in
        </Link>
      }
    >
      <form onSubmit={submit}>
        <Field label="Work email" htmlFor="reset-email" className="mb-4 text-left">
          <Input
            id="reset-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="name@yamaha-motor-india.com"
            autoComplete="email"
            required
          />
        </Field>
        <Field label="Reset code" htmlFor="reset-code" className="mb-4 text-left">
          <Input
            id="reset-code"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
            placeholder="000000"
            inputMode="numeric"
            autoComplete="one-time-code"
            className="tracking-[0.5em] text-center text-[18px] font-semibold"
            required
          />
        </Field>
        <Field label="New password" htmlFor="reset-pass" className="mb-1 text-left">
          <Input
            id="reset-pass"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            autoComplete="new-password"
            required
          />
        </Field>
        <p className="text-label-md text-neutral-600 mb-4 mt-0">{PASSWORD_HINT}</p>
        <Field label="Confirm new password" htmlFor="reset-confirm" className="mb-5 text-left">
          <Input
            id="reset-confirm"
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            placeholder="••••••••"
            autoComplete="new-password"
            required
          />
        </Field>

        <FormNotice message={notice} />
        <FormError message={error} />

        <Button
          type="submit"
          variant="primary"
          block
          className="py-[11px] whitespace-nowrap"
          disabled={busy || code.length < 6}
        >
          {busy ? 'Updating…' : 'Update password'}
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
