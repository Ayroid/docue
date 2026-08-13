import type { TemplateOut } from '@/services/templates'

/**
 * Local **browse** filter over the templates the backend already returned —
 * not search. Real search is `searchTemplates()` in `@/services/templates`,
 * which calls `POST /api/v1/search` and returns ranked hits with per-signal
 * scores; use it for anything the user typed a query into.
 *
 * This is what backs the empty-query library view and Discovery's rail, where
 * there is no query to rank and a round trip would buy nothing. `GET /templates`
 * is unpaginated and small, so filtering in the browser is honest and immediate.
 *
 * The invented relevance scoring that used to live here — semantic similarity,
 * team usage, recency, and a "why this matched" breakdown — is gone. Those
 * numbers were generated from a result's position in the list, so they
 * described nothing.
 *
 * Words of two characters or fewer are dropped; matching "of" against every
 * template makes the result set meaningless.
 */
export function filterTemplates(templates: TemplateOut[], query: string, format: string): TemplateOut[] {
  const q = query.trim().toLowerCase()
  const words = q ? q.split(/\s+/).filter((w) => w.length > 2) : []

  return templates.filter((t) => {
    if (format !== 'all' && t.format !== format) return false
    if (!words.length) return true
    const hay = `${t.title} ${t.original_filename} ${t.format}`.toLowerCase()
    return words.some((w) => hay.includes(w))
  })
}
