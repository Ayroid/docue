import type { FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useHub } from '@/store/HubProvider'
import { Button } from '@/components/ui/button'
import { Field, Input } from '@/components/ui/input'

export function Login() {
  const navigate = useNavigate()
  const { login } = useHub()

  const signIn = (e: FormEvent) => {
    e.preventDefault()
    login()
    navigate('/discovery')
  }

  return (
    <div className="min-h-screen flex flex-col animate-hubfade-fast">
      <div className="py-5 px-[clamp(20px,5vw,56px)] flex items-center gap-[10px]">
        <Button className="flex items-center gap-[10px] py-[6px] px-2" onClick={() => navigate('/')}>
          <div className="w-[30px] h-[30px] rounded-pill bg-accent grid place-items-center text-bg font-heading text-[14px]">
            T
          </div>
          <span className="font-heading text-[17px]">YMSLI Template Hub</span>
        </Button>
      </div>

      <div className="flex-1 grid place-items-center py-[clamp(16px,4vw,48px)] px-[clamp(20px,5vw,56px)] pb-[clamp(40px,6vw,72px)]">
        <div className="w-full max-w-[480px] bg-surface rounded-card p-[clamp(28px,4vw,44px)] grid justify-items-center">
          <form onSubmit={signIn} className="w-full max-w-[380px] text-center">
            <h3 className="text-[29px] mb-[6px]">Sign in</h3>
            <p className="opacity-65 text-[14px] mb-[26px]">Use your work email address.</p>

            <Field label="Work email" htmlFor="hub-email" className="mb-4 text-left">
              <Input id="hub-email" type="email" placeholder="name@yamaha-motor-india.com" required />
            </Field>
            <Field label="Password" htmlFor="hub-pass" className="mb-3 text-left">
              <Input id="hub-pass" type="password" placeholder="••••••••" required />
            </Field>

            <div className="flex justify-center mb-[22px]">
              <a href="#" className="text-[13px]">
                Forgot password?
              </a>
            </div>

            <Button type="submit" variant="primary" block className="py-[11px] whitespace-nowrap">
              Sign in
            </Button>
          </form>
        </div>
      </div>
    </div>
  )
}
