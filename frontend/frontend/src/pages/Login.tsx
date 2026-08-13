import type { FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useHub } from '@/store/HubProvider'
import { Button } from '@/components/ui/button'
import { Field, Input } from '@/components/ui/input'
import { Icon } from '@/components/ui/icon'

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
          <div className="w-10 h-10 rounded-md bg-accent2-900 text-white grid place-items-center">
            <Icon name="hub" size={22} />
          </div>
          <span className="font-heading text-headline-md text-accent2-900 tracking-tight">TemplateHub</span>
        </Button>
      </div>

      <div className="flex-1 grid place-items-center py-[clamp(16px,4vw,48px)] px-[clamp(20px,5vw,56px)] pb-[clamp(40px,6vw,72px)]">
        <div className="w-full max-w-[460px] bg-surface border border-divider rounded-card p-[clamp(28px,4vw,44px)] grid justify-items-center shadow-elev-md">
          <form onSubmit={signIn} className="w-full max-w-[380px] text-center">
            <h3 className="text-headline-md mb-2">Sign in</h3>
            <p className="text-body-md text-neutral-700 mb-7">Use your work email address.</p>

            <Field label="Work email" htmlFor="hub-email" className="mb-4 text-left">
              <Input id="hub-email" type="email" placeholder="name@yamaha-motor-india.com" required />
            </Field>
            <Field label="Password" htmlFor="hub-pass" className="mb-3 text-left">
              <Input id="hub-pass" type="password" placeholder="••••••••" required />
            </Field>

            <div className="flex justify-center mb-[22px]">
              <a href="#" className="text-body-md text-accent no-underline hover:underline">
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
