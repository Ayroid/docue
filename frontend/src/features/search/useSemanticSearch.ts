import { useEffect, useState } from 'react'

import { searchTemplates, TemplateApiError, type SearchResponse } from '@/services/templates'

/**
 * Run `POST /search` for a query, replacing the client-side filter.
 *
 * The backend fuses a keyword ranking with a vector ranking, so this is the
 * only way to match a query that shares no words with a template's title --
 * "record what we agreed and who's doing what" finds the Minutes of Meeting
 * form through its generated purpose, which no client-side substring filter
 * could ever do.
 *
 * An empty query is not sent. `POST /search` answers a blank query with no
 * results, but the page is also the library's browse view, so the caller falls
 * back to listing everything instead of showing "nothing found".
 *
 * Results are dropped if the query changed while the request was in flight --
 * typing quickly would otherwise let a slower earlier response overwrite a
 * faster later one. Search runs ~1.5s here, most of it embedding the query, so
 * that race is easy to hit rather than theoretical.
 */
export interface SemanticSearchState {
  response: SearchResponse | null
  loading: boolean
  error: string | null
}

export function useSemanticSearch(query: string, topK = 25): SemanticSearchState {
  const [response, setResponse] = useState<SearchResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const trimmed = query.trim()
    if (!trimmed) {
      setResponse(null)
      setError(null)
      setLoading(false)
      return
    }

    let cancelled = false
    setLoading(true)
    setError(null)

    searchTemplates(trimmed, topK)
      .then((result) => {
        if (cancelled) return
        setResponse(result)
      })
      .catch((err) => {
        if (cancelled) return
        setResponse(null)
        setError(
          err instanceof TemplateApiError ? err.message : 'Search is unavailable right now.',
        )
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [query, topK])

  return { response, loading, error }
}
