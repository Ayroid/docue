import { useEffect, useState } from 'react'
import { listTemplates, TemplateApiError, type TemplateOut } from '@/services/templates'

/**
 * `GET /templates` with the loading/error states both consumers need —
 * Discovery's "Real Templates" rail and the document library page. Kept as one
 * hook so the two stay in step: whatever the backend lists is exactly what the
 * library can preview.
 */
export function useRealTemplates() {
  const [templates, setTemplates] = useState<TemplateOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listTemplates()
      .then((result) => {
        if (!cancelled) setTemplates(result)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof TemplateApiError ? err.message : 'Could not load templates.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return { templates, loading, error }
}
