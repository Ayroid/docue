import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AuthApiError, register } from '@/services/auth'
import { Button } from '@/components/ui/button'
import { Field, Input } from '@/components/ui/input'
import { AuthLayout, FormError } from '@/pages/auth/AuthLayout'

/* Mirrors `app/core/security.py::password_problem`. Checked here purely to
   give the answer without a round trip -- the server enforces the same rules
   and is the one that decides, so the two can never disagree in a way that
   matters. */
function passwordProblem(password: string): string | null {
  if (password.length < 8) return 'Password must be at least 8 characters.'
  if (password === password.toLowerCase() || password === password.toUpperCase()) {
    return 'Password must contain both upper and lower case letters.'
  }
  if (!/\d/.test(password)) return 'Password must contain at least one digit.'
  return null
}

export function Register() {
  const navigate = useNavigate()

  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
      const sent = await register({
        email: email.trim(),
        username: username.trim(),
        password,
        full_name: fullName.trim() || undefined,
      })
      /* The account exists but cannot sign in yet. Carry the address and, in
         local dev, the code itself straight to the verification screen so
         nobody has to retype either. */
      navigate('/verify-email', {
        state: { email: sent.email, debugCode: sent.debug_code, emailSent: sent.email_sent },
      })
    } catch (err) {
      setError(err instanceof AuthApiError ? err.message : 'Could not create that account.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout
      title="Create your account"
      subtitle="We'll email you a code to confirm the address."
      footer={
        <>
          <span className="text-neutral-700">Already have an account? </span>
          <Link to="/login" className="text-accent no-underline hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={submit}>
        <Field label="Full name" htmlFor="reg-name" className="mb-4 text-left">
          <Input
            id="reg-name"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            placeholder="Riya Mehta"
            autoComplete="name"
          />
        </Field>
        <Field label="Work email" htmlFor="reg-email" className="mb-4 text-left">
          <Input
            id="reg-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="name@yamaha-motor-india.com"
            autoComplete="email"
            required
          />
        </Field>
        <Field label="Username" htmlFor="reg-username" className="mb-4 text-left">
          <Input
            id="reg-username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="riya.mehta"
            autoComplete="username"
            minLength={3}
            maxLength={64}
            required
          />
        </Field>
        <Field label="Password" htmlFor="reg-pass" className="mb-1 text-left">
          <Input
            id="reg-pass"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            autoComplete="new-password"
            required
          />
        </Field>
        <p className="text-label-md text-neutral-600 mb-4 mt-0">
          At least 8 characters, with upper and lower case and a digit.
        </p>
        <Field label="Confirm password" htmlFor="reg-confirm" className="mb-5 text-left">
          <Input
            id="reg-confirm"
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            placeholder="••••••••"
            autoComplete="new-password"
            required
          />
        </Field>

        <FormError message={error} />

        <Button type="submit" variant="primary" block className="py-[11px] whitespace-nowrap" disabled={busy}>
          {busy ? 'Creating account…' : 'Create account'}
        </Button>
      </form>
    </AuthLayout>
  )
}
