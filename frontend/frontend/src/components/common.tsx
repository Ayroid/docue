import type { ReactNode } from 'react'
import type { Fmt } from '@/data/catalog'
import { PREVIEW_LINES } from '@/data/demo'
import type { TemplateFormat } from '@/services/templates'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

/** Real templates carry a file extension; the chip speaks the prototype's Fmt. */
export const CHIP_BY_FORMAT: Record<TemplateFormat, Fmt> = {
  docx: 'DOC',
  xlsx: 'XLS',
  pptx: 'PPT',
}

/**
 * The circular format chip (DOC / XLS / PPT) used at four different sizes
 * across the bundle. The prototype scales the font with the disc; keep the
 * pairs together so they stay in proportion.
 */
export function FormatChip({
  children,
  size = 40,
  tone = 'accent',
  className,
}: {
  children: ReactNode
  size?: 30 | 32 | 34 | 38 | 40
  tone?: 'accent' | 'accent2'
  className?: string
}) {
  const fontSize = size >= 40 ? 10 : size >= 34 ? 9.5 : 9
  return (
    <div
      className={cn(
        'flex-none rounded-pill grid place-items-center font-heading',
        tone === 'accent' ? 'bg-accent-200 text-accent-800' : 'bg-accent2-200 text-accent2-900',
        className,
      )}
      style={{ width: size, height: size, fontSize }}
    >
      {children}
    </div>
  )
}

/** Person avatar — initials on the second-accent ramp. */
export function Avatar({ initials, size = 34 }: { initials: string; size?: number }) {
  return (
    <div
      className="flex-none rounded-pill bg-accent2-300 text-accent2-900 grid place-items-center text-[13px] font-bold"
      style={{ width: size, height: size }}
    >
      {initials}
    </div>
  )
}

/**
 * Marks a screen whose content is scripted rather than real. Used across the
 * generation walkthrough, which has no service behind it — see `data/demo.ts`.
 */
export function DemoBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-[6px] rounded-tag border border-dashed border-accent2-400 bg-accent2-100 text-accent2-900 text-[11px] font-semibold uppercase tracking-[.08em] py-[3px] px-[9px] whitespace-nowrap',
        className,
      )}
      title="Scripted walkthrough — the document produced here is not stored anywhere"
    >
      Demo
    </span>
  )
}

/**
 * The grey bar skeleton standing in for rendered document body text, used by
 * the generation walkthrough's preview. Real documents are rendered from their
 * actual bytes by `features/document-preview` instead.
 */
export function PreviewLines({ lines = PREVIEW_LINES, flat = false }: { lines?: typeof PREVIEW_LINES; flat?: boolean }) {
  return (
    <>
      {lines.map((l, i) => (
        <div
          key={i}
          className="bg-neutral-300 rounded-[6px]"
          style={{
            height: l.h,
            width: l.w,
            marginBottom: flat ? undefined : l.mb,
            opacity: flat ? 0.55 : 0.7,
          }}
        />
      ))}
    </>
  )
}

export function EmptyState({
  title,
  body,
  action,
  size = 'lg',
}: {
  title: string
  body: string
  action?: { label: string; onClick: () => void }
  size?: 'lg' | 'md'
}) {
  const disc = size === 'lg' ? 76 : 72
  return (
    <div className={cn('text-center', size === 'lg' ? 'py-16 px-5' : 'py-14 px-5')}>
      <div
        className="rounded-pill bg-accent2-100 mx-auto mb-[18px]"
        style={{ width: disc, height: disc }}
      />
      <h4 className="mb-2">{title}</h4>
      <p className="opacity-65 text-[14px] max-w-[38ch] mx-auto mb-[18px]">{body}</p>
      {action ? (
        <Button variant="secondary" onClick={action.onClick}>
          {action.label}
        </Button>
      ) : null}
    </div>
  )
}

/** Page heading block — centred on Discovery, left-aligned everywhere else. */
export function PageHeading({
  title,
  subtitle,
  center = false,
  className,
  children,
}: {
  title: string
  subtitle?: string
  center?: boolean
  className?: string
  children?: ReactNode
}) {
  return (
    <div className={cn(center ? 'text-center mb-[18px]' : 'mb-[22px]', className)}>
      {children}
      <h2 className="text-[clamp(26px,3vw,36px)] mb-1">{title}</h2>
      {subtitle ? <p className="opacity-65 text-[14px] m-0">{subtitle}</p> : null}
    </div>
  )
}

/** The standard page frame: consistent gutters and the entry animation. */
export function PageBody({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn('pt-[6px] px-[clamp(18px,3vw,36px)] pb-12 animate-hubfade-fast', className)}>
      {children}
    </div>
  )
}
