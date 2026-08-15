import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/ui/icon'

/**
 * The frame every signed-out screen shares: brand bar, centred card.
 *
 * Lifted out of `Login` rather than copied into five files — the five auth
 * screens are one flow, and a card that drifts a few pixels between "sign in"
 * and "enter your code" reads as a different site mid-signup.
 */
export function AuthLayout({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string
  subtitle?: ReactNode
  children: ReactNode
  footer?: ReactNode
}) {
  const navigate = useNavigate()

  return (
    <div className="min-h-screen flex flex-col animate-hubfade-fast">
      <div className="py-5 px-[clamp(20px,5vw,56px)] flex items-center gap-[10px]">
        <Button className="flex items-center gap-[10px] py-[6px] px-2" onClick={() => navigate('/')}>
          <div className="w-10 h-10 rounded-md bg-accent2-900 text-white grid place-items-center">
            <Icon name="hub" size={22} />
          </div>
          <span className="font-heading text-headline-md text-accent2-900 tracking-tight">Docue</span>
        </Button>
      </div>

      <div className="flex-1 grid place-items-center py-[clamp(16px,4vw,48px)] px-[clamp(20px,5vw,56px)] pb-[clamp(40px,6vw,72px)]">
        <div className="w-full max-w-[460px] bg-surface border border-divider rounded-card p-[clamp(28px,4vw,44px)] grid justify-items-center shadow-elev-md">
          <div className="w-full max-w-[380px]">
            <h3 className="text-headline-md mb-2 text-center">{title}</h3>
            {subtitle ? (
              <p className="text-body-md text-neutral-700 mb-7 text-center">{subtitle}</p>
            ) : null}
            {children}
            {footer ? <div className="mt-6 text-center text-body-md">{footer}</div> : null}
          </div>
        </div>
      </div>
    </div>
  )
}

/** The inline error strip these forms show above their submit button.
 *
 *  `role="alert"` so a screen reader announces a failed sign-in — without it
 *  the message appears silently and the form looks like it did nothing. */
export function FormError({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <p
      role="alert"
      className="text-body-md text-[color:var(--md-error)] bg-[color:var(--md-error)]/10 border border-[color:var(--md-error)]/30 rounded-lg py-[10px] px-3 m-0 mb-4"
    >
      {message}
    </p>
  )
}

/** Confirmation that something worked, in the same slot as `FormError`. */
export function FormNotice({ message }: { message: ReactNode | null }) {
  if (!message) return null
  return (
    <p className="text-body-md text-accent2-900 bg-accent2-100 border border-accent2-400/40 rounded-lg py-[10px] px-3 m-0 mb-4">
      {message}
    </p>
  )
}
