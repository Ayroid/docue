import { useEffect, useRef, useState } from 'react'
import type { TemplateFormat } from '@/services/templates'
import { DocumentPreviewSkeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

type Status = 'loading' | 'ready' | 'error'

/**
 * Renders a docx/xlsx/pptx entirely client-side — no LibreOffice, no Office
 * Online iframe. `loadBytes` decouples this from *how* the bytes arrive (a
 * local `File` on Upload, a fetch against the backend on TemplateDetail);
 * callers must keep its identity stable (`useCallback`) or this effect loops.
 */
export function DocumentPreview({
  format,
  fileName,
  loadBytes,
  className = 'rounded-[8px] bg-surface',
  surfaceClassName = 'document-preview-surface max-h-[70vh] overflow-auto',
}: {
  format: TemplateFormat
  fileName: string
  loadBytes: () => Promise<ArrayBuffer>
  /** Defaults suit an inline panel; the full-page viewer overrides both so the
      document fills the page and scrolls with it rather than in a sub-box. */
  className?: string
  surfaceClassName?: string
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<Status>('loading')

  useEffect(() => {
    let cancelled = false
    /* Renderers hand back a teardown (pptx has a ResizeObserver to disconnect);
       the ones with nothing to undo return a no-op. */
    let cleanup: (() => void) | undefined
    setStatus('loading')

    const run = async () => {
      try {
        const buf = await loadBytes()
        if (cancelled || !containerRef.current) return
        containerRef.current.innerHTML = ''

        if (format === 'docx') {
          const { renderDocx } = await import('./docx')
          cleanup = await renderDocx(containerRef.current, buf)
        } else if (format === 'xlsx') {
          const { renderXlsx } = await import('./xlsx')
          await renderXlsx(containerRef.current, buf)
        } else {
          const { renderPptx } = await import('./pptx')
          cleanup = await renderPptx(containerRef.current, buf)
        }

        // The effect may have been torn down while the render was in flight.
        if (cancelled) {
          cleanup?.()
          return
        }
        setStatus('ready')
      } catch (err) {
        // Log the real cause for debugging, but don't surface a library's raw
        // internal error text (e.g. JSZip's) to the user.
        console.error('DocumentPreview render failed:', err)
        if (!cancelled) setStatus('error')
      }
    }

    run()
    return () => {
      cancelled = true
      cleanup?.()
    }
  }, [format, loadBytes])

  return (
    <div className={className}>
      {/* Shaped like the file that is coming — a page for docx/pptx, a grid for
          xlsx — so the placeholder occupies the space the render will land in
          rather than collapsing the panel to one line of text and then
          expanding it. `fileName` moves into the skeleton's accessible label,
          which is where a caption that nobody reads belongs. */}
      {status === 'loading' ? (
        <DocumentPreviewSkeleton variant={format === 'xlsx' ? 'sheet' : 'page'} fileName={fileName} />
      ) : null}
      {status === 'error' ? (
        <p className="text-[13px] text-accent2-700 py-8 px-4 m-0 text-center">
          Preview unavailable — download the file to view it.
        </p>
      ) : null}
      {/* `doc-render-root` keeps the app's typography from inheriting into the
          rendered file — see the note in styles/components.css. */}
      <div ref={containerRef} className={status === 'ready' ? cn('doc-render-root', surfaceClassName) : 'hidden'} />
    </div>
  )
}
