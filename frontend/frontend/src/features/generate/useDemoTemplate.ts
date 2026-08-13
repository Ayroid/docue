import { useEffect, useState } from 'react'
import type { Fmt } from '@/data/catalog'
import { FALLBACK_TEMPLATE, type DemoTemplate } from '@/data/demo'
import { getTemplate, type TemplateFormat } from '@/services/templates'

const FMT_BY_FORMAT: Record<TemplateFormat, Fmt> = { docx: 'DOC', xlsx: 'XLS', pptx: 'PPT' }

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/**
 * Adapts a real backend template into the shape the generation walkthrough
 * works from, so the demo at least starts from a document that genuinely
 * exists — its real title, format and version number.
 *
 * Everything the walkthrough does *with* it is still scripted (see
 * `data/demo.ts`). If the id doesn't resolve, it falls back rather than
 * failing, because the walkthrough is a demonstration and shouldn't dead-end.
 */
export function useDemoTemplate(id: string | undefined): DemoTemplate {
  const [template, setTemplate] = useState<DemoTemplate>(FALLBACK_TEMPLATE)

  useEffect(() => {
    /* Only real backend ids are worth a request — the fallback's own id would
       come back 422 from a route typed to accept a UUID. */
    if (!id || !UUID.test(id)) return
    let cancelled = false

    getTemplate(id)
      .then((real) => {
        if (cancelled) return
        setTemplate({
          id: real.id,
          name: real.title,
          version: String(real.current_version?.version_number ?? 1),
          fmt: FMT_BY_FORMAT[real.format] ?? 'DOC',
        })
      })
      .catch(() => {
        /* Left on the fallback — the walkthrough still runs. */
      })

    return () => {
      cancelled = true
    }
  }, [id])

  return template
}
