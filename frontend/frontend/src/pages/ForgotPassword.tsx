import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AuthApiError, forgotPassword } from '@/services/auth'
import { Button } from '@/components/ui/button'
import { Field, Input } from '@/components/ui/input'
import { AuthLayout, FormError } from '@/pages/auth/AuthLayout'

/**
 * Ask for a reset code.
 *
 * The server answers the same way whether or not the address has an account —
 * it will not tell an anonymous caller who is registered — so this screen must
 * not imply otherwise. It says "if that address has an account" and moves on
 * to the code entry either way, which is also the honest UI: a person who
 * mistyped their address needs to reach the next screen to notice.
 *
 * There is no `debug_code` here even in local dev, deliberately: the response
 * has to look identical for a real and an invented address, and a field that
 * appeared only for real ones would be exactly the oracle the API avoids. The
 * code is in the server log.
 */
export function ForgotPassword() {
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await forgotPassword(email.trim())
      navigate('/reset-password', { state: { email: email.trim() } })
    } catch (err) {
      setError(err instanceof AuthApiError ? err.message : 'Could not start a password reset.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout
      title="Reset your password"
      subtitle="Enter your work email and we'll send you a code."
      footer={
        <Link to="/login" className="text-accent no-underline hover:underline">
          Back to sign in
        </Link>
      }
    >
      <form onSubmit={submit}>
        <Field label="Work email" htmlFor="forgot-email" className="mb-5 text-left">
          <Input
            id="forgot-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="name@yamaha-motor-india.com"
            autoComplete="email"
            required
          />
        </Field>

        <FormError message={error} />

        <Button type="submit" variant="primary" block className="py-[11px] whitespace-nowrap" disabled={busy}>
          {busy ? 'Sending…' : 'Send reset code'}
        </Button>
      </form>
    </AuthLayout>
  )
}
