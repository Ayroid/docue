import type { ReactNode } from 'react'
import type { Fmt } from '@/data/catalog'
import { PREVIEW_LINES } from '@/data/demo'
import type { TemplateFormat } from '@/services/templates'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/ui/icon'

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
  const fontSize = size >= 40 ? 11 : size >= 34 ? 10 : 9.5
  return (
    <div
      className={cn(
        /* A rounded square tile, as the design uses for document icons —
           not the prototype's circular disc. */
        'flex-none rounded-md grid place-items-center font-semibold tracking-wide',
        tone === 'accent' ? 'bg-accent-100 text-accent-700' : 'bg-accent2-100 text-accent2-700',
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
      className="flex-none rounded-pill bg-accent2-900 text-white grid place-items-center text-[12px] font-bold"
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
  const disc = size === 'lg' ? 72 : 64
  return (
    <div
      className={cn(
        'text-center bg-surface border border-divider rounded-card',
        size === 'lg' ? 'py-16 px-5' : 'py-12 px-5',
      )}
    >
      <div
        className="rounded-pill bg-neutral-200 text-neutral-500 mx-auto mb-5 grid place-items-center"
        style={{ width: disc, height: disc }}
      >
        <Icon name="folder_open" size={30} />
      </div>
      <h4 className="mb-2 text-title-lg">{title}</h4>
      <p className="text-neutral-700 text-body-md max-w-[46ch] mx-auto mb-5">{body}</p>
      {action ? (
        <Button variant="primary" onClick={action.onClick}>
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
    <div className={cn(center && 'text-center', className)}>
      {children}
      <h2 className="text-headline-lg text-ink mb-1">{title}</h2>
      {subtitle ? <p className="text-neutral-700 text-body-md m-0">{subtitle}</p> : null}
    </div>
  )
}

/**
 * The standard page frame. Gutters and the max width now come from AppShell's
 * container, so this only supplies vertical rhythm and the entry animation.
 */
export function PageBody({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('flex flex-col gap-8 animate-hubfade-fast', className)}>{children}</div>
}
