import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'
import type { TemplateFormat } from '@/services/templates'
import { CHIP_BY_FORMAT, FormatChip } from '@/components/common'
import { DocumentPreview } from './DocumentPreview'

/**
 * A document presented as a document: an identifying bar naming the file,
 * above a full-bleed render of it on a neutral backdrop.
 *
 * Shared by the viewer tab (`/viewer/:id`) and the Upload page so a file looks
 * exactly the same before it is submitted as it does afterwards — the point of
 * previewing on Upload is to confirm you picked the right file, which only
 * works if it is the same picture.
 *
 * Sizing and scrolling are left to the caller: the viewer lets the whole page
 * scroll, while Upload pins the stage beside its form and scrolls it inside.
 */
export function DocumentStage({
  format,
  fileName,
  title,
  meta,
  loadBytes,
  leading,
  actions,
  className,
  bodyClassName,
}: {
  format: TemplateFormat
  fileName: string
  title: string
  meta?: string
  loadBytes: () => Promise<ArrayBuffer>
  /** Leading header content, before the format tile — a Back control, and so
      on. Navigation belongs on the left of what it navigates away from. */
  leading?: ReactNode
  /** Trailing header content — version tag, Download, and so on. */
  actions?: ReactNode
  className?: string
  bodyClassName?: string
}) {
  /* A spreadsheet fills its window edge to edge, so it gets a white backdrop.
     A document and a deck are pages sitting on a desk, so they keep the
     neutral one showing around their sheets. */
  const backdrop = format === 'xlsx' ? 'bg-white' : 'bg-neutral-200'

  return (
    <div className={cn('flex flex-col', backdrop, className)}>
      <header className="sticky top-0 z-10 flex items-center gap-3 flex-wrap bg-surface border-b border-divider py-[10px] px-[clamp(14px,3vw,28px)]">
        {leading}
        <FormatChip size={34}>{CHIP_BY_FORMAT[format]}</FormatChip>
        <div className="flex-1 min-w-0">
          <div className="font-heading text-[16px] leading-[1.2] truncate">{title}</div>
          {meta ? <div className="text-[11.5px] opacity-55 truncate">{meta}</div> : null}
        </div>
        {actions}
      </header>

      <div className={cn('flex-1 min-h-0', bodyClassName)}>
        <DocumentPreview
          format={format}
          fileName={fileName}
          loadBytes={loadBytes}
          className="min-h-full"
          /* No inner scrollbox — whatever the caller scrolls is the only
             scrollbar, so a long document reads as one run of pages. */
          surfaceClassName="min-h-full"
        />
      </div>
    </div>
  )
}
